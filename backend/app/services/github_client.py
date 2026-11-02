import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.config.settings import settings

GITHUB_OWNER_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")
GITHUB_REPO_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{1,100}$")


class GitHubClientError(Exception):
    """Base exception for all GitHub client operations."""


class GitHubResourceNotFoundError(GitHubClientError):
    """Target GitHub repository or endpoint was not found or is private."""


class GitHubRateLimitError(GitHubClientError):
    """GitHub API rate limit was exceeded or access forbidden."""


class GitHubServerError(GitHubClientError):
    """GitHub API server returned 5xx status."""


class GitHubNetworkError(GitHubClientError):
    """Network failure or timeout communicating with GitHub API."""


class GitHubOversizedResponseError(GitHubClientError):
    """GitHub API response payload exceeded bounded size limits."""


class GitHubMalformedResponseError(GitHubClientError):
    """GitHub API returned an unparseable or unexpected response body."""


class GitHubSecurityError(GitHubClientError):
    """Security invariant violated (e.g. host deviation, unsafe redirect, injection)."""


def extract_github_owner_and_repo(source_uri: str) -> tuple[str, str]:
    """
    Extract (owner, repo) from a normalized GitHub repository URI.
    Enforces strict GitHub naming rules and forbids path traversal.

    Raises:
        GitHubSecurityError: If the URI contains invalid hosts, path segments,
                             or traversal sequences.
    """
    if not source_uri or not isinstance(source_uri, str):
        raise GitHubSecurityError("Source URI must be a non-empty string.")

    try:
        parsed = urlsplit(source_uri.strip())
    except Exception as exc:
        raise GitHubSecurityError(f"Malformed source URI: {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        raise GitHubSecurityError(
            f"Invalid scheme '{scheme}'. Only HTTPS is permitted for GitHub repositories."
        )

    hostname = (parsed.hostname or "").lower()
    if hostname not in ("github.com", "www.github.com"):
        raise GitHubSecurityError(
            f"Invalid GitHub host '{hostname}'. Only official github.com is supported."
        )

    if parsed.query or parsed.fragment:
        raise GitHubSecurityError(
            "Query parameters and fragment identifiers are not permitted in GitHub repository URI."
        )

    segments = [s for s in parsed.path.strip("/").split("/") if s]
    if len(segments) != 2:
        raise GitHubSecurityError(
            "GitHub repository URI must be in the format https://github.com/owner/repo."
        )

    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    if owner in (".", "..") or repo in (".", ".."):
        raise GitHubSecurityError("Path traversal sequences are not permitted.")

    if not GITHUB_OWNER_REGEX.match(owner):
        raise GitHubSecurityError(f"Invalid GitHub owner name '{owner}'.")

    if not GITHUB_REPO_REGEX.match(repo):
        raise GitHubSecurityError(f"Invalid GitHub repository name '{repo}'.")

    return owner, repo


