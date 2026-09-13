from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_alembic_migrations_upgrade_and_downgrade(tmp_path: Path) -> None:
    """Verifies that Alembic migration 003_create_resume_parses_table upgrades and downgrades cleanly."""
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "migrations"))

    test_db = tmp_path / "migration_test.db"
    sqlite_url = f"sqlite:///{test_db.as_posix()}"

    # Setup base database schema with initial users table prior to migration 001
    engine = create_engine(sqlite_url)
    with engine.connect() as conn:
        conn.execute(text("""
                CREATE TABLE users (
                    id CHAR(32) PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    hashed_password VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                );
                """))
        conn.commit()

    with patch("app.config.settings.Settings.sqlalchemy_database_url", sqlite_url):
        # 1. Upgrade to latest migration (head) -> runs 001, 002, 003
        command.upgrade(alembic_cfg, "head")

        # 2. Downgrade 003 to 002
        command.downgrade(alembic_cfg, "002_create_resumes_table")

        # 3. Upgrade back to head to verify idempotent re-application of 003
        command.upgrade(alembic_cfg, "head")
