#!/usr/bin/env python3
"""Parse and extract data from Claude transcript JSONL files.

This module provides utility functions for parsing transcript data:
- parse_meta: Extract common metadata from transcript entries
- extract_text_content: Extract text from content items
- parse_timestamp: Parse ISO timestamps

For transcript entry and content item parsing, see transcript_parser.py.
"""

from datetime import datetime
from typing import Optional

from .models import (
    # Common metadata
    BaseTranscriptEntry,
    MessageMeta,
    # Content types
    ContentItem,
    ThinkingContent,
)


def parse_meta(transcript: BaseTranscriptEntry) -> MessageMeta:
    """Extract common metadata from a transcript entry.

    This function extracts the shared fields that are present in all
    BaseTranscriptEntry subclasses.

    Note: formatted_timestamp is computed at render time, not here.

    Args:
        transcript: Any transcript entry inheriting from BaseTranscriptEntry

    Returns:
        MessageMeta with session_id, timestamp, uuid, and parent_uuid
    """
    return MessageMeta(
        session_id=transcript.sessionId,
        timestamp=transcript.timestamp,
        uuid=transcript.uuid,
        parent_uuid=transcript.parentUuid,
    )


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
