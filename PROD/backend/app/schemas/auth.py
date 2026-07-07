"""Pydantic schemas for authentication endpoints."""
from typing import Literal
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    username: str
    role: Literal["viewer", "admin"]
    is_active: bool
