import secrets

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AppContainer, CurrentUser
from app.core.security import create_access_token
from app.models.api import DemoUser, LoginRequest, LoginResponse, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, app: AppContainer) -> LoginResponse:
    user = app.users.by_username(body.username)
    # compare_digest only accepts ASCII str, so compare bytes: non-ASCII input is just a wrong password.
    if user is None or not secrets.compare_digest(user.password.encode(), body.password.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return LoginResponse(access_token=create_access_token(user.id), user=UserPublic.from_user(user))


@router.get("/me", response_model=UserPublic)
def me(user: CurrentUser) -> UserPublic:
    return UserPublic.from_user(user)


@router.get("/demo-users", response_model=list[DemoUser])
def demo_users(app: AppContainer) -> list[DemoUser]:
    if not app.settings.auth.show_demo_users:
        return []
    return [DemoUser(username=u.username, password=u.password, name=u.name, role=u.role) for u in app.users.all()]
