from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionView(BaseModel):
    id: str
    user_id: str
    status: Literal["active", "closed", "expired"]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class EventCreate(BaseModel):
    type: str = Field(default="message", min_length=1, max_length=64)
    content: Any
    source: str = Field(default="app", max_length=64)
    sync_to_mobius: bool = True


class EventView(BaseModel):
    id: str
    session_id: str
    type: str
    content: Any
    source: str
    created_at: datetime
    mobius_resource_name: str | None = None


class AnalysisRequest(BaseModel):
    text: str | None = Field(default=None, max_length=50_000)
    include_session_events: bool = True


class AnalysisResult(BaseModel):
    provider: str
    model: str
    summary: str
    insights: list[str]
    recommendations: list[str]
    risk_level: Literal["low", "medium", "high"]
    raw: dict[str, Any] = Field(default_factory=dict)


class MobiusIngest(BaseModel):
    session_id: str | None = None
    content: Any
    resource_name: str | None = None


class DeviceCommand(BaseModel):
    content: dict[str, Any]


class DeviceCommand(BaseModel):
    content: dict[str, Any]

