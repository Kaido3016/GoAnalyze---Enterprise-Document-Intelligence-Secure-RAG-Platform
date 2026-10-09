from uuid import UUID

from .models import (
    AIFinding,
    EnvironmentalReviewRequest,
    EnvironmentalReviewResult,
    EvidenceCitation,
)

REQUIRED_DOCUMENTS_BY_PROJECT = {
    "industrial_discharge": {
        "application_form",
        "site_plan",
        "effluent_characterization",
        "mitigation_plan",
        "public_consultation_record",
    },
    "waste_management": {
        "application_form",
        "site_plan",
        "waste_profile",
        "contingency_plan",
        "closure_plan",
    },
    "water_taking": {
        "application_form",
        "hydrogeology_report",
        "water_balance",
        "impact_assessment",
    },
}

REGULATIONS_BY_PROJECT = {
    "industrial_discharge": [
        "Environmental protection authorization discharge limits",
        "Surface water quality objective assessment",
        "Spill prevention and contingency planning",
    ],
    "waste_management": [
        "Waste classification and handling requirements",
        "Financial assurance and closure obligations",
        "Receiving site compatibility review",
    ],
    "water_taking": [
        "Water taking permit threshold analysis",
        "Cumulative watershed impact assessment",
        "Monitoring and reporting condition review",
    ],
}


class EnvironmentalAuthorizationEngine:
    def review(
        self,
        request: EnvironmentalReviewRequest,
        available_document_types: set[str],
        citations: list[EvidenceCitation],
    ) -> EnvironmentalReviewResult:
        required = REQUIRED_DOCUMENTS_BY_PROJECT.get(request.project_type, {"application_form"})
        missing = sorted(required - available_document_types)
        regulation_mappings = [
            AIFinding(
                finding_type="regulation_mapping",
                statement=regulation,
                confidence=0.0,
                citations=[],
                grounded=False,
                explanation=(
                    "Rule-based mapping from project type only. No authoritative regulatory "
                    "source was retrieved and verified for this mapping."
                ),
            )
            for regulation in REGULATIONS_BY_PROJECT.get(request.project_type, ["General authorization review"])
        ]
        compliance_findings = self._compliance_findings(request.case_id, missing, citations)
        # Risk scores remain unavailable until a representative, reviewed
        # benchmark supports a calibrated model. Checklist counts are not risk.
        risk_score = None
        recommendation = self._recommendation(missing, risk_score)
        justification = self._justification(missing, risk_score, regulation_mappings)
        return EnvironmentalReviewResult(
            case_id=request.case_id,
            admissible=len(missing) == 0,
            missing_documents=missing,
            regulation_mappings=regulation_mappings,
            compliance_findings=compliance_findings,
            risk_score=risk_score,
            recommendation=recommendation,
            justification=justification,
            requires_human_review=True,
        )

    def _compliance_findings(
        self, case_id: UUID, missing: list[str], citations: list[EvidenceCitation]
    ) -> list[AIFinding]:
        if missing:
            return [
                AIFinding(
                    finding_type="missing_document",
                    statement=f"Required document is missing: {name}",
                    confidence=0.0,
                    citations=[],
                    grounded=False,
                    explanation=(
                        f"Rule-based document-type checklist for case {case_id}; this is not "
                        "evidence that the underlying document content was reviewed."
                    ),
                )
                for name in missing
            ]
        return [
            AIFinding(
                finding_type="admissibility",
                statement="Required document set is complete for admissibility screening.",
                confidence=0.0,
                citations=[],
                grounded=False,
                explanation=(
                    "Declared document-type markers satisfy the configured checklist, but "
                    "document contents and authoritative regulatory sources were not verified."
                ),
            )
        ]

    def _risk_score(self, missing: list[str], findings: list[AIFinding]) -> float:
        base = 25.0
        missing_penalty = min(45.0, len(missing) * 9.0)
        confidence_penalty = sum(1.0 - finding.confidence for finding in findings) * 5.0
        return round(min(100.0, base + missing_penalty + confidence_penalty), 2)

    def _recommendation(self, missing: list[str], risk_score: float | None) -> str:
        if missing:
            return "request_additional_information"
        # Do not auto-advance a case when the evidence and risk model are unvalidated.
        return "refer_to_senior_technical_review"

    def _justification(self, missing: list[str], risk_score: float | None, mappings: list[AIFinding]) -> str:
        mapped = "; ".join(mapping.statement for mapping in mappings)
        if missing:
            return (
                f"Admissibility is incomplete because {len(missing)} required item(s) are absent. "
                f"Mapped obligations: {mapped}. Risk score is unavailable pending validated evidence and evaluation."
            )
        return f"The checklist is complete, but regulatory applicability and risk remain unverified. Mapped obligations: {mapped}. Risk score is unavailable pending validated evidence and evaluation."


engine = EnvironmentalAuthorizationEngine()

