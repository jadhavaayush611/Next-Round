from app.repositories.base import BaseRepository
from app.repositories.candidate_claim import CandidateClaimRepository
from app.repositories.candidate_profile import CandidateProfileRepository
from app.repositories.candidate_target import CandidateTargetRepository
from app.repositories.resume import ResumeRepository
from app.repositories.resume_parse import ResumeParseRepository
from app.repositories.user import UserRepository

__all__ = [
    "BaseRepository",
    "UserRepository",
    "ResumeRepository",
    "ResumeParseRepository",
    "CandidateProfileRepository",
    "CandidateTargetRepository",
    "CandidateClaimRepository",
]
