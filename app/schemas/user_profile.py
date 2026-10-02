"""Profile edits (name, phone, photo)."""

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import valid_image_value


def _valid_profile_photo(value: str | None) -> str | None:
    return valid_image_value(value)



class UserProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=7, max_length=30)
    photo_url: str | None = Field(default=None, max_length=200_000)
    memory_enabled: bool | None = None

    @field_validator("photo_url")
    @classmethod
    def profile_photo_policy(cls, value: str | None) -> str | None:
        return _valid_profile_photo(value)
