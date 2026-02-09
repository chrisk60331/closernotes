FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependency files first for better caching
COPY pyproject.toml README.md uv.lock ./

# Install dependencies
RUN uv sync --frozen

# Copy application code
COPY app/ ./app/

# Expose port
EXPOSE 5000

# Run with gunicorn for production (env-driven bind for App Runner parity)
CMD ["sh", "-c", "uv run gunicorn --bind ${FLASK_HOST:-0.0.0.0}:${PORT:-${FLASK_PORT:-5000}} --workers ${GUNICORN_WORKERS:-2} --timeout ${GUNICORN_TIMEOUT:-120} --access-logfile - --error-logfile - app.wsgi:app"]
