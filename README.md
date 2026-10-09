# GoAnalyze — Enterprise Document Intelligence & Secure RAG Platform

> **Production-oriented AI engineering platform for secure document intelligence, retrieval-augmented generation, semantic search, multi-tenant access control, and auditable analysis.**

**RAG** · **LLM** · **Document Intelligence** · **Semantic Search** · **Multi-Tenancy** · **RBAC/ABAC** · **Observability** · **Docker** · **Kubernetes** · **Terraform**

## Overview

GoAnalyze is an enterprise-oriented document intelligence platform designed to process, search, analyze, and audit sensitive documents through a security-first architecture.

The project demonstrates how a modern AI application can combine the **AI layer and the production engineering layer**: document ingestion, retrieval, LLM analysis, authorization, tenant isolation, auditability, observability, automated testing, containerization, Kubernetes deployment, and infrastructure as code.

The goal is not to present a model demo, but to demonstrate the architecture required to operate a secure AI document platform in a realistic enterprise or government-oriented environment.

## What the platform demonstrates

- Document ingestion and processing
- Retrieval-Augmented Generation (RAG)
- Semantic and vector-based retrieval architecture
- LLM-powered document analysis
- Multi-tenant application architecture
- RBAC / ABAC authorization boundaries
- Tenant isolation
- Audit trails and evidence-oriented workflows
- Production Docker images
- Kubernetes deployment with Helm
- Infrastructure as Code with Terraform
- Observability foundations
- Automated testing
- Database migrations
- Nginx / reverse-proxy configuration

## Architecture

```text
                         Web Client
                            │
                            ▼
                    ┌───────────────┐
                    │ Nginx / API   │
                    │    Gateway    │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Application   │
                    │   Services    │
                    └───────┬───────┘
                            │
             ┌──────────────┼──────────────┐
             │              │              │
             ▼              ▼              ▼
      Document / RAG   Authorization   Audit / Evidence
         Pipeline       RBAC / ABAC       & Logging
             │              │
             ▼              ▼
      Search / Vector   Tenant Isolation
        Retrieval
             │
             ▼
       LLM Analysis
             │
             ▼
     Structured Result
```

## AI & Retrieval Pipeline

```text
Document
   │
   ▼
Ingestion
   │
   ▼
Document Processing
   │
   ▼
Chunking / Indexing
   │
   ▼
Embeddings / Semantic Retrieval
   │
   ▼
Relevant Context
   │
   ▼
LLM Analysis
   │
   ▼
Structured / User-facing Result
```

The architecture separates retrieval from generation so that retrieved context can be inspected and controlled before it reaches the model.

### AI engineering priorities

GoAnalyze treats RAG as an engineering system rather than simply an LLM prompt:

- Retrieval quality and relevance
- Context construction
- Access-controlled retrieval
- Tenant-aware data boundaries
- Structured model outputs
- Failure handling
- Auditability
- Latency and observability
- Evaluation and regression testing

Production deployments should validate retrieval quality, answer relevance, groundedness, latency, cost, and failure modes against representative evaluation datasets before making performance claims.

## Security Architecture

Security is a core architectural concern rather than an optional feature.

The platform includes engineering boundaries for:

- Authentication
- RBAC
- ABAC
- Tenant isolation
- Protected document workflows
- Audit trails
- Environment-based configuration
- Secure reverse-proxy deployment

Sensitive production data, credentials, and secrets must never be committed to source control.

For a real production deployment, security controls must be validated in the target environment through appropriate threat modeling, configuration review, penetration testing, identity integration, secrets management, encryption, monitoring, backup, and incident-response procedures.

## Multi-Tenancy

GoAnalyze is designed around explicit tenant-aware boundaries so that enterprise users can operate within isolated organizational contexts.

```text
Tenant A ─┐
          ├── Authorization ──► Application ──► Tenant-scoped data
Tenant B ─┘

                  │
                  ▼
              Audit Trail
```

Authorization is treated as part of the retrieval and document-access path, not only as a UI concern.

## Infrastructure

### Docker

```text
Dockerfile
Dockerfile.production
```

The repository includes separate containerization artifacts for development and production-oriented workflows.

### Kubernetes

```text
helm/
└── goanalyze-government/
```

### Infrastructure as Code

```text
terraform/
```

### Observability

```text
observability/
```

### Database

```text
migrations/
```

## Testing & Quality

The repository includes a dedicated test suite and CI configuration:

```text
tests/
.github/
```

Testing is integrated into the engineering workflow to cover application behavior and security-sensitive boundaries. Production acceptance should additionally include environment-specific integration, load, security, and AI evaluation testing.

## Production Engineering

GoAnalyze demonstrates the major layers required for an enterprise AI platform:

