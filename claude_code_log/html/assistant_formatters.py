"""HTML formatters for assistant message content.

This module formats assistant message content types to HTML.
Part of the thematic formatter organization:
- system_formatters.py: SystemContent, HookSummaryContent
- user_formatters.py: SlashCommandContent, CommandOutputContent, BashInputContent
- assistant_formatters.py: AssistantTextContent, ThinkingContent
- tool_formatters.py: tool use/result content
"""

from dataclasses import dataclass
from typing import Optional

from ..models import MessageContent
from .utils import render_markdown_collapsible


# =============================================================================
# Assistant Message Content Models
# =============================================================================


@dataclass
class AssistantTextContent(MessageContent):
    """Content for assistant text messages.

    These are the text portions of assistant messages that get
    rendered as markdown with syntax highlighting.
    """

    text: str


@dataclass
class ThinkingContentModel(MessageContent):
    """Content for assistant thinking/reasoning blocks.

    These are the <thinking> blocks that show the assistant's
    internal reasoning process.
    """

    thinking: str
    signature: Optional[str] = None


# =============================================================================
# Formatting Functions
# =============================================================================


def format_assistant_text_content(
    content: AssistantTextContent,
    line_threshold: int = 30,
    preview_line_count: int = 10,
) -> str:
    """Format assistant text content as HTML.

    Args:
        content: AssistantTextContent with the text to render
        line_threshold: Number of lines before content becomes collapsible
        preview_line_count: Number of preview lines to show when collapsed

    Returns:
        HTML string with markdown-rendered, optionally collapsible content
    """
    return render_markdown_collapsible(
        content.text,
        "assistant-text",
        line_threshold=line_threshold,
        preview_line_count=preview_line_count,
    )


def format_thinking_content(
    content: ThinkingContentModel,
    line_threshold: int = 20,
    preview_line_count: int = 5,
) -> str:
    """Format thinking content as HTML.

    Args:
        content: ThinkingContentModel with the thinking text
        line_threshold: Number of lines before content becomes collapsible
        preview_line_count: Number of preview lines to show when collapsed

    Returns:
        HTML string with markdown-rendered, optionally collapsible thinking content
    """
    return render_markdown_collapsible(
        content.thinking,
        "thinking-content",
        line_threshold=line_threshold,
        preview_line_count=preview_line_count,
    )


# =============================================================================
# Public Exports
# =============================================================================

__all__ = [
    # Content models
    "AssistantTextContent",
    "ThinkingContentModel",
    # Formatting functions
    "format_assistant_text_content",
    "format_thinking_content",
]
