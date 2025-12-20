"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings
from typing import List, Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Required: Authentication token
    bandscan_api_token: str

    # Base URL for constructing URLs (no trailing slash)
    base_url: str = "http://localhost:8000"

    # Google Sheets settings (for student requests)
    google_service_account_json: Optional[str] = None  # JSON string of service account credentials
    google_service_account_file: Optional[str] = None  # Path to service account credentials file

    # Firebase Cloud Messaging settings (for push notifications)
    fcm_server_key: Optional[str] = None  # FCM server key for Android notifications
    fcm_service_account_json: Optional[str] = None  # Firebase service account JSON string
    fcm_service_account_file: Optional[str] = None  # Path to Firebase service account file

    # Apple Push Notification Service settings
    apns_key_id: Optional[str] = None  # APNs key ID
    apns_team_id: Optional[str] = None  # Apple team ID
    apns_bundle_id: Optional[str] = None  # iOS app bundle ID
    apns_key_file: Optional[str] = None  # Path to APNs .p8 key file
    apns_use_sandbox: bool = True  # Use APNs sandbox environment

    # Maximum upload file size in MB
    max_file_size_mb: int = 10

    # Thumbnail dimension in pixels (square)
    thumbnail_size: int = 300

    # Comma-separated list of allowed file extensions
    allowed_extensions: str = "jpg,jpeg,png,gif,webp"

    # Logging level
    log_level: str = "INFO"

    # Data storage path
    data_path: str = "/data"

    @property
    def allowed_extensions_list(self) -> List[str]:
        """Get allowed extensions as a list."""
        return [ext.strip().lower() for ext in self.allowed_extensions.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        """Get max file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @property
    def images_path(self) -> str:
        """Path for image storage."""
        return f"{self.data_path}/images"

    @property
    def database_path(self) -> str:
        """Path for SQLite database."""
        return f"{self.data_path}/database/bandscan.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
