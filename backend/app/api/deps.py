from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.container import Container, container
from app.core.security import TokenError, decode_access_token
from app.models.domain import Claim, User

bearer = HTTPBearer(auto_error=False)


def get_container() -> Container:
    return container


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    access_token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> User:
    """Authenticate via Bearer header, or ?access_token= for <img>/EventSource requests."""
    token = credentials.credentials if credentials else access_token
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        user_id = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please sign in again") from exc
    user = container.users.get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def require_manager(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "manager":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Manager access required")
    return user


def get_owned_claim(claim_id: str, user: Annotated[User, Depends(get_current_user)]) -> Claim:
    claim = container.claims.get(claim_id)
    if claim is None or claim.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    return claim


CurrentUser = Annotated[User, Depends(get_current_user)]
Manager = Annotated[User, Depends(require_manager)]
OwnedClaim = Annotated[Claim, Depends(get_owned_claim)]
AppContainer = Annotated[Container, Depends(get_container)]
