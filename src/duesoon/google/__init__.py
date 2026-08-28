"""Read-only Google Workspace adapters."""

from .client import GoogleAPIError, GoogleWorkspaceClient
from .config import GoogleWorkspaceConfig

__all__ = ["GoogleAPIError", "GoogleWorkspaceClient", "GoogleWorkspaceConfig"]
