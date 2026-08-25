from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pydantic_settings import BaseSettings, SettingsConfigDict


# Placeholder values that must never reach production. Startup refuses to
# continue when secrets are missing or left at these known-bad values.
_KNOWN_BAD_SECRETS = {
    "your-secret-api-key-here-change-in-production",
    "change-this-to-a-long-random-secret",
    "change-me",
    "secret",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str
    SECRET_KEY: str = ""   # JWT signing key — REQUIRED, see validate_security_settings()
    API_KEY: str = ""      # shared gateway/dashboard ingestion key — REQUIRED
    SMMS_BASE_URL: str = "https://smms.indianrailways.gov.in/api"
    SMMS_API_KEY: str = ""  # optional: only needed when SMMS integration is enabled
    VENDOR_CODE: str = "XYZ"
    VENDOR_NAME: str = "XYZ Signalling Ltd"

    # Redis config settings loaded from .env
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # ── mTLS (Annexure B §6) ──────────────────────────────────────────────
    # TLS itself is terminated by the reverse proxy (nginx/Traefik/etc), not
    # by this app — by the time a request reaches FastAPI, the TLS handshake
    # is already done. What this app CAN do is verify the proxy actually
    # performed client-certificate verification before forwarding the
    # request, via the standard headers nginx sets after a successful mTLS
    # handshake. See deployment/nginx-mtls.conf.example for the proxy config
    # that populates these headers.
    #
    # Defaults to False so this doesn't break existing dev/staging
    # deployments that don't have mTLS terminated yet — set True in
    # production once the reverse proxy is configured for client-cert auth.
    REQUIRE_MTLS: bool = False
    MTLS_VERIFY_HEADER: str = "X-SSL-Client-Verify"   # nginx sets this to "SUCCESS" on a valid client cert
    MTLS_CN_HEADER: str = "X-SSL-Client-CN"            # nginx sets this to the certificate's Common Name

    @property
    def database_url(self) -> str:
        # Fix postgres:// -> postgresql:// for SQLAlchemy
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if "render.com" in url and "sslmode=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}sslmode=require"
        return url


settings = Settings()


def validate_security_settings() -> None:
    """Fail fast at startup when secrets are missing or left at known-bad
    placeholder values. Raises RuntimeError listing every offender so the
    operator sees all problems in one boot, not one per restart.
    """
    errors: list[str] = []
    warnings: list[str] = []

    secret = (settings.SECRET_KEY or "").strip()
    if not secret:
        errors.append("SECRET_KEY is not set (required for JWT signing)")
    elif secret.lower() in _KNOWN_BAD_SECRETS:
        errors.append("SECRET_KEY is still the documented placeholder value")
    elif len(secret) < 32:
        errors.append("SECRET_KEY is too short — use >= 32 random characters")

    api_key = (settings.API_KEY or "").strip()
    if not api_key:
        errors.append("API_KEY is not set (required for gateway ingestion auth)")
    elif api_key.lower() in _KNOWN_BAD_SECRETS:
        errors.append("API_KEY is still the documented placeholder value")

    smms_key = (settings.SMMS_API_KEY or "").strip()
    if not smms_key or smms_key.lower() in _KNOWN_BAD_SECRETS:
        warnings.append(
            "SMMS_API_KEY is unset/placeholder — SMMS integration endpoints will reject requests"
        )

    for w in warnings:
        print(f"WARNING: {w}")

    if errors:
        raise RuntimeError(
            "Refusing to start due to insecure configuration:\n  - " + "\n  - ".join(errors)
        )



engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=20,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()