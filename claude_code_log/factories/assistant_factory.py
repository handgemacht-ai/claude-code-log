"""Factory for assistant transcript entries.

This module handles creation of AssistantTranscriptEntry content into MessageContent
subclasses:
- AssistantTextMessage: Claude's text responses
- ThinkingMessage: Extended thinking blocks
"""

from typing import Optional

from ..models import (
    AssistantTextMessage,
    ContentItem,
    MessageMeta,
    ThinkingContent,
    ThinkingMessage,
)


# =============================================================================
# Message Creation Functions
# =============================================================================


def create_assistant_message(
    items: list[ContentItem],
    meta: Optional[MessageMeta] = None,
) -> Optional[AssistantTextMessage]:
    """Create AssistantTextMessage from content items.

    Creates AssistantTextMessage from text/image content items.

    Args:
        items: List of text/image content items (no tool_use, tool_result, thinking).
        meta: Optional message metadata.

    Returns:
        AssistantTextMessage if items is non-empty, None otherwise.
    """
    # Create AssistantTextMessage directly from items
    # (empty text already filtered by chunk_message_content)
    if items:
        return AssistantTextMessage(
            items=items,  # type: ignore[arg-type]
            meta=meta,
        )
    return None


def create_thinking_message(
    tool_item: ContentItem,
    meta: Optional[MessageMeta] = None,
) -> ThinkingMessage:
    """Create ThinkingMessage from a thinking content item.

    Args:
        tool_item: ThinkingContent or compatible object with 'thinking' attribute
        meta: Optional message metadata.

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
    return ThinkingMessage(thinking=thinking_text, signature=signature, meta=meta)
