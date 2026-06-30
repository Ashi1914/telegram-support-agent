"""Shared test utilities."""
from unittest.mock import MagicMock


def llm_resp(content: str):
    """Build a minimal mock that looks like a Groq chat-completion response."""
    msg    = MagicMock(); msg.content = content
    choice = MagicMock(); choice.message = msg
    resp   = MagicMock(); resp.choices = [choice]
    return resp
