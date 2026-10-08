from sqlalchemy import Engine, inspect, text

from app.db import Base


def ensure_database_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    session_columns = {column["name"]: column for column in inspector.get_columns("sessions")}
    event_columns = {column["name"]: column for column in inspector.get_columns("events")}

    with engine.begin() as connection:
        if "external_id" not in session_columns:
            connection.execute(text("ALTER TABLE sessions ADD COLUMN external_id VARCHAR(128)"))
        if not session_columns["src_ip"]["nullable"]:
            connection.execute(text("ALTER TABLE sessions ALTER COLUMN src_ip DROP NOT NULL"))
        if not event_columns["session_id"]["nullable"]:
            connection.execute(text("ALTER TABLE events ALTER COLUMN session_id DROP NOT NULL"))
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_sessions_external_id ON sessions (external_id)")
        )