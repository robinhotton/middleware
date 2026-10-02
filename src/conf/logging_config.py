"""Configuration du logging de l'application.

Ecrit toujours sur stdout (capturé par Docker).
Si LOG_DIR existe, ecrit aussi dans des fichiers rotatifs quotidiens :
    api.log          ← fichier actif du jour
    2026-02-20.log   ← archive du jour precedent
    2026-02-19.log   ← ...
    (30 jours conserves)

Consulter les logs :
    docker logs -f cours-api_25d12-25d18-api-1
    docker exec cours-api_25d12-25d18-api-1 ls /app/logs
    docker exec cours-api_25d12-25d18-api-1 cat /app/logs/api.log
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logging(level: str = "INFO", log_dir: str = "") -> None:
    """Configure le logger de l'application.

    - Stdout : toujours actif (Docker capture le flux)
    - Fichier : actif si log_dir existe et est accessible en ecriture
    """
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | pid=%(process)d | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    log_path = Path(log_dir) if log_dir else None
    if log_path and log_path.is_dir():
        file_handler = TimedRotatingFileHandler(
            filename=log_path / "api.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        # Renommage a la rotation : api.log.2026-02-20 → 2026-02-20.log
        file_handler.namer = lambda name: str(
            log_path / (name.rsplit(".", 1)[1] + ".log")
        )
        handlers.append(file_handler)

    app_logger = logging.getLogger("src")
    app_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in handlers:
        h.setFormatter(formatter)
        app_logger.addHandler(h)
    app_logger.propagate = False
