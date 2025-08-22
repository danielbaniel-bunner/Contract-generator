import json
import logging
import os

# Configure root logging once
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("contract")

def jlog(msg: str, **kw):
    """Log a message with JSON-ish context; values must be JSON-serializable."""
    try:
        if kw:
            ctx = " ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in kw.items())
            log.info(f"{msg} | {ctx}")
        else:
            log.info(msg)
    except Exception as e:
        log.info(f"{msg} | logging_error={e}")
