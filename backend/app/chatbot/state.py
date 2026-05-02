from __future__ import annotations

from typing import Any, Literal, TypedDict


ChatDecision = Literal[
    "conversation_guard",
    "general",
    "scope_guard",
    "local_grounded",
    "local_curated",
    "model_grounded",
]


class ChatbotState(TypedDict, total=False):
    query: str
    history: list[dict[str, str]]
    context: dict[str, Any]
    source_lookup: dict[str, dict[str, Any]]
    decision: ChatDecision
    raw_response: dict[str, Any]
    used_model: str
    response: dict[str, Any]

