from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/job_agent"
    DATABASE_URL_SYNC: str = "postgresql://postgres:postgres@localhost:5432/job_agent"

    GROQ_API_KEY: str

    REDIS_URL: str = "redis://localhost:6379/0"

    BROWSERLESS_URL: Optional[str] = None

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    SECRET_KEY: str = "change-this-secret-key"

    HITL_TIMEOUT_SECONDS: int = 30

    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    MAX_CONCURRENT_JOBS: int = 3
    AGENT_HEADLESS: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
