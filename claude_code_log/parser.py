#!/usr/bin/env python3
"""Parse and extract data from Claude transcript JSONL files.

This module provides utility functions for parsing transcript data:
- extract_text_content: Extract text from content items
- parse_timestamp: Parse ISO timestamps

For transcript entry and content item creation, see factories/.
"""

from datetime import datetime
from typing import Optional

from .models import ContentItem, ThinkingContent


def extract_text_content(content: Optional[list[ContentItem]]) -> str:
    """Extract text content from Claude message content structure.

    Supports both custom models (TextContent, ThinkingContent) and official
    Anthropic SDK types (TextBlock, ThinkingBlock).
    """
    if not content:
        return ""
    text_parts: list[str] = []
    for item in content:
        # Skip thinking content
        if (
            isinstance(item, ThinkingContent)
            or getattr(item, "type", None) == "thinking"
        ):
            continue
        # Handle text content
        if hasattr(item, "text"):
            text_parts.append(getattr(item, "text"))  # type: ignore[arg-type]
    return "\n".join(text_parts)


def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """Parse ISO timestamp to datetime object."""
    try:
        return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
