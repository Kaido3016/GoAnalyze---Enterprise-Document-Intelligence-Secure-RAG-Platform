from uuid import uuid4

from gov_platform.environmental_engine import engine
from gov_platform.models import EnvironmentalReviewRequest


def test_missing_documents_drive_admissibility_and_risk():
    request = EnvironmentalReviewRequest(
        tenant_id="env",
        case_id=uuid4(),
        project_type="industrial_discharge",
        location="North watershed",
        applicant="Example Applicant",
        documents=[],
    )

    result = engine.review(request, {"application_form"}, [])

    assert result.admissible is False
    assert "site_plan" in result.missing_documents
    assert result.risk_score is None
    assert result.recommendation == "request_additional_information"
    assert all(not finding.grounded for finding in result.regulation_mappings)
    assert all(finding.confidence == 0.0 for finding in result.regulation_mappings)
    assert all(not finding.grounded for finding in result.compliance_findings)

