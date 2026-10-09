from urllib.parse import urlparse

import httpx
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import gov_platform.regulatory_sources as sources
from gov_platform.db.models import RegulatorySourceORM


def urlparse_host(url: str) -> str | None:
    return urlparse(url).hostname


def test_catalog_contains_only_official_government_domains():
    assert sources.SOURCE_CATALOG
    for _jurisdiction, _title, url, domain in sources.SOURCE_CATALOG:
        sources._validate_official_url(url)
        assert urlparse_host(url) == domain


def test_source_url_allowlist_rejects_non_https_and_untrusted_hosts():
    with pytest.raises(ValueError, match="not_allowlisted"):
        sources._validate_official_url("http://laws-lois.justice.gc.ca/eng/acts/c-15.31/")
    with pytest.raises(ValueError, match="not_allowlisted"):
        sources._validate_official_url("https://attacker.example/law")
    with pytest.raises(ValueError, match="not_allowlisted"):
        sources._validate_official_url("https://laws-lois.justice.gc.ca:8443/eng/acts/c-15.31/")


def test_html_extractor_ignores_script_and_navigation_content():
    parser = sources._TextExtractor()
    parser.feed("<html><nav>Menu</nav><main>Official law text</main><script>secret()</script></html>")
    extracted = " ".join(parser.parts)
    assert "Official law text" in extracted
    assert "Menu" not in extracted
    assert "secret" not in extracted


async def test_seed_sources_is_idempotent(db_engine, monkeypatch):
    maker = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(sources, "get_sessionmaker", lambda: maker)
    inserted = await sources.seed_sources()
    inserted_again = await sources.seed_sources()
    async with maker() as session:
        count = (await session.execute(select(func.count()).select_from(RegulatorySourceORM))).scalar_one()
    assert inserted == len(sources.SOURCE_CATALOG)
    assert inserted_again == 0
    assert count == len(sources.SOURCE_CATALOG)


async def test_download_extracts_official_page_text_and_removes_scripts(monkeypatch):
    url = sources.SOURCE_CATALOG[0][2]
    response = httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        text="<html><nav>Menu</nav><main>Updated to 2026-09-01. " + ("Official statute text. " * 20)
        + "</main><script>secret()</script></html>",
        request=httpx.Request("GET", url),
    )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, requested_url):
            assert requested_url == url
            return response

    monkeypatch.setattr(sources.httpx, "AsyncClient", FakeClient)
    text = await sources._download_source(url)
    assert "Official statute text" in text
    assert "Menu" not in text
    assert "secret" not in text


async def test_download_rejects_redirect_to_untrusted_host(monkeypatch):
    url = sources.SOURCE_CATALOG[0][2]
    response = httpx.Response(
        302,
        headers={"location": "https://attacker.example/"},
        request=httpx.Request("GET", url),
    )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _requested_url):
            return response

    monkeypatch.setattr(sources.httpx, "AsyncClient", FakeClient)
    with pytest.raises(ValueError, match="not_allowlisted"):
        await sources._download_source(url)


async def test_sync_sources_persists_hash_and_pending_review_chunks(db_engine, monkeypatch):
    maker = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(sources, "get_sessionmaker", lambda: maker)
    await sources.seed_sources()

    async def fake_download(_url):
        return "Official consolidated law text. " * 40

    async def fake_embed(texts):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(sources, "_download_source", fake_download)
    monkeypatch.setattr(sources.rag_service, "embed", fake_embed)
    result = await sources.sync_sources()

    async with maker() as session:
        rows = (await session.execute(select(RegulatorySourceORM))).scalars().all()
        chunks = (await session.execute(select(sources.RegulatoryChunkORM))).scalars().all()
    assert result == {"fetched_pending_review": len(sources.SOURCE_CATALOG), "failed": 0}
    assert all(row.status == "fetched_pending_review" and row.content_sha256 for row in rows)
    assert all(chunk.source_sha256 for chunk in chunks)
