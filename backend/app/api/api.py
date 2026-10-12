from fastapi import APIRouter

from app.api.endpoints import (
    auth,
    candidate_claims,
    candidate_profiles,
    candidate_targets,
    evidence_sources,
    resumes,
    users,
)

api_router = APIRouter()

# Include endpoint sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(resumes.router, prefix="/resumes", tags=["resumes"])

# Candidate Intelligence Vertical Slice
api_router.include_router(
    candidate_profiles.router, prefix="/candidate-profile", tags=["candidate-profile"]
)
api_router.include_router(
    candidate_profiles.router,
    prefix="/candidate-profiles",
    tags=["candidate-profile"],
    include_in_schema=False,
)
api_router.include_router(
    candidate_targets.router, prefix="/candidate-targets", tags=["candidate-targets"]
)
api_router.include_router(
    candidate_targets.router,
    prefix="/candidate-profile/targets",
    tags=["candidate-targets"],
    include_in_schema=False,
)
api_router.include_router(
    candidate_claims.router, prefix="/candidate-claims", tags=["candidate-claims"]
)
api_router.include_router(
    candidate_claims.router,
    prefix="/candidate-profile/claims",
    tags=["candidate-claims"],
    include_in_schema=False,
)

# Evidence Source Foundation
api_router.include_router(
    evidence_sources.router, prefix="/evidence-sources", tags=["evidence-sources"]
)
