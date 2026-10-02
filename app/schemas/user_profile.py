"""Profile creation and edits (name, contact and personal details)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import valid_image_value

#: The only gender values the API accepts. Canonical form (not an abbreviation),
#: so a stored value is never ambiguous — this is what `GENDER_OPTIONS` mirrors
#: on the frontend. `None` stays allowed: the field is optional.
Gender = Literal["Male", "Female", "Other"]

GENDER_OPTIONS: tuple[str, ...] = ("Male", "Female", "Other")


def _valid_gender(value: str | None) -> str | None:
    """Accepts one of :data:`GENDER_OPTIONS`, or ``None`` to clear the field."""
    if value is None:
        return None
    if value not in GENDER_OPTIONS:
        raise ValueError("Gender must be one of: " + ", ".join(GENDER_OPTIONS))
    return value


def _valid_profile_photo(value: str | None) -> str | None:
    return valid_image_value(value)


class UserProfileCreate(BaseModel):
    """Personal fields for ``POST /api/profiles``.

    The profile's ``email`` is copied from the authenticated account — it is
    never supplied by the client.
    """

    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=7, max_length=30)
    date_of_birth: date | None = None
    gender: Gender | None = None
    address: str | None = Field(default=None, max_length=500)


class UserProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=7, max_length=30)
    date_of_birth: date | None = None
    gender: Gender | None = None
    address: str | None = Field(default=None, max_length=500)
    photo_url: str | None = Field(default=None, max_length=200_000)
    memory_enabled: bool | None = None

    @field_validator("gender")
    @classmethod
    def gender_policy(cls, value: str | None) -> str | None:
        return _valid_gender(value)

    @field_validator("photo_url")
    @classmethod
    def profile_photo_policy(cls, value: str | None) -> str | None:
        return _valid_profile_photo(value)


class UserProfileOut(BaseModel):
    """A ``user_profile`` row as returned by the profile endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str | None = None
    first_name: str
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    address: str | None = None
    photo_url: str | None = None
    memory_enabled: bool = True
