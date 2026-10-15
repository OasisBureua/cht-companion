"""Force app logs onto stdout — uvicorn access logs alone hide cht-companion.*."""

from __future__ import annotations

import logging
import sys

_APP_LOGGERS = (
    "cht-companion",
    "cht-companion.bedrock",
    "cht-companion.chat",
)


def configure_app_logging() -> None:
    """Attach a stdout StreamHandler so INFO logs appear in ECS/CloudWatch.

    Uvicorn's default config shows access lines but often does not surface
    application loggers (lifespan / Bedrock / chat). Handlers are idempotent
    across reload and create_app() calls.
    """
    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)

    for name in _APP_LOGGERS:
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        # One stdout handler per logger; skip if already attached.
        if not any(
            isinstance(h, logging.StreamHandler)
            and getattr(h, "stream", None) is sys.stdout
            for h in log.handlers
        ):
            log.addHandler(handler)
        # Do not rely on uvicorn's root logger configuration.
        log.propagate = False
