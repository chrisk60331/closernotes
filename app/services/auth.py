"""Authentication decorators and helpers for CloserNotes."""

import asyncio
from functools import wraps
from typing import Callable

from flask import g, redirect, request, session, url_for, flash

from app.schemas.user import User, UserRole
from app.services.backboard import BackboardService
from app.services.user import UserService


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def get_current_user() -> User | None:
    """Get the current logged-in user from session.

    Returns:
        Current user if logged in, None otherwise
    """
    # Check if already loaded in request context
    if hasattr(g, "current_user"):
        return g.current_user

    user_id = session.get("user_id")
    if not user_id:
        g.current_user = None
        return None

    # Load user from database
    backboard = BackboardService()
    user_svc = UserService(backboard)

    async def _get_user():
        return await user_svc.get_user(user_id)

    user = run_async(_get_user())
    g.current_user = user
    return user


def set_current_user(user: User) -> None:
    """Set the current user in session.

    Args:
        user: User to set as current
    """
    session["user_id"] = user.id
    session["user_email"] = user.email
    session["user_name"] = user.name
    session["user_role"] = user.role.value
    g.current_user = user


def clear_current_user() -> None:
    """Clear the current user from session."""
    session.pop("user_id", None)
    session.pop("user_email", None)
    session.pop("user_name", None)
    session.pop("user_role", None)
    if hasattr(g, "current_user"):
        g.current_user = None


def login_required(f: Callable) -> Callable:
    """Decorator to require login for a route.

    Redirects to login page if not authenticated.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if user is None:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def manager_required(f: Callable) -> Callable:
    """Decorator to require manager role for a route.

    Returns 403 if user is not a manager.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if user is None:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        if not user.is_manager():
            flash("You don't have permission to access this page.", "error")
            return redirect(url_for("ui.dashboard"))
        return f(*args, **kwargs)

    return decorated_function


def is_manager() -> bool:
    """Check if current user is a manager.

    Returns:
        True if current user has manager role
    """
    user = get_current_user()
    return user is not None and user.is_manager()


def get_session_user_info() -> dict | None:
    """Get basic user info from session without database lookup.

    Returns:
        Dict with user_id, email, name, role if logged in, None otherwise
    """
    user_id = session.get("user_id")
    if not user_id:
        return None

    return {
        "user_id": user_id,
        "email": session.get("user_email"),
        "name": session.get("user_name"),
        "role": session.get("user_role"),
        "is_manager": session.get("user_role") == UserRole.MANAGER.value,
    }
