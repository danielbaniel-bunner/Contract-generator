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

# Optional policy inputs (NO specifics by default)
def _get_env_optional(name: str, cast: Optional[Callable[[str], Any]] = None) -> Optional[Any]:
    raw = os.getenv(name, "").strip()
    jlog("env.read", name=name, present=bool(raw))
    if raw == "":
        return None
    if cast:
        try:
            val = cast(raw)
            jlog("env.cast.ok", name=name, value=val)
            return val
        except Exception as e:
            jlog("env.cast.fail", name=name, raw=raw, error=str(e))
            return None
    return raw

PAYMENT_NET_DAYS = _get_env_optional("PAYMENT_NET_DAYS", int)
AUTO_RENEWAL_NOTICE_DAYS = _get_env_optional("AUTO_RENEWAL_NOTICE_DAYS", int)
SLA_CREDIT_CAP_PERCENT = _get_env_optional("SLA_CREDIT_CAP_PERCENT", int)
SLA_CLAIM_WINDOW_DAYS = _get_env_optional("SLA_CLAIM_WINDOW_DAYS", int)
BREACH_NOTICE_HOURS = _get_env_optional("BREACH_NOTICE_HOURS", int)
SLA_EXCLUSIVE_REMEDY = _get_env_optional("SLA_EXCLUSIVE_REMEDY", lambda v: v.lower() == "true")
FORCE_MAJEURE_PAYMENT_CONTINUES = _get_env_optional("FORCE_MAJEURE_PAYMENT_CONTINUES", lambda v: v.lower() == "true")
ARBITRATION_PROVIDER = _get_env_optional("ARBITRATION_PROVIDER", str)
ARBITRATORS = _get_env_optional("ARBITRATORS", int)
ARBITRATION_LANGUAGE = _get_env_optional("ARBITRATION_LANGUAGE", str)

def build_policy_params(jurisdiction: str) -> Dict[str, Any]:
    jlog("policy_params.build.start", jurisdiction=jurisdiction)
    params: Dict[str, Any] = {}
    if PAYMENT_NET_DAYS is not None: params["PAYMENT_NET_DAYS"] = PAYMENT_NET_DAYS
    if AUTO_RENEWAL_NOTICE_DAYS is not None: params["AUTO_RENEWAL_NOTICE_DAYS"] = AUTO_RENEWAL_NOTICE_DAYS
    if SLA_CREDIT_CAP_PERCENT is not None: params["SLA_CREDIT_CAP_PERCENT"] = SLA_CREDIT_CAP_PERCENT
    if SLA_CLAIM_WINDOW_DAYS is not None: params["SLA_CLAIM_WINDOW_DAYS"] = SLA_CLAIM_WINDOW_DAYS
    if BREACH_NOTICE_HOURS is not None: params["BREACH_NOTICE_HOURS"] = BREACH_NOTICE_HOURS
    if SLA_EXCLUSIVE_REMEDY is not None: params["SLA_EXCLUSIVE_REMEDY"] = SLA_EXCLUSIVE_REMEDY
    if FORCE_MAJEURE_PAYMENT_CONTINUES is not None: params["FORCE_MAJEURE_PAYMENT_CONTINUES"] = FORCE_MAJEURE_PAYMENT_CONTINUES
    if ARBITRATION_PROVIDER: params["ARBITRATION_PROVIDER"] = ARBITRATION_PROVIDER
    jur = (jurisdiction or "").strip()
    if jur: params["ARBITRATION_SEAT"] = jur
    if ARBITRATORS is not None: params["ARBITRATORS"] = ARBITRATORS
    if ARBITRATION_LANGUAGE: params["ARBITRATION_LANGUAGE"] = ARBITRATION_LANGUAGE
    jlog("policy_params.build.finish", params=params)
    return params

def policy_params_to_line(params: Dict[str, Any]) -> str:
    def v(x):
        if isinstance(x, bool):
            return "true" if x else "false"
        return str(x)
    keys = sorted(params.keys())
    line = "; ".join(f"{k}={v(params[k])}" for k in keys)
    jlog("policy_params.line", line=line)
    return line

# Reverse-engineering helper text
REVERSE_ENGINEERING_GUIDANCE = (
    "Reverse-engineering discipline: For each section, identify the doctrine served "
    "(Mutual Assent, Consideration, Capacity/Legality, Definiteness, Risk Allocation, Remedies). "
    "Expand the section into subclauses by asking: what risk is addressed, whose interests are favored, "
    "and which carve-outs/exceptions refine scope. Maintain definiteness; avoid unconscionability. "
    "If specific numeric values or providers are not present in the Global Contract Context PARAMS line, "
    "avoid inventing numbers or named providers; use generic phrasing instead."
)
