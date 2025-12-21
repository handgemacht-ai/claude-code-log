"""Parser for assistant transcript entries.

This module handles parsing of AssistantTranscriptEntry content into MessageContent subclasses:
- AssistantTextMessage: Claude's text responses
- ThinkingMessage: Extended thinking blocks
"""

from typing import Optional

from .models import (
    AssistantTextMessage,
    ContentItem,
    MessageContent,
    ThinkingContent,
    ThinkingMessage,
)


# =============================================================================
# Message Processing Functions
# =============================================================================


def process_assistant_message(
    items: list[ContentItem],
    is_sidechain: bool,
) -> tuple[bool, Optional[MessageContent], str, str]:
    """Process assistant message and return (is_sidechain, content_model, message_type, message_title).

    Creates AssistantTextMessage from text/image content items.

    Args:
        items: List of text/image content items (no tool_use, tool_result, thinking).
        is_sidechain: Whether this is a sidechain message.

    Returns:
        Tuple of (is_sidechain, content_model, message_type, message_title)
    """
    message_title = "Assistant"
    message_type = "assistant"
    content_model: Optional[MessageContent] = None

    # Create AssistantTextMessage directly from items
    # (empty text already filtered by chunk_message_content)
    if items:
        content_model = AssistantTextMessage(
            items=items  # type: ignore[arg-type]
        )

    if is_sidechain:
        message_title = "Sub-assistant"

    return is_sidechain, content_model, message_type, message_title


def process_thinking_item(
    tool_item: ContentItem,
) -> tuple[str, str, Optional[MessageContent]]:
    """Process a thinking content item.

    Args:
        tool_item: ThinkingContent or compatible object with 'thinking' attribute

    Returns:
        Tuple of (message_type, message_title, content_model)
    """
    # Extract thinking text from the content item
    if isinstance(tool_item, ThinkingContent):
        thinking_text = tool_item.thinking.strip()
        signature = getattr(tool_item, "signature", None)
    else:
        thinking_text = getattr(tool_item, "thinking", str(tool_item)).strip()
        signature = None

    # Create the content model (formatting happens in HtmlRenderer)
    thinking_model = ThinkingMessage(thinking=thinking_text, signature=signature)

    return "thinking", "Thinking", thinking_model
