from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config.settings import settings

# Create engine with connection pooling parameters for production
engine = create_engine(
    settings.sqlalchemy_database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# SQLAlchemy 2.0 Declarative base
class Base(DeclarativeBase):
    pass


def get_db() -> Generator:
    """Dependency injection yield generator for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
