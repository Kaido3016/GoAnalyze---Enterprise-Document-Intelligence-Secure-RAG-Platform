"""Curated official-source registry and controlled ingestion CLI.

Sources are fetched only from a fixed allowlist of government legislation
domains. Downloaded content remains pending human review until an authorized
platform administrator approves the source version. Nothing here constitutes
legal advice or automatically establishes applicability to a specific case.
Run: python -m gov_platform.regulatory_sources seed
     python -m gov_platform.regulatory_sources sync
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select

from .db.models import RegulatoryChunkORM, RegulatorySourceORM
from .db.session import get_sessionmaker
from .rag import ProviderUnavailable, rag_service, split_text

ALLOWED_HOSTS = {"legisquebec.gouv.qc.ca", "laws-lois.justice.gc.ca"}
SOURCE_CATALOG = (
    ("QC", "Environment Quality Act (chapter Q-2)", "https://www.legisquebec.gouv.qc.ca/en/document/cs/Q-2", "legisquebec.gouv.qc.ca"),
    ("QC", "Regulation respecting the regulatory scheme applying to activities on the basis of their environmental impact", "https://www.legisquebec.gouv.qc.ca/en/document/cr/Q-2,%20r.%2017.1", "legisquebec.gouv.qc.ca"),
    ("QC", "Land Protection and Rehabilitation Regulation", "https://www.legisquebec.gouv.qc.ca/en/document/cr/q-2,%20r.%2037", "legisquebec.gouv.qc.ca"),
    ("CA", "Canadian Environmental Protection Act, 1999", "https://laws-lois.justice.gc.ca/eng/acts/c-15.31/", "laws-lois.justice.gc.ca"),
    ("CA", "Impact Assessment Act", "https://laws-lois.justice.gc.ca/eng/acts/I-2.75/", "laws-lois.justice.gc.ca"),
)
MAX_SOURCE_CHARS = 2_000_000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "nav", "footer", "header", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "nav", "footer", "header", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())


def _validate_official_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("regulatory_source_url_not_allowlisted")


async def seed_sources() -> int:
    sessionmaker = get_sessionmaker()
    inserted = 0
    async with sessionmaker() as session:
        existing = set((await session.execute(select(RegulatorySourceORM.official_url))).scalars().all())
        for jurisdiction, title, url, domain in SOURCE_CATALOG:
            _validate_official_url(url)
            if url in existing:
                continue
            session.add(
                RegulatorySourceORM(
                    jurisdiction=jurisdiction,
                    title=title,
                    official_url=url,
                    authority_domain=domain,
                    status="catalogued_not_ingested",
                )
            )
            inserted += 1
        await session.commit()
    return inserted


async def _download_source(url: str) -> str:
    _validate_official_url(url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(45.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": "GoAnalyze-RegulatorySourceIndexer/1.0"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        _validate_official_url(str(response.url))
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and "text/plain" not in content_type:
            raise ValueError("regulatory_source_not_html_or_text")
        raw = response.text
    parser = _TextExtractor()
    parser.feed(raw)
    text = re.sub(r"[ \t]+", " ", "\n".join(parser.parts))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 100:
        raise ValueError("regulatory_source_text_too_short")
    return text[:MAX_SOURCE_CHARS]


async def sync_sources() -> dict[str, int]:
    from .config import get_settings

    sessionmaker = get_sessionmaker()
    settings = get_settings()
    result = {"fetched_pending_review": 0, "failed": 0}
    async with sessionmaker() as session:
        source_refs = (await session.execute(
            select(RegulatorySourceORM.id, RegulatorySourceORM.official_url)
        )).all()
    for source_id, url in source_refs:
        try:
            text = await _download_source(url)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            parts = split_text(text, max_chars=1800, overlap=200)
            vectors = []
            for batch_start in range(0, len(parts), 32):
                vectors.extend(await rag_service.embed([part for part, _ in parts[batch_start : batch_start + 32]]))
            async with sessionmaker() as session:
                source = await session.get(RegulatorySourceORM, source_id)
                if source is None:
                    continue
                await session.execute(delete(RegulatoryChunkORM).where(RegulatoryChunkORM.source_id == source.id))
                source.content_text = text
                source.content_sha256 = digest
                version_match = re.search(
                    r"(?:updated to|current to|à jour au)\s+([^\n.]{3,100})",
                    text[:20000],
                    re.IGNORECASE,
                )
                source.source_version = version_match.group(1).strip() if version_match else None
                source.status = "fetched_pending_review"
                source.last_verified_at = datetime.now(UTC)
                source.reviewer = None
                session.add_all(
                    [
                        RegulatoryChunkORM(
                            source_id=source.id,
                            chunk_index=index,
                            content=part,
                            embedding=vector,
                            embedding_model=settings.embedding_model,
                            source_sha256=digest,
                        )
                        for index, ((part, _), vector) in enumerate(zip(parts, vectors, strict=True))
                    ]
                )
                await session.commit()
            result["fetched_pending_review"] += 1
        except (httpx.HTTPError, ValueError, ProviderUnavailable) as exc:
            result["failed"] += 1
            print(f"source sync failed: {url}: {type(exc).__name__}", file=sys.stderr)
    return result


async def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "seed"
    if command == "seed":
        print({"inserted": await seed_sources()})
    elif command == "sync":
        print(await sync_sources())
    else:
        raise SystemExit("usage: python -m gov_platform.regulatory_sources [seed|sync]")


if __name__ == "__main__":
    asyncio.run(main())
