FROM python:3.11-slim

# Dev (pytest, ruff) stays the default for `make dev`; the cloud compose file turns it off.
ARG INSTALL_DEV=true
ARG INSTALL_S3=false

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
RUN EXTRAS=""; \
    if [ "$INSTALL_DEV" = "true" ]; then EXTRAS="dev"; fi; \
    if [ "$INSTALL_S3" = "true" ]; then EXTRAS="${EXTRAS:+$EXTRAS,}s3"; fi; \
    pip install --no-cache-dir -e ".${EXTRAS:+[$EXTRAS]}"
COPY . .

# Run as a non-root user; /data/snapshots is the writable directory for STORAGE_BACKEND=local.
RUN useradd --system --uid 10001 --no-create-home rada \
    && mkdir -p /data/snapshots \
    && chown -R rada /data /app
USER rada

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
