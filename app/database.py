from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str
    API_KEY: str = "your-secret-api-key-here-change-in-production"
    SMMS_BASE_URL: str = "https://smms.indianrailways.gov.in/api"
    SMMS_API_KEY: str = "your-secret-api-key-here-change-in-production"
    VENDOR_CODE: str = "XYZ"
    VENDOR_NAME: str = "XYZ Signalling Ltd"

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
        return url


settings = Settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()