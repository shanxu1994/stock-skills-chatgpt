"""Deployment entrypoint that adds fetcher-friendly public routes."""

from .asgi import app
from .chatgpt_bridge import register_chatgpt_bridge

register_chatgpt_bridge(app)
