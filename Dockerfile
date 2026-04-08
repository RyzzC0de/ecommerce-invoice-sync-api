# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — builder: installs Python deps into an isolated prefix
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# System packages needed to compile some Python deps (e.g. asyncpg C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a dedicated prefix so the runtime stage can COPY just that dir
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime: lean image with only what's needed to run the app
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Put the installed packages on the Python path
    PYTHONPATH=/install/lib/python3.11/site-packages

WORKDIR /app

# ── WeasyPrint system dependencies (GTK / Cairo / Pango / fonts) ─────────────
# These are required for the primary PDF engine. WeasyPrint falls back to
# ReportLab automatically if these libs are missing (e.g. on Windows), but in
# the Docker image we install them so WeasyPrint is always used.
RUN apt-get update && apt-get install -y --no-install-recommends \
        # Pango / Cairo / GDK (WeasyPrint rendering stack)
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        libglib2.0-0 \
        # Font support
        fonts-liberation \
        fonts-dejavu-core \
        fontconfig \
        # SSL / networking
        ca-certificates \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source (exclude venv, __pycache__, .env via .dockerignore)
COPY app/          ./app/
COPY alembic/      ./alembic/
COPY alembic.ini   .
COPY start.sh      .

# ── Security: run as non-root ─────────────────────────────────────────────────
RUN addgroup --system appgroup \
 && adduser  --system --ingroup appgroup --no-create-home appuser \
 && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

ENTRYPOINT ["sh", "start.sh"]
