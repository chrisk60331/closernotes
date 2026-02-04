"""Authentication routes for CloserNotes."""

import asyncio

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.schemas.user import UserRole
from app.services.auth import clear_current_user, get_current_user, set_current_user
from app.services.backboard import BackboardService
from app.services.user import UserService

auth_bp = Blueprint("auth", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login."""
    # Redirect if already logged in
    if get_current_user():
        return redirect(url_for("ui.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.", "error")
            return render_template("login.html", email=email)

        backboard = BackboardService()
        user_svc = UserService(backboard)

        async def _authenticate():
            # Ensure default manager exists on first login attempt
            await user_svc.ensure_default_manager()
            return await user_svc.authenticate(email, password)

        user = run_async(_authenticate())

        if user:
            set_current_user(user)
            flash(f"Welcome back, {user.name}!", "success")

            # Redirect to next URL or dashboard
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("ui.dashboard"))
        else:
            flash("Invalid email or password.", "error")
            return render_template("login.html", email=email)

    return render_template("login.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    """Handle user signup."""
    # Redirect if already logged in
    if get_current_user():
        return redirect(url_for("ui.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        name = request.form.get("name", "").strip()

        # Validation
        errors = []
        if not email:
            errors.append("Email is required.")
        if not name:
            errors.append("Name is required.")
        if not password:
            errors.append("Password is required.")
        elif len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("signup.html", email=email, name=name)

        backboard = BackboardService()
        user_svc = UserService(backboard)

        async def _create_user():
            # Check if this is the first user (make them a manager)
            users = await user_svc.list_users()
            role = UserRole.MANAGER if len(users) == 0 else UserRole.USER

            return await user_svc.create_user(
                email=email,
                password=password,
                name=name,
                role=role,
            )

        try:
            user = run_async(_create_user())
            set_current_user(user)

            if user.is_manager():
                flash(f"Welcome, {user.name}! You're the first user, so you've been made a Manager.", "success")
            else:
                flash(f"Welcome, {user.name}! Your account has been created.", "success")

            return redirect(url_for("ui.dashboard"))

        except ValueError as e:
            flash(str(e), "error")
            return render_template("signup.html", email=email, name=name)

    return render_template("signup.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Handle user logout."""
    clear_current_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