class GitHubClient:
    """
    Dedicated HTTP client for retrieving public repository metadata and documentation
    from the official GitHub REST API.

    Enforces:
    - Strictly official GitHub host or configured base URL.
    - Explicit connection, read, and pool timeouts.
    - Bounded response bodies to prevent denial of service.
    - Safe redirect policy (disallows cross-host redirects).
    - Predictable error mapping without leaking internal credentials.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        api_token: str | None = None,
        max_response_bytes: int | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = (base_url or settings.GITHUB_API_BASE_URL).rstrip("/")
        self.timeout = (
            timeout if timeout is not None else settings.GITHUB_REQUEST_TIMEOUT_SECONDS
        )
        self.api_token = api_token or settings.GITHUB_API_TOKEN
        self.max_response_bytes = (
            max_response_bytes
            if max_response_bytes is not None
            else settings.GITHUB_MAX_RESPONSE_BYTES
        )
        self._custom_client = http_client

    def _build_headers(self) -> dict[str, str]:
        """Build standard GitHub API request headers."""
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "NextRound-Evidence-Collector/1.0",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _send_request(self, endpoint: str) -> dict[str, Any]:
        """
        Execute an HTTP GET request to the GitHub API with bounded response sizes,
        explicit timeouts, and safe redirect validation.
        """
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"

        url = f"{self.base_url}{endpoint}"

        # Host and HTTPS security check
        parsed_base = urlsplit(self.base_url)
        parsed_url = urlsplit(url)
        if (
            parsed_url.netloc != parsed_base.netloc
            or parsed_url.scheme != "https"
            or parsed_base.scheme != "https"
        ):
            raise GitHubSecurityError(
                "Request URL must use HTTPS and match configured GitHub API base URL."
            )

        client = self._custom_client or httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=5.0),
            follow_redirects=False,
        )
        should_close = self._custom_client is None

        try:
            req = client.build_request("GET", url, headers=self._build_headers())
            res = client.send(req, stream=True)
            try:
                # Handle safe single redirect
                if res.is_redirect:
                    redirect_url = res.headers.get("Location")
                    if not redirect_url:
                        raise GitHubMalformedResponseError(
                            "Redirect response missing Location header."
                        )
                    full_redirect_url = urljoin(url, redirect_url)
                    parsed_redir = urlsplit(full_redirect_url)
                    if (
                        parsed_redir.netloc != parsed_base.netloc
                        or parsed_redir.scheme != "https"
                    ):
                        raise GitHubSecurityError(
                            f"Redirect to unauthorized host or non-HTTPS '{full_redirect_url}' is prohibited."
                        )
                    redir_req = client.build_request(
                        "GET", full_redirect_url, headers=self._build_headers()
                    )
                    res.close()
                    res = client.send(redir_req, stream=True)
                    if res.is_redirect:
                        raise GitHubSecurityError(
                            "Multiple redirects are not permitted."
                        )

                if res.status_code == 404:
                    raise GitHubResourceNotFoundError(
                        f"GitHub resource at {endpoint} was not found."
                    )
                if res.status_code in (403, 429):
                    raise GitHubRateLimitError(
                        f"GitHub API rate limit exceeded or access forbidden (status {res.status_code})."
                    )
                if res.status_code >= 500:
                    raise GitHubServerError(
                        f"GitHub API returned upstream server error (status {res.status_code})."
                    )
                if res.status_code >= 400:
                    raise GitHubClientError(
                        f"GitHub API returned client error (status {res.status_code})."
                    )

                # Bounded body reading
                content_length = res.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > self.max_response_bytes:
                            raise GitHubOversizedResponseError(
                                f"Response Content-Length ({content_length} bytes) exceeds maximum "
                                f"allowed size ({self.max_response_bytes} bytes)."
                            )
                    except ValueError:
                        pass

                body_chunks: list[bytes] = []
                total_bytes = 0
                for chunk in res.iter_bytes(chunk_size=8192):
                    total_bytes += len(chunk)
                    if total_bytes > self.max_response_bytes:
                        raise GitHubOversizedResponseError(
                            f"Response body exceeded maximum allowed limit of {self.max_response_bytes} bytes."
                        )
                    body_chunks.append(chunk)

                raw_bytes = b"".join(body_chunks)
                try:
                    data = json.loads(raw_bytes.decode("utf-8"))
                except Exception as exc:
                    raise GitHubMalformedResponseError(
                        f"Malformed JSON response from GitHub API: {exc}"
                    ) from exc

                if not isinstance(data, dict):
                    raise GitHubMalformedResponseError(
                        "Expected JSON object in GitHub API response."
                    )
                return data
            finally:
                res.close()
        except (
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
        ) as exc:
            raise GitHubNetworkError(f"GitHub API connection timed out: {exc}") from exc
        except httpx.NetworkError as exc:
            raise GitHubNetworkError(
                f"Network error communicating with GitHub API: {exc}"
            ) from exc
        finally:
            if should_close:
                client.close()

    def get_repository(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch repository metadata for the given owner and repo."""
        return self._send_request(f"/repos/{owner}/{repo}")

    def get_readme(self, owner: str, repo: str) -> dict[str, Any] | None:
        """
        Fetch README metadata and content for the given owner and repo.
        Returns None if no README documentation exists in the repository.
        """
        try:
            return self._send_request(f"/repos/{owner}/{repo}/readme")
        except GitHubResourceNotFoundError:
            return None
