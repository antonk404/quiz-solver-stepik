from pydantic import BaseModel

class SolveRequest(BaseModel):
    client_id: str
    client_secret: str
    access_token: str
    course_url: str


class JobStatus(BaseModel):
    job_id: str
    status: str  # running | completed | failed | not_found
    progress: str = ""
    error: str = ""
