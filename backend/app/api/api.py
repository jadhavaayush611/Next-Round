from fastapi import APIRouter

from app.api.endpoints import auth, resumes, users

api_router = APIRouter()

# Include endpoint sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(resumes.router, prefix="/resumes", tags=["resumes"])
