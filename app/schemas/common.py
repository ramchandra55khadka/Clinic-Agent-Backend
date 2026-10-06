"""Validators and response shapes shared by more than one schema module."""

from pydantic import BaseModel


def valid_image_value(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if len(value) > 8_000_000:
        raise ValueError("image is too large")
    if value.startswith("https://") or value.startswith("data:image/"):
        return value
    raise ValueError("image must be an https URL or data image")



class MessageResponse(BaseModel):
    message: str

