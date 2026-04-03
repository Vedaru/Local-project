from __future__ import annotations

from typing import Callable, Optional

from app.tool import BaseTool

_ask_human_voice_callback: Optional[Callable[[str], None]] = None


def set_ask_human_voice_callback(callback: Optional[Callable[[str], None]]) -> None:
    """Register a callback used to speak ask_human prompts in local app."""
    global _ask_human_voice_callback
    _ask_human_voice_callback = callback


def _emit_voice_prompt(prompt: str) -> None:
    if _ask_human_voice_callback is None:
        return
    try:
        _ask_human_voice_callback(prompt)
    except Exception:
        # Voice callback failures should not break ask_human interaction.
        pass


class AskHuman(BaseTool):
    """Add a tool to ask human for help."""

    name: str = "ask_human"
    description: str = "Use this tool to ask human for help."
    parameters: str = {
        "type": "object",
        "properties": {
            "inquire": {
                "type": "string",
                "description": "The question you want to ask human.",
            }
        },
        "required": ["inquire"],
    }

    async def execute(self, inquire: str) -> str:
        prompt = (inquire or "").strip()
        if prompt:
            _emit_voice_prompt(prompt)
        return input(f"""Bot: {prompt}\n\nYou: """).strip()
