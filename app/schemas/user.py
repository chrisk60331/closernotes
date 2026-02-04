"""User schemas for CloserNotes authentication."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, EmailStr


class UserRole(str, Enum):
    """User role enumeration."""

    MANAGER = "manager"
    USER = "user"


class User(BaseModel):
    """A user in the system."""

    id: str = Field(..., description="Unique user identifier")
    email: str = Field(..., description="User email address")
    password_hash: str = Field(..., description="Hashed password")
    name: str = Field(..., description="User display name")
    role: UserRole = Field(UserRole.USER, description="User role")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_memory_content(self) -> str:
        """Serialize user to memory-friendly format."""
        return self.model_dump_json()

    def to_memory_metadata(self) -> dict[str, Any]:
        """Generate memory metadata tags."""
        return {
            "type": "user",
            "id": self.id,
            "email": self.email,
            "role": self.role.value,
        }

    def is_manager(self) -> bool:
        """Check if user has manager role."""
        return self.role == UserRole.MANAGER


class UserCreate(BaseModel):
    """Request model for creating a user."""

    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password")
    name: str = Field(..., description="User display name")
    role: UserRole = Field(UserRole.USER, description="User role")


class UserUpdate(BaseModel):
    """Request model for updating a user."""

    email: str | None = None
    name: str | None = None
    role: UserRole | None = None


class UserPublic(BaseModel):
    """Public user info (no password hash)."""

    id: str
    email: str
    name: str
    role: UserRole
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserPublic":
        """Create public user from full user."""
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            created_at=user.created_at,
        )
