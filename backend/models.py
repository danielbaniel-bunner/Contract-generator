from pydantic import BaseModel
import asyncio, uuid, time
from typing import Dict
from logging_utils import jlog

class GenerateRequest(BaseModel):
    prompt: str

class StopRequest(BaseModel):
    jobId: str

class Job:
    def __init__(self, prompt: str):
        self.id = uuid.uuid4().hex
        self.prompt = prompt
        self.queue: "asyncio.Queue[str]" = asyncio.Queue()
        self.cancel = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.created_at = time.monotonic()
        jlog("job.init", job_id=self.id, prompt_len=len(prompt))

JOBS: Dict[str, Job] = {}
