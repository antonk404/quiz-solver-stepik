from pydantic import BaseModel


class SolveRequest(BaseModel):
    client_id: str
    client_secret: str
    access_token: str
    course_url: str
    user_id: str | None = None
