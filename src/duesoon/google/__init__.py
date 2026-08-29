"""Read-only Google Workspace adapters."""

from .client import GoogleAPIError, GoogleWorkspaceClient
from .config import GoogleWorkspaceConfig
from .evidence import GoogleEvidenceService

__all__ = [
    "GoogleAPIError",
    "GoogleEvidenceService",
    "GoogleWorkspaceClient",
    "GoogleWorkspaceConfig",
]
