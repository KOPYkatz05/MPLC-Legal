from sqlalchemy import text

from version import SCHEMA_VERSION


def record_schema_version(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_metadata ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO app_metadata (key, value) VALUES "
                "('schema_version', :version) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            ),
            {"version": str(SCHEMA_VERSION)},
        )


def get_schema_version(engine):
    try:
        with engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT value FROM app_metadata "
                    "WHERE key = 'schema_version'"
                )
            ).scalar_one_or_none()
        return int(value) if value is not None else 0
    except Exception:
        return 0
