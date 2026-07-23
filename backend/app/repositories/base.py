from typing import Any, Generic, Type, TypeVar, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], db: Session):
        """
        Base repository containing common CRUD operations.
        Isolated from service layers.
        """
        self.model = model
        self.db = db

    def get(self, id: Any) -> ModelType | None:
        """Fetch a record by its primary key ID."""
        return self.db.get(self.model, id)

    def get_multi(self, *, skip: int = 0, limit: int = 100) -> Sequence[ModelType]:
        """Fetch multiple records with offset and limit parameters."""
        query = select(self.model).offset(skip).limit(limit)
        return self.db.execute(query).scalars().all()

    def create(self, db_obj: ModelType) -> ModelType:
        """Persist a new entity model to the database."""
        self.db.add(db_obj)
        self.db.commit()
        self.db.refresh(db_obj)
        return db_obj

    def update(self, db_obj: ModelType, update_data: dict[str, Any]) -> ModelType:
        """Update fields of an existing entity."""
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        self.db.add(db_obj)
        self.db.commit()
        self.db.refresh(db_obj)
        return db_obj

    def remove(self, id: Any) -> ModelType | None:
        """Remove a record by primary key."""
        obj = self.db.get(self.model, id)
        if obj:
            self.db.delete(obj)
            self.db.commit()
        return obj
