"""Factory modules for creating typed objects from raw data."""

from .system_factory import (
    # System message detection
    is_system_message,
    # System message creation
    create_system_message,
)
from .transcript_factory import (
    # Content type constants
    ASSISTANT_CONTENT_TYPES,
    USER_CONTENT_TYPES,
    # Conditional casts
    as_assistant_entry,
    as_user_entry,
    # Usage normalization
    normalize_usage_info,
    # Content item creation
    create_content_item,
    create_message_content,
    # Transcript entry creation
    create_transcript_entry,
)

__all__ = [
    # Content type constants
    "USER_CONTENT_TYPES",
    "ASSISTANT_CONTENT_TYPES",
    # Conditional casts
    "as_user_entry",
    "as_assistant_entry",
    # Usage normalization
    "normalize_usage_info",
    # Content item creation
    "create_content_item",
    "create_message_content",
    # Transcript entry creation
    "create_transcript_entry",
    # System message detection
    "is_system_message",
    # System message creation
    "create_system_message",
]
