"""Vercel Python Runtime エントリポイント（全ルートをFastAPIへ委譲）。"""
from src.web.app import app  # noqa: F401
