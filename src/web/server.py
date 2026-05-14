import asyncio
import logging
import uuid

from fastapi import FastAPI

from src.web.models import JobStatus, SolveRequest

logger = logging.getLogger(__name__)

app = FastAPI()

_jobs: dict[str, JobStatus] = {}


@app.post("/api/solve")
async def solve(request: SolveRequest) -> dict:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobStatus(job_id=job_id, status="running")
    asyncio.create_task(_run_solver(job_id, request))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JobStatus:
    return _jobs.get(job_id, JobStatus(job_id=job_id, status="not_found"))


async def _run_solver(job_id: str, request: SolveRequest) -> None:
    from src.ai_client import AIClient
    from src.config import settings
    from src.db.knowledge_cache import KnowledgeCache
    from src.orchestration import CourseProcessor, StepProcessor, create_default_registry
    from src.stepik import StepikAPIClient, StepikHTTPClient
    from src.stepik.auth import StepikAuth
    from src.stepik.utils import parse_course_id

    try:
        course_id = parse_course_id(request.course_url)
        if not course_id:
            _jobs[job_id] = JobStatus(job_id=job_id, status="failed", error="Неверный URL курса")
            return

        auth = StepikAuth.from_token(request.access_token)

        cache = None
        if settings.database_url:
            cache = KnowledgeCache(settings.database_url)
            await cache.init()

        ai = AIClient()
        registry = create_default_registry()

        try:
            async with StepikHTTPClient(auth) as http:
                api = StepikAPIClient(http)
                step_proc = StepProcessor(ai, api, registry, cache=cache)
                course_proc = CourseProcessor(step_proc)
                solved = await course_proc.process_course(course_id)
                _jobs[job_id] = JobStatus(
                    job_id=job_id,
                    status="completed",
                    progress=str(solved),
                )
        finally:
            if cache:
                await cache.close()

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        _jobs[job_id] = JobStatus(job_id=job_id, status="failed", error=str(e))
