from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_alembic_migrations_upgrade_and_downgrade(tmp_path: Path) -> None:
    """Verifies that Alembic migrations up to 009_create_candidate_skills_tables upgrade and downgrade cleanly."""
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
        # 1. Upgrade to latest migration (head) -> runs 001 through 010
        command.upgrade(alembic_cfg, "head")

        # 2. Downgrade 010 to 009
        command.downgrade(alembic_cfg, "009_create_candidate_skills_tables")

        # 3. Upgrade back to head to verify re-application of 010
        command.upgrade(alembic_cfg, "head")

        # 4. Downgrade 010 and 009 to 008
        command.downgrade(alembic_cfg, "008_create_skills_table")

        # 5. Upgrade back to head to verify re-application of 009 and 010
        command.upgrade(alembic_cfg, "head")

        # 4. Downgrade 009 and 008 to 007
        command.downgrade(alembic_cfg, "007_create_verification_results_table")

        # 5. Upgrade back to head to verify re-application of 008 and 009
        command.upgrade(alembic_cfg, "head")

        # 6. Downgrade to 006
        command.downgrade(alembic_cfg, "006_create_evidence_items_table")

        # 7. Upgrade back to head
        command.upgrade(alembic_cfg, "head")

        # 8. Downgrade to 005
        command.downgrade(alembic_cfg, "005_create_evidence_sources_table")

        # 9. Upgrade back to head
        command.upgrade(alembic_cfg, "head")

        # 10. Downgrade to 004
        command.downgrade(alembic_cfg, "004_create_candidate_profile_target_and_claims")

        # 11. Upgrade back to head
        command.upgrade(alembic_cfg, "head")

        # 12. Downgrade down to 003
        command.downgrade(alembic_cfg, "003_create_resume_parses_table")

        # 13. Upgrade back to head
        command.upgrade(alembic_cfg, "head")

        # 14. Downgrade down to 002
        command.downgrade(alembic_cfg, "002_create_resumes_table")

        # 15. Upgrade back to head to verify idempotent full chain upgrade
        command.upgrade(alembic_cfg, "head")
