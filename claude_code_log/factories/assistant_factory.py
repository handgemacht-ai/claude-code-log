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
    TextContent,
    ThinkingContent,
    ThinkingMessage,
)


# =============================================================================
# Message Creation Functions
# =============================================================================


def create_assistant_message(
    meta: MessageMeta,
    items: list[ContentItem],
) -> Optional[AssistantTextMessage]:
    """Create AssistantTextMessage from content items.

    Creates AssistantTextMessage from text/image content items.

    Args:
        meta: Message metadata.
        items: List of text/image content items (no tool_use, tool_result, thinking).

    Returns:
        AssistantTextMessage if items is non-empty, None otherwise.
    """
    # Create AssistantTextMessage directly from items
    # (empty text already filtered by chunk_message_content)
    if items:
        # Extract text content from items for dedup matching and simple renderers
        text_content = "\n".join(
            item.text for item in items if isinstance(item, TextContent)
        )
        return AssistantTextMessage(
            meta,
            items=items,  # type: ignore[arg-type]
            raw_text_content=text_content if text_content else None,
        )
    return None


def create_thinking_message(
    meta: MessageMeta,
    tool_item: ContentItem,
) -> ThinkingMessage:
    """Create ThinkingMessage from a thinking content item.

    Args:
        meta: Message metadata.
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
    return ThinkingMessage(meta, thinking=thinking_text, signature=signature)
