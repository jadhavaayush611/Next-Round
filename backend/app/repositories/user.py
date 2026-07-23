from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: Session):
        super().__init__(User, db)

    def get_by_email(self, email: str) -> User | None:
        """Fetch a single user from the database matching the provided email."""
        query = select(self.model).where(self.model.email == email)
        return self.db.execute(query).scalar_one_or_none()
