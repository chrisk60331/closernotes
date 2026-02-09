"""WSGI entrypoint for Gunicorn/App Runner."""

from app.main import create_app

app = create_app()
