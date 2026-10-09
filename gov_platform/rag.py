"""Grounded answer generation boundary.

This repository does not ship a configured generation provider yet. Until one is
configured and its output is validated against retrieved chunks, this service
must not synthesize a response by concatenating excerpts or assign confidence
from citation counts. It fails closed and reports the capability as unavailable.
"""
from .models import AIFinding, EvidenceCitation


class GroundedRagService:
    def answer(self, question: str, citations: list[EvidenceCitation]) -> AIFinding:
        """Return an explicit unavailable result until a real generator exists.

        Citations supplied by an API caller are not proof that an answer was
        generated from those sources. Retrieval, excerpt integrity checks, and
        a configured generator must be wired before this method can return a
        grounded answer.
        """
        del question
        return AIFinding(
            finding_type="rag_unavailable",
            statement=(
                "No answer was generated. A retrieval-backed generation provider "
                "is not configured, so the supplied excerpts are not presented "
                "as an AI-generated answer."
            ),
            confidence=0.0,
            citations=[],
            grounded=False,
            explanation=(
                "Grounded generation is unavailable. Caller-supplied citations "
                "are untrusted until they are resolved against indexed document "
                "chunks and validated by a configured generation provider."
            ),
        )


rag_service = GroundedRagService()
