"""Accounts, credentials and sessions: register, login, password, refresh."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.roles import Role
from app.services.auth import password_problems


class UserRegister(BaseModel):
    """Account fields only: ``POST /api/auth/register`` creates just the account.

    Personal details (name, phone) are written afterwards by
    ``POST /api/profiles`` — see :class:`app.schemas.user_profile.UserProfileCreate`.
    """

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        problems = password_problems(value)
        if problems:
            raise ValueError("Password " + ", ".join(problems))
        return value



class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)



class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        problems = password_problems(value)
        if problems:
            raise ValueError("Password " + ", ".join(problems))
        return value



class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=16)



class UserAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    first_name: str
    last_name: str | None = None
    email: EmailStr
    phone: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    address: str | None = None
    photo_url: str | None = None
    memory_enabled: bool = True
    role: str
    is_active: bool



class ManagedUserCreate(BaseModel):
    """Admin-created account: credentials **and** the initial profile.

    Only an administrator can reach this endpoint, and only clinic roles can be
    chosen — public registration is the path for patients. Unlike public
    registration (which splits account and profile across two calls) this is a
    convenience endpoint: it invokes both creation functions in one request.
    """

    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    phone: str | None = Field(default=None, min_length=7, max_length=30)
    role: Literal["staff", "admin"] = "staff"

    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        problems = password_problems(value)
        if problems:
            raise ValueError("Password " + ", ".join(problems))
        return value



class UserRoleUpdate(BaseModel):
    role: Role



class UserActiveUpdate(BaseModel):
    is_active: bool



class TokenResponse(BaseModel):
    """Issued tokens. The refresh token is stored httpOnly by the frontend BFF."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserAccountOut
