---
name: DB migrations
description: How schema migrations work in this SQLite project
---

SQLAlchemy `create_all()` only creates NEW tables — it never adds columns to existing tables.

**Migration approach:** `_run_migrations()` in `database/db.py` runs after `create_all()` with a list of raw SQL statements (try/except to silently handle "column already exists").

**If a migration doesn't apply (existing DB):** Run directly via Python:
```python
from sqlalchemy import create_engine, text
engine = create_engine("sqlite:///data/app.db")
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE documents ADD COLUMN notes TEXT"))
    conn.commit()
```

**Why:** SQLite's ALTER TABLE does not support IF NOT EXISTS, so try/except is the portable workaround.

**How to apply:** Add the SQL string to the `migrations` list in `_run_migrations()`. It will run on every startup but fail silently once the column exists.
