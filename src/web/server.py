import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from src.config import settings
from src.db.user_repository import UserRepository
from src.web.models import JobStatus, SolveRequest, UserResponse, UserUpsert

logger = logging.getLogger(__name__)

_jobs: dict[str, JobStatus] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url:
        app.state.user_repo = await UserRepository.create(settings.database_url)
    else:
        app.state.user_repo = None
    yield
    if getattr(app.state, "user_repo", None):
        await app.state.user_repo.close()


app = FastAPI(lifespan=lifespan)


@app.post("/api/users")
async def upsert_user(body: UserUpsert, req: Request) -> UserResponse:
    user_repo: UserRepository | None = getattr(req.app.state, "user_repo", None)
    if not user_repo:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    await user_repo.upsert(body.user_id, body.ai_provider, body.ai_api_key)
    return UserResponse(user_id=body.user_id, ai_provider=body.ai_provider)


@app.get("/api/users/{user_id}")
async def get_user(user_id: str, req: Request) -> UserResponse:
    user_repo: UserRepository | None = getattr(req.app.state, "user_repo", None)
    if not user_repo:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    user = await user_repo.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return UserResponse(user_id=user["user_id"], ai_provider=user["ai_provider"])


@app.post("/api/solve")
async def solve(request: SolveRequest, req: Request) -> dict:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobStatus(job_id=job_id, status="running")
    user_repo = getattr(req.app.state, "user_repo", None)
    asyncio.create_task(_run_solver(job_id, request, user_repo))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JobStatus:
    return _jobs.get(job_id, JobStatus(job_id=job_id, status="not_found"))


async def _run_solver(job_id: str, request: SolveRequest, user_repo: UserRepository | None = None) -> None:
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

        ai_kwargs: dict = {}
        if request.user_id and user_repo:
            user = await user_repo.get(request.user_id)
            if user:
                provider = user["ai_provider"]
                key = user["ai_api_key"]
                ai_kwargs["ai_provider"] = provider
                if provider == "gemini":
                    ai_kwargs["api_key"] = key
                elif provider == "groq":
                    ai_kwargs["groq_api_key"] = key
                elif provider == "anthropic":
                    ai_kwargs["anthropic_api_key"] = key

        ai = AIClient(**ai_kwargs)
        registry = create_default_registry()

        try:
            async with StepikHTTPClient(auth) as http:
                api = StepikAPIClient(http)
                step_proc = StepProcessor(ai, api, registry, cache=cache)
                course_proc = CourseProcessor(step_proc)

                def on_progress(current: int, total: int) -> None:
                    percent = round(current / total * 100) if total else 0
                    _jobs[job_id] = JobStatus(
                        job_id=job_id, status="running",
                        progress=str(percent),
                        current_step=current, total_steps=total,
                    )

                solved = await course_proc.process_course(course_id, progress_callback=on_progress)
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
