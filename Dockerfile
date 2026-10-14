# Agent HQ in a container: run the office on any free Linux VM (Oracle Cloud Always Free,
# Google Cloud e2-micro, a Raspberry Pi) so it keeps working when the Mac is off.
# Build:  docker build -t agent-hq .
# Run:    docker run -d --name agent-hq -p 8787:8787 --env-file .env \
#           -v agenthq-brain:/app/brain/data -v agenthq-workspace:/app/workspace -v agenthq-logs:/app/office/logs agent-hq
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt pywebpush python-multipart
COPY brain ./brain
COPY office ./office
COPY workspace/roadmap.md workspace/plan-90-days.md workspace/offer.md ./workspace/
COPY README.md .
# the venv path is baked into tools (PATH is set from sys.executable), so a symlink keeps scripts working
RUN ln -s /usr/local/bin /app/.venv 2>/dev/null || true
ENV OLLAMA_URL=http://host.docker.internal:11434/api/chat
EXPOSE 8787
HEALTHCHECK CMD curl -fs http://127.0.0.1:8787/api/state >/dev/null || exit 1
CMD ["python", "office/dashboard.py"]
