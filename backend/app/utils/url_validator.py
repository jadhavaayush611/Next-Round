import ipaddress
import posixpath
import re
from urllib.parse import urlsplit, urlunsplit

from app.models.evidence_source import EvidenceSourceType

DISALLOWED_SCHEMES = {
    "file",
    "ftp",
    "ftps",
    "javascript",
    "data",
    "git",
    "ssh",
    "gopher",
    "mailto",
}
ALLOWED_SCHEMES = {"http", "https"}
DISALLOWED_HOSTS = {"localhost", "0.0.0.0", "::1"}

DOMAIN_LABEL_REGEX = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


def normalize_and_validate_url(
    raw_url: str, source_type: EvidenceSourceType | None = None
) -> str:
    """
    Validates and normalizes an external source URL without trusting it as proof of identity.
    Performs purely offline, deterministic parsing without network requests.

    Enforces:
    - Supported HTTP/HTTPS schemes only.
    - Rejects embedded credentials (userinfo).
    - Rejects localhost, loopback, private, and reserved IP addresses.
    - Normalizes lowercase scheme and hostname.
    - Strips default ports (80 for http, 443 for https).
    - Resolves redundant slashes and strips trailing slashes on sub-paths.
    - Strips client-side URL fragments.
    - Source-type specific formatting checks for GitHub and LinkedIn.

    Raises:
        ValueError: If the URL is malformed, unsupported, or unsafe.
    """
    if not raw_url or not isinstance(raw_url, str):
        raise ValueError("URL must be a non-empty string.")

    cleaned = raw_url.strip()
    if not cleaned:
        raise ValueError("URL cannot be empty or whitespace only.")

    if len(cleaned) > 2048:
        raise ValueError("URL exceeds maximum length of 2048 characters.")

    # Reject null bytes and control characters
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError("URL contains invalid control characters.")

    try:
        parsed = urlsplit(cleaned)
    except Exception as exc:
        raise ValueError(f"Malformed URL: {exc}") from exc

    scheme = parsed.scheme.lower()
    if not scheme:
        raise ValueError("URL is missing a protocol scheme (must be http or https).")

    if scheme in DISALLOWED_SCHEMES or scheme not in ALLOWED_SCHEMES:
        raise ValueError(
            f"Unsupported scheme '{scheme}'. Only HTTP and HTTPS are permitted."
        )

    # Reject embedded credentials
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise ValueError("URLs with embedded credentials are not permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must contain a valid hostname.")

    hostname = hostname.lower()

    if hostname in DISALLOWED_HOSTS:
        raise ValueError("Localhost and loopback hostnames are not permitted.")

    # Check for private / loopback IP addresses or invalid domain syntax
    try:
        ip = ipaddress.ip_address(hostname)
        is_ip = True
    except ValueError:
        is_ip = False

    if is_ip:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                "Private, loopback, and reserved IP addresses are not permitted."
            )
    else:
        # Not an IP address, validate domain format
        if not DOMAIN_LABEL_REGEX.match(hostname):
            raise ValueError(
                f"Invalid hostname '{hostname}'. Must be a valid domain name."
            )

    # Port handling: omit default ports
    netloc = hostname
    if parsed.port:
        if (scheme == "http" and parsed.port == 80) or (
            scheme == "https" and parsed.port == 443
        ):
            netloc = hostname
        else:
            if not (1 <= parsed.port <= 65535):
                raise ValueError(f"Invalid port number {parsed.port}.")
            netloc = f"{hostname}:{parsed.port}"

    # Path normalization: resolve dot segments and collapse slashes
    raw_path = parsed.path
    if not raw_path or raw_path == "/":
        path = ""
    else:
        norm = posixpath.normpath(raw_path)
        if norm.startswith("/"):
            norm = norm[1:]
        path = f"/{norm}" if norm and norm != "." else ""
        if path.endswith("/"):
            path = path.rstrip("/")

    # Fragment must be stripped
    query = parsed.query

    # Source-type specific validations
    if source_type == EvidenceSourceType.GITHUB_REPOSITORY:
        if hostname in ("www.github.com", "github.com"):
            hostname = "github.com"
            netloc = hostname
        else:
            raise ValueError("GitHub repository source must have a github.com domain.")

        segments = [s for s in path.split("/") if s]
        if len(segments) < 2:
            raise ValueError(
                "GitHub repository URL must include both owner and repository name (e.g., https://github.com/owner/repo)."
            )
        owner = segments[0]
        repo = segments[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not repo:
            raise ValueError("Repository name cannot be empty.")
        path = f"/{owner}/{repo}"

    elif source_type == EvidenceSourceType.GITHUB_PROFILE:
        if hostname in ("www.github.com", "github.com"):
            hostname = "github.com"
            netloc = hostname
        else:
            raise ValueError("GitHub profile source must have a github.com domain.")

        segments = [s for s in path.split("/") if s]
        if len(segments) != 1:
            raise ValueError(
                "GitHub profile URL must be in the format https://github.com/username."
            )
        username = segments[0]
        if username in {
            "features",
            "topics",
            "collections",
            "trending",
            "explore",
            "settings",
        }:
            raise ValueError(
                f"'{username}' is a reserved GitHub system path, not a user profile."
            )
        path = f"/{username}"

    elif source_type == EvidenceSourceType.LINKEDIN_PROFILE:
        if not (hostname == "linkedin.com" or hostname.endswith(".linkedin.com")):
            raise ValueError("LinkedIn profile source must have a linkedin.com domain.")
        segments = [s for s in path.split("/") if s]
        if not segments:
            raise ValueError("LinkedIn profile URL must include a profile path.")

    # Reconstruct normalized URL
    normalized = urlunsplit((scheme, netloc, path, query, ""))
    return normalized
