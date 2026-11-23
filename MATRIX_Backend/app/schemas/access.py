from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UserAccessResponse(BaseModel):
    user_id: UUID
    full_name: str | None
    access_status: str | None
    activation_completed_at: datetime | None
    has_matrix_access: bool
