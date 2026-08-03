# Imagen del runtime multi-agente (Python). Una sola imagen sirve a TODOS
# los agentes — la config/prompts/vector stores se cargan desde S3 en runtime.
#
# Build:    docker build -t westfield-agent-back-python:latest .
# Run:      docker run -p 8000:8000 --env-file .env westfield-agent-back-python:latest
# Health:   curl http://localhost:8000/api/v1/health
#
# Env requerido en runtime: S3_BUCKET, AWS_REGION, S3_PREFIX, credenciales
# AWS (o rol IAM) y OPENAI_API_KEY. Ver .env.example.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# curl: para el healthcheck del compose. build-essential: por si numpy
# necesita compilar wheels en arquitecturas raras (slim base).
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# Cache layer: si pyproject.toml/poetry.lock no cambian, no reinstala deps.
COPY pyproject.toml poetry.lock* /app/
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Código + instalación del paquete (src layout → necesita el install del root).
COPY . /app
RUN poetry install --no-interaction --no-ansi --only main

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "westfield_agent_back_python.main_api"]