```text
AI / RAG
   │
   ├── Retrieval
   ├── Context construction
   └── LLM analysis

Application
   │
   ├── API
   ├── Authorization
   ├── Multi-tenancy
   └── Auditability

Platform
   │
   ├── Docker
   ├── Kubernetes / Helm
   ├── Terraform
   ├── Nginx
   └── Observability

Quality
   │
   ├── Automated tests
   ├── Database migrations
   └── CI/CD
```

## Repository Structure

```text
GoAnalyze/
├── frontend/
├── gov_platform/
├── helm/
├── migrations/
├── nginx/
├── observability/
├── terraform/
├── tests/
├── .github/
├── ARCHITECTURE.md
├── BUSINESS_CASE.md
├── EXECUTION_EVIDENCE.md
├── FINAL_DEPLOYMENT_REPORT.md
├── FINAL_OBSERVABILITY_REPORT.md
├── FINAL_PRODUCTION_READINESS.md
├── Dockerfile
├── Dockerfile.production
└── README.md
```

## Technology Areas

**Python · LLMs · RAG · Semantic Search · Document Intelligence · Docker · Kubernetes · Helm · Terraform · Nginx · Database Migrations · Automated Testing · Observability · RBAC · ABAC**

## Documentation

The repository includes technical documentation covering:

- Architecture
- Business case
- Deployment
- Observability
- Production readiness
- Database auditing
- Execution evidence
- Bugs and fixes

See the corresponding Markdown files in the repository for the detailed engineering and operational documentation.

## Implemented pipeline and honest capability boundaries

The remediation branch adds the following concrete paths:

- **Extraction/OCR:** selectable PDF text, scanned-PDF OCR through PDFium + Tesseract, DOCX paragraphs/tables, plain text and common image OCR. Page count, rendered-pixel count, DOCX archive size/member count, and extracted text are bounded. Tesseract English/French language data are installed in the production image and configurable through GOV_OCR_LANGUAGES.
- **Embeddings and RAG:** configure an OpenAI-compatible embeddings endpoint and chat-completions endpoint using the GOV_EMBEDDING_* and GOV_LLM_* environment variables. Ingestion chunks extracted text, persists embeddings and document version/SHA-256 metadata in PostgreSQL, retrieves only tenant-authorized current-version chunks, and rejects missing or forged citation markers. If a provider is absent, the API reports that grounded generation is unavailable.
- **Vector scale:** similarity ranking currently scans the authorized persisted chunk set in application memory. This provides real vector retrieval for modest corpora, but it is not a high-scale ANN index. Use pgvector/HNSW or OpenSearch k-NN and benchmark before large production corpora.
- **Regulatory sources:** the initial catalog points to official Québec and Canadian legislation sites. Run python -m gov_platform.regulatory_sources seed and then python -m gov_platform.regulatory_sources sync after configuring embeddings. Downloaded source versions remain pending human review. A platform administrator must approve the exact source version and provide a review rationale before it can be retrieved for regulatory assessments.
- **Cases and processing:** tenant-scoped case create/list/detail endpoints and aggregate analytics are persisted in PostgreSQL. POST /v1/documents/{id}/process-async enqueues a durable job; run python -m gov_platform.worker as a separate service. Job status is available from GET /v1/jobs/{id}; failed jobs can be retried by authorized case managers.
- **Risk decisions:** numeric risk scores are intentionally unavailable until a representative expert-labeled dataset and calibrated model are validated. The rule-based checklist and LLM output are decision support only, not legal conclusions or automatic compliance determinations.
- **Frontend dependencies:** Next.js/React are upgraded, the npm lockfile is regenerated in CI, and the remediation workflow runs npm audit. CI also uses npm ci and TypeScript typechecking.

For local setup, copy .env.example to .env, set strong local secrets and provider keys only in the ignored .env file, apply alembic upgrade head, and run the API and document worker. For production identity, regulatory source review, backups/restore drills, independent security assessment and go-live gates, follow docs/PRODUCTION_ACCEPTANCE.md and docs/SECURITY_TEST_PLAN.md.

## Production Readiness Boundary

GoAnalyze is a **technical portfolio and engineering demonstration**. The presence of production-oriented infrastructure does not by itself establish production certification, government approval, customer deployment, security accreditation, or compliance.

A real deployment handling sensitive information requires environment-specific validation, security assessment, privacy review, operational controls, AI evaluation, and acceptance testing.

## Engineering Focus

GoAnalyze demonstrates AI engineering beyond the model layer:

**AI + RAG + Security + Retrieval + Backend + Multi-Tenancy + Infrastructure + Observability + Testing**

## Disclaimer

This project demonstrates enterprise AI architecture and engineering practices. It should not be interpreted as proof of production deployment, regulatory compliance, government certification, or customer adoption.
