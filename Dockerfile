FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home appuser

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser helpers ./helpers

USER appuser

EXPOSE 8000

ENTRYPOINT ["python", "helpers/api_server.py"]
