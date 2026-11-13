from fastapi import APIRouter, Request
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.core.errors import AppError
from app.core.ratelimit import AUTH_LIMIT, GUEST_CREATE_LIMIT, limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies import CurrentUser, Credentials, DbSession, OptionalUser, user_from_token
from app.models import InterviewSession, Resume, Role, User
from app.schemas import ChangePasswordRequest, LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user.id, user.role, user.password_hash), user=UserOut.model_validate(user))


def _email_taken() -> AppError:
    return AppError("email_taken", "An account with this email already exists.", 409)


@router.post("/guest", response_model=TokenResponse, status_code=201)
@limiter.limit(GUEST_CREATE_LIMIT)
async def create_guest(request: Request, db: DbSession) -> TokenResponse:
    user = User(display_name="Guest", role=Role.guest.value, is_guest=True)
    db.add(user)
    await db.commit()
    return _token_response(user)


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit(AUTH_LIMIT)
async def register(request: Request, body: RegisterRequest, db: DbSession, current: OptionalUser) -> TokenResponse:
    if await db.scalar(select(User.id).where(User.email == body.email)):
        raise _email_taken()
    password_hash = await hash_password(body.password)

    if current is not None and current.is_guest:
        user = current  # upgrade in place: same id, history is kept
        user.email, user.password_hash, user.display_name = body.email, password_hash, body.display_name
        user.is_guest, user.role = False, Role.user.value
    else:
        user = User(
            email=body.email, password_hash=password_hash, display_name=body.display_name,
            is_guest=False, role=Role.user.value,
        )
        db.add(user)
    try:
        await db.commit()
    except IntegrityError:  # lost a race on the unique email
        await db.rollback()
        raise _email_taken() from None
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_LIMIT)
async def login(request: Request, body: LoginRequest, db: DbSession, current: OptionalUser) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == body.email))
    if not await verify_password(body.password, user.password_hash if user else None) or user is None:
        raise AppError("invalid_credentials", "Invalid email or password.", 401)

    guest = current if (body.merge_guest and current is not None and current.is_guest and current.id != user.id) else None
    if guest is not None:
        guest_id = guest.id
        await db.execute(update(InterviewSession).where(InterviewSession.user_id == guest_id).values(user_id=user.id))
        await db.execute(update(Resume).where(Resume.user_id == guest_id).values(user_id=user.id))
        db.expunge(guest)
        await db.execute(delete(User).where(User.id == guest_id, User.is_guest.is_(True)))  # FK cascade clears counters
    await db.commit()
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(creds: Credentials, db: DbSession) -> TokenResponse:
    """Swap a valid or recently expired token (REFRESH_GRACE_DAYS) for a fresh one. Role is re-read from the DB."""
    if creds is None:
        raise AppError("not_authenticated", "Authentication required.", 401, {"WWW-Authenticate": "Bearer"})
    grace = get_settings().REFRESH_GRACE_DAYS * 86400
    user = await user_from_token(creds.credentials, db, leeway_seconds=grace)
    return _token_response(user)


@router.post("/change-password", response_model=TokenResponse)
@limiter.limit(AUTH_LIMIT)
async def change_password(request: Request, body: ChangePasswordRequest, user: CurrentUser, db: DbSession) -> TokenResponse:
    """Signed-in users only. Old tokens stop working (the token embeds a password fingerprint); the reply has a new one."""
    if user.is_guest or not user.password_hash:
        raise AppError("forbidden", "Create an account first to set a password.", 403)
    if not await verify_password(body.current_password, user.password_hash):
        raise AppError("wrong_password", "Your current password is incorrect.", 400)
    if body.new_password == body.current_password:
        raise AppError("same_password", "Choose a password different from your current one.", 400)
    user.password_hash = await hash_password(body.new_password)
    await db.commit()
    return _token_response(user)
