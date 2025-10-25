FROM python:3.12-slim

ENV PATH="/root/.local/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y curl netcat-openbsd && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

COPY ./pyproject.toml /uv.lock* ./
COPY . .
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["bash", "./entrypoint.sh"]
