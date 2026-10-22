from app.repositories.base import BaseRepository
from app.repositories.candidate_claim import CandidateClaimRepository
from app.repositories.candidate_profile import CandidateProfileRepository
from app.repositories.candidate_target import CandidateTargetRepository
from app.repositories.evidence_item import EvidenceItemRepository
from app.repositories.evidence_source import EvidenceSourceRepository
from app.repositories.resume import ResumeRepository
from app.repositories.resume_parse import ResumeParseRepository
from app.repositories.user import UserRepository
from app.repositories.verification_result import VerificationResultRepository

__all__ = [
    "BaseRepository",
    "UserRepository",
    "ResumeRepository",
    "ResumeParseRepository",
    "CandidateProfileRepository",
    "CandidateTargetRepository",
    "CandidateClaimRepository",
    "EvidenceSourceRepository",
    "EvidenceItemRepository",
    "VerificationResultRepository",
]
