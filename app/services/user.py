"""User service for CloserNotes authentication."""

import json
import uuid
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from app.schemas.user import User, UserCreate, UserRole, UserUpdate
from app.services.backboard import BackboardService


# Assistant name for storing users
USERS_ASSISTANT_NAME = "closernotes-users"


class UserService:
    """Service for user management with Backboard storage."""

    def __init__(self, backboard: BackboardService):
        """Initialize the user service.

        Args:
            backboard: BackboardService instance
        """
        self._backboard = backboard
        self._users_assistant_id: str | None = None

    async def _get_users_assistant_id(self) -> str:
        """Get or create the users assistant ID."""
        if self._users_assistant_id:
            return self._users_assistant_id

        # Try to find existing assistant
        assistant = await self._backboard.find_assistant_by_name(USERS_ASSISTANT_NAME)
        if assistant:
            self._users_assistant_id = str(assistant.assistant_id)
            return self._users_assistant_id

        # Create new assistant for users
        result = await self._backboard.create_assistant(
            name=USERS_ASSISTANT_NAME,
            system_prompt="User storage assistant for CloserNotes authentication.",
        )
        self._users_assistant_id = str(result.assistant_id)
        return self._users_assistant_id

    async def create_user(
        self,
        email: str,
        password: str,
        name: str,
        role: UserRole = UserRole.USER,
    ) -> User:
        """Create a new user.

        Args:
            email: User email address
            password: Plain text password (will be hashed)
            name: User display name
            role: User role

        Returns:
            Created user

        Raises:
            ValueError: If email already exists
        """
        # Check if email already exists
        existing = await self.get_user_by_email(email)
        if existing:
            raise ValueError(f"User with email {email} already exists")

        assistant_id = await self._get_users_assistant_id()

        user = User(
            id=str(uuid.uuid4()),
            email=email.lower().strip(),
            password_hash=generate_password_hash(password),
            name=name.strip(),
            role=role,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Store user in memory (metadata excluded - can cause Backboard API issues)
        await self._backboard.add_memory(
            assistant_id=assistant_id,
            content=user.to_memory_content(),
        )

        return user

    async def authenticate(self, email: str, password: str) -> User | None:
        """Authenticate a user by email and password.

        Args:
            email: User email address
            password: Plain text password

        Returns:
            User if authentication successful, None otherwise
        """
        user = await self.get_user_by_email(email)
        if not user:
            return None

        if not check_password_hash(user.password_hash, password):
            return None

        return user

    async def get_user(self, user_id: str) -> User | None:
        """Get a user by ID.

        Args:
            user_id: User ID

        Returns:
            User if found, None otherwise
        """
        assistant_id = await self._get_users_assistant_id()
        memories = await self._backboard.get_memories(assistant_id)

        for memory in memories.memories if hasattr(memories, "memories") else memories:
            try:
                content = memory.content if hasattr(memory, "content") else memory.get("content")
                if not content:
                    continue
                data = json.loads(content)
                if data.get("id") == user_id:
                    return User.model_validate(data)
            except (json.JSONDecodeError, ValueError):
                continue

        return None

    async def get_user_by_email(self, email: str) -> User | None:
        """Get a user by email address.

        Args:
            email: User email address

        Returns:
            User if found, None otherwise
        """
        email_lower = email.lower().strip()
        assistant_id = await self._get_users_assistant_id()
        memories = await self._backboard.get_memories(assistant_id)

        for memory in memories.memories if hasattr(memories, "memories") else memories:
            try:
                content = memory.content if hasattr(memory, "content") else memory.get("content")
                if not content:
                    continue
                data = json.loads(content)
                if data.get("email", "").lower() == email_lower:
                    return User.model_validate(data)
            except (json.JSONDecodeError, ValueError):
                continue

        return None

    async def list_users(self) -> list[User]:
        """List all users.

        Returns:
            List of all users
        """
        assistant_id = await self._get_users_assistant_id()
        memories = await self._backboard.get_memories(assistant_id)

        users = []
        for memory in memories.memories if hasattr(memories, "memories") else memories:
            try:
                content = memory.content if hasattr(memory, "content") else memory.get("content")
                if not content:
                    continue
                data = json.loads(content)
                if data.get("id"):  # Valid user record
                    users.append(User.model_validate(data))
            except (json.JSONDecodeError, ValueError):
                continue

        return users

    async def update_user(self, user_id: str, update: UserUpdate) -> User | None:
        """Update a user.

        Args:
            user_id: User ID
            update: Update data

        Returns:
            Updated user if found, None otherwise
        """
        assistant_id = await self._get_users_assistant_id()
        memories = await self._backboard.get_memories(assistant_id)

        for memory in memories.memories if hasattr(memories, "memories") else memories:
            try:
                content = memory.content if hasattr(memory, "content") else memory.get("content")
                memory_id = memory.memory_id if hasattr(memory, "memory_id") else memory.get("memory_id")
                if not content or not memory_id:
                    continue

                data = json.loads(content)
                if data.get("id") == user_id:
                    # Apply updates
                    update_dict = update.model_dump(exclude_none=True)
                    if "email" in update_dict:
                        update_dict["email"] = update_dict["email"].lower().strip()
                    data.update(update_dict)
                    data["updated_at"] = datetime.utcnow().isoformat()

                    user = User.model_validate(data)

                    await self._backboard.update_memory(
                        assistant_id=assistant_id,
                        memory_id=str(memory_id),
                        content=user.to_memory_content(),
                    )

                    return user
            except (json.JSONDecodeError, ValueError):
                continue

        return None

    async def reset_password(self, user_id: str, new_password: str) -> User | None:
        """Reset a user's password.

        Args:
            user_id: User ID
            new_password: New plain text password

        Returns:
            Updated user if found, None otherwise
        """
        assistant_id = await self._get_users_assistant_id()
        memories = await self._backboard.get_memories(assistant_id)

        for memory in memories.memories if hasattr(memories, "memories") else memories:
            try:
                content = memory.content if hasattr(memory, "content") else memory.get("content")
                memory_id = memory.memory_id if hasattr(memory, "memory_id") else memory.get("memory_id")
                if not content or not memory_id:
                    continue

                data = json.loads(content)
                if data.get("id") == user_id:
                    data["password_hash"] = generate_password_hash(new_password)
                    data["updated_at"] = datetime.utcnow().isoformat()

                    user = User.model_validate(data)

                    await self._backboard.update_memory(
                        assistant_id=assistant_id,
                        memory_id=str(memory_id),
                        content=user.to_memory_content(),
                    )

                    return user
            except (json.JSONDecodeError, ValueError):
                continue

        return None

    async def delete_user(self, user_id: str) -> bool:
        """Delete a user.

        Args:
            user_id: User ID

        Returns:
            True if deleted, False if not found
        """
        assistant_id = await self._get_users_assistant_id()
        memories = await self._backboard.get_memories(assistant_id)

        for memory in memories.memories if hasattr(memories, "memories") else memories:
            try:
                content = memory.content if hasattr(memory, "content") else memory.get("content")
                memory_id = memory.memory_id if hasattr(memory, "memory_id") else memory.get("memory_id")
                if not content or not memory_id:
                    continue

                data = json.loads(content)
                if data.get("id") == user_id:
                    await self._backboard.delete_memory(
                        assistant_id=assistant_id,
                        memory_id=str(memory_id),
                    )
                    return True
            except (json.JSONDecodeError, ValueError):
                continue

        return False

    async def ensure_default_manager(self) -> User | None:
        """Ensure at least one manager exists, creating default if needed.

        Creates a default manager account if no users exist.
        Default credentials: admin@closernotes.local / changeme123

        Returns:
            The default manager if created, None if users already exist
        """
        users = await self.list_users()
        if users:
            return None

        # Create default manager
        return await self.create_user(
            email="admin@closernotes.local",
            password="changeme123",
            name="Admin",
            role=UserRole.MANAGER,
        )
