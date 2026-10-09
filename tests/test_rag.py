import uuid

from gov_platform.models import EvidenceCitation
from gov_platform.rag import GroundedRagService


def test_service_never_claims_grounded_generation_without_provider():
    citation = EvidenceCitation(
        document_id=uuid.uuid4(),
        version=1,
        chunk_id="chunk-1",
        sha256="a" * 64,
        excerpt="Some supplied evidence.",
    )

    finding = GroundedRagService().answer("What does the document say?", [citation])

    assert finding.grounded is False
    assert finding.confidence == 0.0
    assert finding.citations == []
    assert finding.finding_type == "rag_unavailable"
    assert "No answer was generated" in finding.statement


def test_empty_evidence_is_not_presented_as_an_answer():
    finding = GroundedRagService().answer("Question without evidence", [])

    assert finding.grounded is False
    assert finding.confidence == 0.0
    assert finding.citations == []
