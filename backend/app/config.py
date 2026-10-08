from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Adaptive Honeypot API"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://honeypot:change_me@db:5432/honeypot"
    session_root: str = "/tmp/honeypot_sessions"
    log_dir: str = "/var/log/honeypot"
    evidence_dir: str = "/var/log/honeypot/evidence"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
