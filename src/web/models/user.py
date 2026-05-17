from typing import Literal

from pydantic import BaseModel


class UserUpsert(BaseModel):
    user_id: str
    ai_provider: Literal["gemini", "groq", "anthropic", "auto", "off"] = "gemini"
    ai_api_key: str = ""


class UserResponse(BaseModel):
    user_id: str
    ai_provider: str
