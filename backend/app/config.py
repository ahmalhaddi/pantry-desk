from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://pantry:pantry@localhost:5432/pantry"
    jwt_secret: str = "dev-only-change-me"
    capacity_fresh_hours: int = 48

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")


settings = Settings()
