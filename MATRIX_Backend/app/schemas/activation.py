from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.schemas.access import UserAccessResponse


class ActivationIssuanceResponse(BaseModel):
    user_id: UUID
    expires_at: datetime
    email_delivery: Literal["accepted"]


class ActivationConsumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activation_code: SecretStr = Field(min_length=1, max_length=256)

    @field_validator("activation_code")
    @classmethod
    def require_non_whitespace_code(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Activation code is required")
        return value


class ActivationConsumeResponse(BaseModel):
    status: Literal["activated"]
    access: UserAccessResponse
