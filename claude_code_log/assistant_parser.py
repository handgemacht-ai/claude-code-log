"""Parser for assistant transcript entries.

This module handles parsing of AssistantTranscriptEntry content into MessageContent subclasses:
- AssistantTextMessage: Claude's text responses
- ThinkingMessage: Extended thinking blocks
"""

from typing import Optional

from .models import (
    AssistantTextMessage,
    ContentItem,
    ThinkingContent,
    ThinkingMessage,
)


# =============================================================================
# Message Parsing Functions
# =============================================================================


def parse_assistant_message_content(
    items: list[ContentItem],
) -> Optional[AssistantTextMessage]:
    """Parse assistant message content into AssistantTextMessage.

    Creates AssistantTextMessage from text/image content items.

    Args:
        items: List of text/image content items (no tool_use, tool_result, thinking).

    Returns:
        AssistantTextMessage if items is non-empty, None otherwise.
    """
    # Create AssistantTextMessage directly from items
    # (empty text already filtered by chunk_message_content)
    if items:
        return AssistantTextMessage(
            items=items  # type: ignore[arg-type]
        )
    return None


def parse_thinking_item(
    tool_item: ContentItem,
) -> ThinkingMessage:
    """Parse a thinking content item into ThinkingMessage.

    Args:
        tool_item: ThinkingContent or compatible object with 'thinking' attribute

    Returns:
        ThinkingMessage containing the thinking text and optional signature.
    """
    # Extract thinking text from the content item
    if isinstance(tool_item, ThinkingContent):
        thinking_text = tool_item.thinking.strip()
        signature = getattr(tool_item, "signature", None)
    else:
        thinking_text = getattr(tool_item, "thinking", str(tool_item)).strip()
        signature = None

    # Create the content model (formatting happens in HtmlRenderer)
    return ThinkingMessage(thinking=thinking_text, signature=signature)
