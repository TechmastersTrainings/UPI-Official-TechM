from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import RoleName

T = TypeVar("T")

PlatformRole = Literal[RoleName.SUPER_ADMIN, RoleName.PLATFORM_ADMIN, RoleName.PLATFORM_SUPPORT]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class CreatePlatformUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=12, max_length=128)
    role: PlatformRole


class UpdatePlatformUserRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    role: PlatformRole | None = None
    is_active: bool | None = None
    unlock: bool = False


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_type: str
    actor_user_id: str | None
    actor_label: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    merchant_id: str | None
    ip_address: str | None
    user_agent: str | None
    request_id: str | None
    details: dict | None
    created_at: datetime
