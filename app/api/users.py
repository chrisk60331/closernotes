"""User management API endpoints."""

import asyncio
from flask import Blueprint, request, jsonify, current_app

from app.schemas.user import UserRole
from app.services.auth import manager_required
from app.services.backboard import BackboardService
from app.services.user import UserService

users_bp = Blueprint("users", __name__)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@users_bp.route("/users", methods=["GET"])
@manager_required
def list_users():
    """List all users (manager only).

    Returns:
        JSON array of users (without password hashes)
    """
    try:
        async def _list():
            backboard = BackboardService()
            user_svc = UserService(backboard)
            users = await user_svc.list_users()
            return [
                {
                    "id": u.id,
                    "email": u.email,
                    "name": u.name,
                    "role": u.role.value,
                    "created_at": u.created_at.isoformat(),
                }
                for u in users
            ]

        users = run_async(_list())
        return jsonify({"users": users}), 200

    except Exception as e:
        current_app.logger.exception("Error listing users")
        return jsonify({"error": str(e)}), 500


@users_bp.route("/users", methods=["POST"])
@manager_required
def create_user():
    """Create a new user (manager only).

    Request body:
        {
            "email": "user@example.com",
            "password": "password123",
            "name": "User Name",
            "role": "user" or "manager"
        }

    Returns:
        JSON with created user
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        email = json_data.get("email", "").strip()
        password = json_data.get("password", "")
        name = json_data.get("name", "").strip()
        role_str = json_data.get("role", "user")

        # Validation
        if not email:
            return jsonify({"error": "Email is required"}), 400
        if not password or len(password) < 8:
            return jsonify({"error": "Password must be at least 8 characters"}), 400
        if not name:
            return jsonify({"error": "Name is required"}), 400

        try:
            role = UserRole(role_str)
        except ValueError:
            role = UserRole.USER

        async def _create():
            backboard = BackboardService()
            user_svc = UserService(backboard)
            return await user_svc.create_user(
                email=email,
                password=password,
                name=name,
                role=role,
            )

        user = run_async(_create())

        return jsonify({
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role.value,
                "created_at": user.created_at.isoformat(),
            }
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("Error creating user")
        return jsonify({"error": str(e)}), 500


@users_bp.route("/users/<user_id>/reset-password", methods=["POST"])
@manager_required
def reset_password(user_id: str):
    """Reset a user's password (manager only).

    Request body:
        {"new_password": "newpassword123"}

    Returns:
        JSON with success message
    """
    try:
        json_data = request.get_json()
        if not json_data:
            return jsonify({"error": "Request body is required"}), 400

        new_password = json_data.get("new_password", "")
        if not new_password or len(new_password) < 8:
            return jsonify({"error": "Password must be at least 8 characters"}), 400

        async def _reset():
            backboard = BackboardService()
            user_svc = UserService(backboard)
            return await user_svc.reset_password(user_id, new_password)

        user = run_async(_reset())

        if not user:
            return jsonify({"error": "User not found"}), 404

        return jsonify({"success": True, "message": "Password reset successfully"}), 200

    except Exception as e:
        current_app.logger.exception("Error resetting password")
        return jsonify({"error": str(e)}), 500


@users_bp.route("/users/<user_id>", methods=["DELETE"])
@manager_required
def delete_user(user_id: str):
    """Delete a user (manager only).

    Returns:
        JSON with success message
    """
    try:
        async def _delete():
            backboard = BackboardService()
            user_svc = UserService(backboard)
            return await user_svc.delete_user(user_id)

        deleted = run_async(_delete())

        if not deleted:
            return jsonify({"error": "User not found"}), 404

        return jsonify({"success": True, "message": "User deleted"}), 200

    except Exception as e:
        current_app.logger.exception("Error deleting user")
        return jsonify({"error": str(e)}), 500
