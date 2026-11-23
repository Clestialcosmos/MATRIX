from uuid import UUID

from pydantic import BaseModel


class AdminProfileSummary(BaseModel):
    user_id: UUID
    full_name: str | None
    access_status: str
