from pydantic import BaseModel


class JobStatus(BaseModel):
    job_id: str
    status: str  # running | completed | failed | not_found
    progress: str = ""
    error: str = ""
    current_step: int = 0
    total_steps: int = 0
