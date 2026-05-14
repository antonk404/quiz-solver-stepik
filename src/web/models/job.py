from pydantic import BaseModel


class JobStatus(BaseModel):
    job_id: str
    status: str  # running | completed | failed | not_found
    progress: str = ""
    error: str = ""
