from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///data/app.db"

engine = create_engine(
    DATABASE_URL,
    echo=False
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)

Base = declarative_base()


def init_db():
    from database.models.missionary import Missionary
    from database.models.workflow import WorkflowStage
    from database.models.document import Document

    Base.metadata.create_all(bind=engine)

    _run_migrations()


def _run_migrations():
    migrations = [
        "ALTER TABLE documents ADD COLUMN notes TEXT",
    ]

    with engine.connect() as conn:
        for sql in migrations:
            try:
                from sqlalchemy import text
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass