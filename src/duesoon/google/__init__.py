"""Read-only Google Workspace adapters."""

from .client import GoogleAPIError, GoogleWorkspaceClient
from .config import GoogleWorkspaceConfig
from .evidence import GoogleEvidenceService
from .availability import GoogleCalendarEvidenceService

__all__ = [
    "GoogleAPIError",
    "GoogleEvidenceService",
    "GoogleCalendarEvidenceService",
    "GoogleWorkspaceClient",
    "GoogleWorkspaceConfig",
]
