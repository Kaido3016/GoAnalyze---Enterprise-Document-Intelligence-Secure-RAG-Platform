from functools import lru_cache

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_AUDIT_SECRET = "change-me-through-secrets-manager"  # nosec B105 - sentinel value that _validate_production_secrets() rejects, not a credential in use


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GOV_", extra="ignore")

    service_name: str = "goanalyze-government-platform"
    environment: str = "development"

    # -- data plane -----------------------------------------------------
    database_url: str = "postgresql+asyncpg://goanalyze:goanalyze@postgres:5432/goanalyze"
    # SQLAlchemy's own defaults (pool_size=5, max_overflow=10 -> 15 total
    # connections per process) are too small to leave silently unconfigured
    # for a production deployment, especially with multiple uvicorn worker
    # processes each holding their own pool. Exposed here so it's tunable
    # via environment variable without a code change.
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30
    redis_url: str = "redis://redis:6379/0"
    opensearch_url: str = "http://opensearch:9200"
    opensearch_index: str = "goanalyze-documents"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "goanalyze-documents"
    minio_secure: bool = False
    # Volatile storage is an explicit local-development/test opt-in only.
    # Production must never acknowledge writes that disappear on process restart.
    allow_in_memory_storage_fallback: bool = False
    kafka_bootstrap_servers: str = "kafka:9092"
    temporal_target_host: str = "temporal:7233"

    # -- rate limiting (Redis-backed) --------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_per_ip_per_minute: int = 120
    rate_limit_per_user_per_minute: int = 300
    rate_limit_per_tenant_per_minute: int = 1000

    # -- identity / auth --------------------------------------------------
    keycloak_issuer: AnyHttpUrl | str = "http://keycloak:8080/realms/goanalyze"
    keycloak_audience: str = "goanalyze-api"
    # Overrides the derived "<issuer>/protocol/openid-connect/certs" JWKS URL
    # if the identity provider uses a non-standard discovery layout.
    keycloak_jwks_url: str | None = None
    # Header-based (x-tenant-id/x-roles) auth bypass for local development
    # only. Must be explicitly enabled; defaults to disabled everywhere,
    # including "development", so it cannot be turned on by accident.
    allow_insecure_dev_auth: bool = False

    # Explicit opt-out for tracing (rather than only inferring from
    # environment). Test suites in particular should disable this: pytest's
    # stdout capture/teardown otherwise races with OpenTelemetry's
    # background export thread when the console exporter is active.
    otel_tracing_enabled: bool = True

    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # -- secrets ----------------------------------------------------------
    # No safe default is provided in code. Must be injected via the
    # GOV_AUDIT_HASH_SECRET environment variable (or a secrets manager that
    # populates it), and the app refuses to start in production without it.
    audit_hash_secret: str = _INSECURE_DEFAULT_AUDIT_SECRET

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        if self.environment == "production":
            if self.audit_hash_secret == _INSECURE_DEFAULT_AUDIT_SECRET or not self.audit_hash_secret.strip():
                raise ValueError(
                    "GOV_AUDIT_HASH_SECRET must be set to a strong, unique value in production "
                    "(inject it via the environment or a secrets manager, never commit it to source)."
                )
            if self.allow_insecure_dev_auth:
                raise ValueError(
                    "GOV_ALLOW_INSECURE_DEV_AUTH must not be enabled in production."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
