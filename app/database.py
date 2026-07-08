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