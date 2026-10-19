import secrets

from fastapi import HTTPException, Request, status

from camp_agent.config import Settings

STAFF_SESSION_KEY = "staff"
LOGIN_PATH = "/staff/login"


def credentials_match(settings: Settings, user: str, password: str) -> bool:
    user_ok = secrets.compare_digest(user.encode(), settings.staff_user.encode())
    expected = settings.staff_password.get_secret_value().encode()
    password_ok = secrets.compare_digest(password.encode(), expected)
    return user_ok and password_ok


def require_staff(request: Request) -> None:
    # Open intake stops at the staff view and its approvals (D9).
    if not request.session.get(STAFF_SESSION_KEY):
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": LOGIN_PATH})
