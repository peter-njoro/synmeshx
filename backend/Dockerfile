FROM python:3.12-slim

ENV PATH="/root/.local/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y curl netcat-openbsd && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Use /app as the build/work directory so any created .venv has correct in-image paths
WORKDIR /app

# Copy minimal metadata first for dependency resolution, then the rest of the project.
COPY ./pyproject.toml /uv.lock* ./
COPY . .

# Create virtual environment inside /app (not copied from host) using uv
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

# Copy entrypoint into /app and make it executable
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["bash", "./entrypoint.sh"]
