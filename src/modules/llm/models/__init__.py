"""Schemas Pydantic du domaine LLM."""

from .chat_session import ChatSession, ChatTurn
from .log import LLMLog
from .schemas import (
    LearnerAnalysis,
    LLMLogRead,
    LLMStatsResponse,
    MoodleChatRequest,
    MoodleChatResponse,
    PlatformSettingsResponse,
    PromptTemplateRead,
)

__all__ = [
    "ChatSession",
    "ChatTurn",
    "LLMLog",
    "LLMLogRead",
    "LLMStatsResponse",
    "LearnerAnalysis",
    "MoodleChatRequest",
    "MoodleChatResponse",
    "PlatformSettingsResponse",
    "PromptTemplateRead",
]
