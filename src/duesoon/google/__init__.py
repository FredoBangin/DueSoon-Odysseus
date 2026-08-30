"""Read-only Google Workspace adapters."""

from .client import GoogleAPIError, GoogleWorkspaceClient
from .config import GoogleWorkspaceConfig
from .evidence import GoogleEvidenceService
from .availability import GoogleCalendarEvidenceService
from .sync import GoogleWorkspaceSyncService

__all__ = [
    "GoogleAPIError",
    "GoogleEvidenceService",
    "GoogleCalendarEvidenceService",
    "GoogleWorkspaceSyncService",
    "GoogleWorkspaceClient",
    "GoogleWorkspaceConfig",
]
