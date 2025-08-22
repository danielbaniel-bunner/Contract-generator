import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from logging_utils import jlog
from config import CORS_ORIGINS
from models import GenerateRequest, StopRequest, Job, JOBS
from services import run_job, sse

app = FastAPI(title="Contract Generator (LLM-Guided, Non-Specific, Logged)", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware: request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    import time
    start = time.monotonic()
    jlog("http.request.start", method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
        dur_ms = int((time.monotonic() - start) * 1000)
        jlog("http.request.finish", method=request.method, path=request.url.path,
             status=response.status_code, duration_ms=dur_ms)
        return response
    except Exception as e:
        dur_ms = int((time.monotonic() - start) * 1000)
        jlog("http.request.error", method=request.method, path=request.url.path,
             duration_ms=dur_ms, error=str(e))
        raise

# -------- Routes --------

@app.post("/generate")
async def generate(req: GenerateRequest):
    jlog("route.generate", prompt_len=len(req.prompt))
    job = Job(req.prompt)
    JOBS[job.id] = job
    job.task = asyncio.create_task(run_job(job, JOBS))
    jlog("job.created", job_id=job.id, active_jobs=len(JOBS))
    return {"jobId": job.id}

@app.get("/stream/{job_id}")
async def stream(job_id: str, request: Request):
    jlog("route.stream.open", job_id=job_id)
    job = JOBS.get(job_id)
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }

    if not job:
        jlog("stream.missing", job_id=job_id)
        async def done_iter():
            yield "retry: 60000\n\n"
            yield "event: done\n\ndata:\n\n"
        return StreamingResponse(done_iter(), headers=headers)

    async def event_iter():
        try:
            yield "retry: 60000\n\n"
            while True:
                if await request.is_disconnected():
                    jlog("stream.client_disconnected", job_id=job_id)
                    break
                try:
                    msg = await asyncio.wait_for(job.queue.get(), timeout=1.0)
                    if msg.startswith("event: chunk"):
                        jlog("stream.chunk", job_id=job_id, size=len(msg))
                    elif msg.startswith("event: error"):
                        jlog("stream.error", job_id=job_id)
                    elif msg.startswith("event: done"):
                        jlog("stream.done", job_id=job_id)
                    yield msg
                    if "event: done" in msg:
                        break
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            jlog("stream.close", job_id=job_id)

    return StreamingResponse(event_iter(), headers=headers)

@app.post("/stop")
async def stop(req: StopRequest):
    jlog("route.stop", job_id=req.jobId)
    job = JOBS.get(req.jobId)
    if not job:
        jlog("stop.unknown", job_id=req.jobId)
        return {"ok": True, "message": "job already finished or unknown"}
    job.cancel.set()
    if job.task and not job.task.done():
        job.task.cancel()
    jlog("stop.ok", job_id=req.jobId)
    await job.queue.put(sse("error", "Generation stopped by user."))
    await job.queue.put(sse("done", ""))
    return {"ok": True}
