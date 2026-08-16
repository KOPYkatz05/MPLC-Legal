from database.migrations.migration_001_baseline import MIGRATION as MIGRATION_001
from database.migrations.migration_002_release_tracking import MIGRATION as MIGRATION_002
from database.migrations.migration_003_dni_tracking import MIGRATION as MIGRATION_003
from database.migrations.migration_004_upload_reliability import MIGRATION as MIGRATION_004
from database.migrations.migration_005_last_entry_date import MIGRATION as MIGRATION_005


MIGRATIONS = (
    MIGRATION_001,
    MIGRATION_002,
    MIGRATION_003,
    MIGRATION_004,
    MIGRATION_005,
)
