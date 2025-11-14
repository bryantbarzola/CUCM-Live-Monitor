"""Configuration management for CUCM Live Monitor."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # CUCM Connection
    cucm_host: str = Field(..., env="CUCM_HOST")
    cucm_username: str = Field(..., env="CUCM_USERNAME")
    cucm_password: str = Field(..., env="CUCM_PASSWORD")
    cucm_version: str = Field(default="14.0", env="CUCM_VERSION")

    # Application Settings
    poll_interval: int = Field(default=5, env="POLL_INTERVAL")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
