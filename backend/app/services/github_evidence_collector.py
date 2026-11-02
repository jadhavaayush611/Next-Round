import base64
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.user import User
from app.repositories.evidence_item import EvidenceItemRepository
from app.repositories.evidence_source import EvidenceSourceRepository
from app.schemas.evidence_source import EvidenceCollectionResponse
from app.services.github_client import (
    GitHubClient,
    GitHubClientError,
    GitHubMalformedResponseError,
    GitHubNetworkError,
    GitHubOversizedResponseError,
    GitHubRateLimitError,
    GitHubResourceNotFoundError,
    GitHubSecurityError,
    GitHubServerError,
    extract_github_owner_and_repo,
)


class GitHubEvidenceCollectorService:
    """
    Domain service for orchestrating evidence collection from registered public
    GitHub repositories.

    Domain Invariants & Principles:
    1. Public Repositories Only: Evaluates only public repositories. Private repos
       or unauthorized modes are rejected without collecting private data.
    2. Identity & Path Security: Only queries api.github.com for the owner and repository
       derived strictly from the candidate's normalized EvidenceSource.source_uri.
    3. Idempotent Observations: Avoids duplicating identical current observations on
       repeated runs, while preserving historical items when repository state changes.
    4. Controlled Lifecycle: Successfully collected sources are marked AVAILABLE;
       missing/private sources are marked INACCESSIBLE; communication errors marked ERROR.
    5. Observation Bounding: Metadata and README content are strictly size-bounded
       to fit within EvidenceItem observed_data constraints (64 KB).
    6. Non-Evaluative: Never generates VerificationResult records or asserts proficiency.
    """

    def __init__(self, db: Session, github_client: GitHubClient | None = None):
        self.db = db
        self.source_repo = EvidenceSourceRepository(db)
        self.item_repo = EvidenceItemRepository(db)
        self.client = github_client or GitHubClient()

    def _update_source_status(
        self,
        source: EvidenceSource,
        access_status: EvidenceSourceStatus | None,
        last_checked_at: datetime,
    ) -> None:
        """Safely update and commit source status without raising unhandled errors."""
        try:
            if access_status is not None:
                source.access_status = access_status
            source.last_checked_at = last_checked_at
            self.db.commit()
        except Exception:
            self.db.rollback()

    def collect_repository_evidence(
        self, user: User, source_id: uuid.UUID
    ) -> EvidenceCollectionResponse:
        """
        Collect repository metadata and README documentation for a candidate-owned
        public GitHub repository evidence source.
        """
        source = self.source_repo.get_by_id(source_id)
        if not source or source.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evidence source not found.",
            )

        if source.source_type != EvidenceSourceType.GITHUB_REPOSITORY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Evidence collection is only supported for GITHUB_REPOSITORY sources.",
            )

        if source.access_status == EvidenceSourceStatus.REVOKED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot collect evidence for a revoked evidence source.",
            )

        if source.access_mode != AccessMode.PUBLIC:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only public GitHub repositories are supported for evidence collection.",
            )

        try:
            owner, repo = extract_github_owner_and_repo(source.source_uri)
        except GitHubSecurityError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        now = datetime.now(UTC)

        # 1. Fetch Repository Metadata
        try:
            repo_info = self.client.get_repository(owner, repo)
        except GitHubResourceNotFoundError as exc:
            self._update_source_status(source, EvidenceSourceStatus.INACCESSIBLE, now)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upstream GitHub repository not found or is private.",
            ) from exc
        except GitHubRateLimitError as exc:
            self._update_source_status(source, None, now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="GitHub API rate limit exceeded. Please try again later.",
            ) from exc
        except (GitHubOversizedResponseError, GitHubMalformedResponseError) as exc:
            self._update_source_status(source, EvidenceSourceStatus.ERROR, now)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub API returned an invalid or oversized response.",
            ) from exc
        except GitHubServerError as exc:
            self._update_source_status(source, EvidenceSourceStatus.ERROR, now)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub API returned an upstream server error.",
            ) from exc
        except GitHubNetworkError as exc:
            self._update_source_status(source, EvidenceSourceStatus.ERROR, now)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Connection to GitHub API timed out or failed.",
            ) from exc
        except GitHubClientError as exc:
            self._update_source_status(source, EvidenceSourceStatus.ERROR, now)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub API client error.",
            ) from exc

        # Disallow private repos returned through unexpected channels
        if repo_info.get("private", False):
            self._update_source_status(source, EvidenceSourceStatus.INACCESSIBLE, now)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target GitHub repository is private. Only public repositories are supported.",
            )

        # 2. Fetch README documentation (None if absent/404)
        try:
            readme_info = self.client.get_readme(owner, repo)
        except GitHubRateLimitError as exc:
            self._update_source_status(source, None, now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="GitHub API rate limit exceeded during documentation retrieval.",
            ) from exc
        except (GitHubOversizedResponseError, GitHubMalformedResponseError) as exc:
            self._update_source_status(source, EvidenceSourceStatus.ERROR, now)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub API returned an invalid or oversized response during documentation retrieval.",
            ) from exc
        except GitHubServerError as exc:
            self._update_source_status(source, EvidenceSourceStatus.ERROR, now)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub API returned an upstream server error during documentation retrieval.",
            ) from exc
        except GitHubNetworkError as exc:
            self._update_source_status(source, EvidenceSourceStatus.ERROR, now)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Connection to GitHub API timed out or failed during documentation retrieval.",
            ) from exc
        except GitHubClientError as exc:
            self._update_source_status(source, EvidenceSourceStatus.ERROR, now)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub API client error during documentation retrieval.",
            ) from exc

        # 3. Construct minimal structured observations
        license_data = repo_info.get("license")
        license_dict = license_data if isinstance(license_data, dict) else None

        observed_metadata: dict[str, Any] = {
            "full_name": repo_info.get("full_name") or f"{owner}/{repo}",
            "description": repo_info.get("description"),
            "primary_language": repo_info.get("language"),
            "topics": repo_info.get("topics") or [],
            "default_branch": repo_info.get("default_branch") or "main",
            "created_at": repo_info.get("created_at"),
            "updated_at": repo_info.get("updated_at"),
            "pushed_at": repo_info.get("pushed_at"),
            "license_spdx_id": license_dict.get("spdx_id") if license_dict else None,
            "license_name": license_dict.get("name") if license_dict else None,
            "is_fork": repo_info.get("fork", False),
            "is_archived": repo_info.get("archived", False),
            "size_kb": repo_info.get("size", 0),
        }

        observed_readme: dict[str, Any] | None = None
        readme_path = "README.md"
        if readme_info:
            readme_name = str(readme_info.get("name") or "README.md")
            readme_path = str(readme_info.get("path") or "README.md")
            readme_sha = str(readme_info.get("sha") or "")
            readme_size = int(readme_info.get("size") or 0)
            raw_b64 = (
                str(readme_info.get("content") or "")
                .replace("\n", "")
                .replace("\r", "")
            )
            encoding = str(readme_info.get("encoding") or "").lower()

            if encoding == "base64" and raw_b64:
                try:
                    decoded_bytes = base64.b64decode(raw_b64, validate=False)
                    decoded_text = decoded_bytes.decode("utf-8", errors="replace")
                except Exception:
                    decoded_text = ""
            else:
                decoded_text = ""

            max_chars = settings.GITHUB_MAX_README_BYTES
            is_truncated = len(decoded_text) > max_chars
            content_extracted = (
                decoded_text[:max_chars] if is_truncated else decoded_text
            )

            observed_readme = {
                "name": readme_name,
                "path": readme_path,
                "sha": readme_sha,
                "size_bytes": readme_size,
                "content": content_extracted,
                "truncated": is_truncated,
                "content_type": "text/markdown",
            }

        # 4. Check idempotency against existing EvidenceItems for this source
        items_collected = 0
        items_retained = 0
        item_ids: list[uuid.UUID] = []

        def _is_metadata_unchanged(
            old_data: dict[str, Any] | None, new_data: dict[str, Any]
        ) -> bool:
            if not old_data:
                return False
            keys = (
                "full_name",
                "description",
                "primary_language",
                "topics",
                "default_branch",
                "pushed_at",
                "license_spdx_id",
            )
            return all(old_data.get(k) == new_data.get(k) for k in keys)

        try:
            # Re-fetch/lock source record to serialize concurrent collection on the same source
            locked_source = self.db.execute(
                select(EvidenceSource)
                .where(EvidenceSource.id == source.id)
                .with_for_update()
            ).scalar_one_or_none()
            target_source = locked_source or source

            existing_items = self.item_repo.list_by_source(target_source.id)
            existing_meta = next(
                (
                    i
                    for i in existing_items
                    if i.evidence_type == EvidenceType.REPOSITORY_METADATA
                    and i.source_locator == "repository_metadata"
                ),
                None,
            )
            existing_doc = next(
                (
                    i
                    for i in existing_items
                    if i.evidence_type == EvidenceType.DOCUMENTATION
                    and i.source_locator == readme_path
                ),
                None,
            )

            # Handle Metadata observation
            if existing_meta and _is_metadata_unchanged(
                existing_meta.observed_data, observed_metadata
            ):
                items_retained += 1
                item_ids.append(existing_meta.id)
            else:
                meta_item = EvidenceItem(
                    evidence_source_id=target_source.id,
                    evidence_type=EvidenceType.REPOSITORY_METADATA,
                    description=f"Repository metadata for {owner}/{repo}",
                    observed_data=observed_metadata,
                    source_locator="repository_metadata",
                    observed_at=now,
                )
                self.db.add(meta_item)
                self.db.flush()
                items_collected += 1
                item_ids.append(meta_item.id)

            # Handle README observation
            if observed_readme:
                new_sha = observed_readme.get("sha")
                old_sha = (
                    (existing_doc.observed_data or {}).get("sha")
                    if existing_doc
                    else None
                )
                if existing_doc and new_sha and old_sha == new_sha:
                    items_retained += 1
                    item_ids.append(existing_doc.id)
                else:
                    doc_item = EvidenceItem(
                        evidence_source_id=target_source.id,
                        evidence_type=EvidenceType.DOCUMENTATION,
                        description=f"README documentation ({readme_path}) for {owner}/{repo}",
                        observed_data=observed_readme,
                        source_locator=readme_path,
                        observed_at=now,
                    )
                    self.db.add(doc_item)
                    self.db.flush()
                    items_collected += 1
                    item_ids.append(doc_item.id)

            # Update EvidenceSource status and last_checked_at
            target_source.access_status = EvidenceSourceStatus.AVAILABLE
            target_source.last_checked_at = now
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to persist evidence collection observations.",
            ) from exc

        total_items = self.item_repo.count_by_source(target_source.id)
        readme_msg = f" and {readme_path}" if observed_readme else " (no README found)"

        return EvidenceCollectionResponse(
            evidence_source_id=target_source.id,
            source_uri=target_source.source_uri,
            access_status=target_source.access_status,
            items_collected=items_collected,
            items_retained=items_retained,
            total_items=total_items,
            collected_at=now,
            message=(
                f"Successfully collected evidence from {owner}/{repo}{readme_msg}. "
                f"New observations: {items_collected}, retained: {items_retained}."
            ),
            item_ids=item_ids,
        )
