"""Configuration Gunicorn pour la production."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", 4))
worker_class = "uvicorn.workers.UvicornWorker"
worker_tmp_dir = "/tmp"
pidfile = "/tmp/gunicorn.pid"
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
