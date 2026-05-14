from pydantic import BaseModel


class UserUpsert(BaseModel):
    user_id: str
    ai_provider: str = "gemini"  # gemini | groq | anthropic
    ai_api_key: str


class UserResponse(BaseModel):
    user_id: str
    ai_provider: str
