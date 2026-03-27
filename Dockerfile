FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY providers/ ./providers/

RUN pip install --no-cache-dir ./providers/codex-bridge-sdk \
    && pip install --no-cache-dir ".[serve]"

EXPOSE 8000

CMD ["hughie", "serve", "--host", "0.0.0.0", "--port", "8000"]
