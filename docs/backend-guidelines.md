# Backend Contribution Guidelines

NextRound's backend is powered by FastAPI, Python 3.12, and SQLAlchemy 2.0. Follow these guidelines to keep code architectures unified.

---

## 1. Application Layer Separation

We implement a strict layer separation to prevent coupling business rules to specific frameworks or databases:

```
[Client Request]
       │
       ▼
 1. API Route (fastapi.APIRouter) -> Validates schema input (Pydantic)
       │
       ▼
 2. Dependency Injection -> Injects database session & current authenticated user
       │
       ▼
 3. Service Layer (UserService, etc.) -> Implements business logic (e.g. hashing, evaluations)
       │
       ▼
 4. Repository Layer (UserRepository, etc.) -> Handles DB transactions (SQLAlchemy)
       │
       ▼
 [Database]
```

---

## 2. Recipe for Adding a Feature

To introduce a new domain entity (e.g. `Resume`):

### Step 1: Create the SQLAlchemy Model
Declare the table structure in `app/models/resume.py`. Use SQLAlchemy 2.0 type mapping notation:
```python
import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base

class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    file_path: Mapped[str] = mapped_column(String(512))
```
*Always register the new model class in `app/models/__init__.py`.*

### Step 2: Define Validation Schemas
Define inputs and outputs in `app/schemas/resume.py`:
```python
from pydantic import BaseModel, ConfigDict
import uuid

class ResumeBase(BaseModel):
    file_name: str

class ResumeCreate(ResumeBase):
    file_path: str

class ResumeResponse(ResumeBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
```

### Step 3: Write the Repository
Define database interactions in `app/repositories/resume.py`:
```python
from app.repositories.base import BaseRepository
from app.models.resume import Resume
from sqlalchemy.orm import Session

class ResumeRepository(BaseRepository[Resume]):
    def __init__(self, db: Session):
        super().__init__(Resume, db)

    def get_by_user_id(self, user_id: str) -> list[Resume]:
        # Custom DB query here
        return self.db.query(self.model).filter(self.model.user_id == user_id).all()
```

### Step 4: Write the Service
Define business workflows in `app/services/resume.py`:
```python
from sqlalchemy.orm import Session
from app.repositories.resume import ResumeRepository
from app.schemas.resume import ResumeCreate

class ResumeService:
    def __init__(self, db: Session):
        self.resume_repo = ResumeRepository(db)

    def save_parsed_resume(self, user_id: str, resume_in: ResumeCreate):
        # Business logic goes here
        pass
```

### Step 5: Implement the API Router
Map the service to an endpoint path in `app/api/endpoints/resumes.py`:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User

router = APIRouter()

@router.post("/", response_model=ResumeResponse)
def upload_resume(
    resume_in: ResumeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Route execution
    pass
```
*Register the router inside `app/api/api.py`.*

---

## 3. Database Migrations (Alembic)

1. Make sure your model class is imported in `app/models/__init__.py`.
2. Generate an auto-migration script:
   ```bash
   docker compose exec backend alembic revision --autogenerate -m "create resumes table"
   ```
3. Inspect the created script in `migrations/versions/` for accuracy.
4. Apply the migration:
   ```bash
   docker compose exec backend alembic upgrade head
   ```

---

## 4. Testing Guidelines

Write unit tests under `tests/`. Use the testing fixtures provided by [conftest.py](file:///D:/NextRound/backend/tests/conftest.py):
* Use `db` fixture for direct database transactions.
* Use `client` fixture for calling API routes.
* Example:
  ```python
  def test_get_current_profile(client, token_headers):
      res = client.get("/api/v1/users/me", headers=token_headers)
      assert res.status_code == 200
  ```
