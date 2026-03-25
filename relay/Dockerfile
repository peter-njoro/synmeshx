FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY relay/ ./relay/

RUN pip install --no-cache-dir .

EXPOSE 8765

CMD ["uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8765"]
