from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: str
    org_id: uuid.UUID
