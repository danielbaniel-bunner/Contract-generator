import os
import dotenv
from typing import Any, Callable, Dict, Optional
from logging_utils import jlog

# Load env
dotenv.load_dotenv()

# Core config
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY")

# Generation knobs
MAX_PARALLEL_SECTIONS = int(os.getenv("MAX_PARALLEL_SECTIONS", "10"))
OUTLINE_MIN_SECTIONS = int(os.getenv("OUTLINE_MIN_SECTIONS", "12"))
SECTION_TARGET_WORDS = int(os.getenv("SECTION_TARGET_WORDS", "600"))
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "30"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

# Streaming UX
STREAM_CHARS_PER_EVENT = int(os.getenv("STREAM_CHARS_PER_EVENT", "5"))
STREAM_DELAY_MS = int(os.getenv("STREAM_DELAY_MS", "1"))
VALIDATION_ENABLED = os.getenv("VALIDATION_ENABLED", "true").lower() == "true"
INCLUDE_GLOBAL_CONTEXT_IN_WORKERS = os.getenv("INCLUDE_GLOBAL_CONTEXT_IN_WORKERS", "true").lower() == "true"
