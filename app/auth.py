"""Authentication middleware for API requests."""

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import get_settings

settings = get_settings()

# HTTP Bearer scheme for token authentication
security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """
    Verify the bearer token matches the configured API token.

    Args:
        credentials: The HTTP authorization credentials

    Returns:
        The verified token

    Raises:
        HTTPException: If token is invalid
    """
    if credentials.credentials != settings.bandscan_api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
