"""Shared validation for descriptions on newly created orders."""

DESCRIPTION_MIN_LENGTH = 3
DESCRIPTION_MAX_LENGTH = 700


def validate_description(value: str | None) -> str:
    description = value.strip() if isinstance(value, str) else ""
    if len(description) < DESCRIPTION_MIN_LENGTH:
        raise ValueError("An order description of at least three characters is required")
    return description[:DESCRIPTION_MAX_LENGTH]
