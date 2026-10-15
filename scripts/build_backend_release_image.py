from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / ".tmp" / "backend-release-context"
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "novel_backend:release-20261015"

if CONTEXT.exists():
    shutil.rmtree(CONTEXT)
CONTEXT.mkdir(parents=True)

for name in ("backend", "core", "schemas", "adapters", "agents", "pipeline", "config", "shared", "scripts"):
    source = ROOT / name
    if source.exists():
        shutil.copytree(source, CONTEXT / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

for relative in (
    "backend/data", "backend/logs", "backend/runs", "backend/tests",
    "backend/chroma_db_runtime_20260428", "backend/chroma_db_runtime_20260428_runtime_fallback",
    "scripts/test_fixtures",
):
    path = CONTEXT / relative
    if path.exists():
        shutil.rmtree(path)

dockerfile = """FROM python:3.11-slim
WORKDIR /app/backend
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \\
    PIP_TRUSTED_HOST=mirrors.aliyun.com \\
    PIP_DEFAULT_TIMEOUT=120 \\
    PYTHONPATH=/app:/app/backend
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \\
    && apt-get update && apt-get install -y gcc ffmpeg postgresql-client \\
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --retries 5 -r /tmp/requirements.txt
COPY backend /app/backend
COPY core /app/core
COPY schemas /app/schemas
COPY adapters /app/adapters
COPY agents /app/agents
COPY pipeline /app/pipeline
COPY config /config
COPY shared /app/shared
COPY scripts /scripts
EXPOSE 8000
CMD ["uvicorn", "app.main:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
"""
(CONTEXT / "Dockerfile").write_text(dockerfile, encoding="ascii", newline="\n")
subprocess.run(["docker", "build", "-t", IMAGE, str(CONTEXT)], check=True)
