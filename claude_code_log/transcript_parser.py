"""Parser for transcript entries and content items.

This module handles parsing of JSONL transcript data into typed models:
- TranscriptEntry subclasses (User, Assistant, Summary, System, QueueOperation)
- ContentItem subclasses (Text, ToolUse, ToolResult, Thinking, Image)

Also provides:
- Type guards for TranscriptEntry discrimination
- Usage info normalization for Anthropic SDK compatibility
"""

from typing import Any, Callable, Optional, cast

from .models import (
    # Content types
    ContentItem,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolResultContent,
    ToolUseContent,
    # Transcript entry types
    AssistantTranscriptEntry,
    MessageType,
    QueueOperationTranscriptEntry,
    SummaryTranscriptEntry,
    SystemTranscriptEntry,
    TranscriptEntry,
    UsageInfo,
    UserTranscriptEntry,
)


# =============================================================================
# Type Guards for TranscriptEntry
# =============================================================================


def as_user_entry(entry: TranscriptEntry) -> UserTranscriptEntry | None:
    """Return entry as UserTranscriptEntry if it is one, else None."""
    if entry.type == MessageType.USER:
        return cast(UserTranscriptEntry, entry)
    return None


def as_assistant_entry(entry: TranscriptEntry) -> AssistantTranscriptEntry | None:
    """Return entry as AssistantTranscriptEntry if it is one, else None."""
    if entry.type == MessageType.ASSISTANT:
        return cast(AssistantTranscriptEntry, entry)
    return None


# =============================================================================
# Usage Info Normalization
# =============================================================================


def normalize_usage_info(usage_data: Any) -> Optional[UsageInfo]:
    """Normalize usage data from various formats to UsageInfo."""
    if usage_data is None:
        return None

    # If it's already a UsageInfo instance, return as-is
    if isinstance(usage_data, UsageInfo):
        return usage_data

    # If it's a dict, validate and convert
    if isinstance(usage_data, dict):
        return UsageInfo.model_validate(usage_data)

    # Handle object-like access (e.g., from SDK types)
    if hasattr(usage_data, "input_tokens"):
        server_tool_use = getattr(usage_data, "server_tool_use", None)
        if server_tool_use is not None and hasattr(server_tool_use, "model_dump"):
            server_tool_use = server_tool_use.model_dump()
        return UsageInfo(
            input_tokens=getattr(usage_data, "input_tokens", None),
            output_tokens=getattr(usage_data, "output_tokens", None),
            cache_creation_input_tokens=getattr(
                usage_data, "cache_creation_input_tokens", None
            ),
            cache_read_input_tokens=getattr(
                usage_data, "cache_read_input_tokens", None
            ),
            service_tier=getattr(usage_data, "service_tier", None),
            server_tool_use=server_tool_use,
        )

    return None


# =============================================================================
# Content Item Parsing
# =============================================================================
# Functions to parse content items from JSONL data. Organized by entry type
# to clarify which content types can appear in which context.


def _parse_text_content(item_data: dict[str, Any]) -> ContentItem:
    """Parse text content.

    Common to both user and assistant messages.
    """
    return TextContent.model_validate(item_data)


def parse_user_content_item(item_data: dict[str, Any]) -> ContentItem:
    """Parse a content item from a UserTranscriptEntry.

    User messages can contain:
    - text: User-typed text
    - tool_result: Results from tool execution
    - image: User-attached images
    """
    try:
        content_type = item_data.get("type", "")

        if content_type == "text":
            return _parse_text_content(item_data)
        elif content_type == "tool_result":
            return ToolResultContent.model_validate(item_data)
        elif content_type == "image":
            return ImageContent.model_validate(item_data)
        else:
            # Fallback to text content for unknown types
            return TextContent(type="text", text=str(item_data))
    except Exception:
        return TextContent(type="text", text=str(item_data))


def parse_assistant_content_item(item_data: dict[str, Any]) -> ContentItem:
    """Parse a content item from an AssistantTranscriptEntry.

    Assistant messages can contain:
    - text: Assistant's response text
    - tool_use: Tool invocations
    - thinking: Extended thinking blocks
    """
    try:
        content_type = item_data.get("type", "")

        if content_type == "text":
            return _parse_text_content(item_data)
        elif content_type == "tool_use":
            return ToolUseContent.model_validate(item_data)
        elif content_type == "thinking":
            return ThinkingContent.model_validate(item_data)
        else:
            # Fallback to text content for unknown types
            return TextContent(type="text", text=str(item_data))
    except Exception:
        return TextContent(type="text", text=str(item_data))


def parse_content_item(item_data: dict[str, Any]) -> ContentItem:
    """Parse a content item (generic fallback).

    For cases where the entry type is unknown. Handles all content types.
    Prefer parse_user_content_item or parse_assistant_content_item when
    the entry type is known.
    """
    try:
        content_type = item_data.get("type", "")

        if content_type == "tool_result":
            return ToolResultContent.model_validate(item_data)
        elif content_type == "image":
            return ImageContent.model_validate(item_data)
        elif content_type == "tool_use":
            return ToolUseContent.model_validate(item_data)
        elif content_type == "thinking":
            return ThinkingContent.model_validate(item_data)
        elif content_type == "text":
            return _parse_text_content(item_data)
        else:
            # Fallback to text content for unknown types
            return TextContent(type="text", text=str(item_data))
    except Exception:
        return TextContent(type="text", text=str(item_data))


def parse_message_content(
    content_data: Any,
    item_parser: Callable[[dict[str, Any]], ContentItem] = parse_content_item,
) -> list[ContentItem]:
    """Parse message content, normalizing to a list of ContentItems.

    Always returns a list for consistent downstream handling. String content
    is wrapped in a TextContent item.

    Args:
        content_data: Raw content data (string or list of items)
        item_parser: Function to parse individual content items. Defaults to
            generic parse_content_item, but can be parse_user_content_item or
            parse_assistant_content_item for type-specific parsing.
    """
    if isinstance(content_data, str):
        return [TextContent(type="text", text=content_data)]
    elif isinstance(content_data, list):
        content_list = cast(list[Any], content_data)
        result: list[ContentItem] = []
        for item in content_list:
            if isinstance(item, dict):
                result.append(item_parser(cast(dict[str, Any], item)))
            else:
                # Non-dict items (e.g., raw strings) become TextContent
                result.append(TextContent(type="text", text=str(item)))
        return result
    else:
        return [TextContent(type="text", text=str(content_data))]


# =============================================================================
# Transcript Entry Parsing
# =============================================================================


def parse_transcript_entry(data: dict[str, Any]) -> TranscriptEntry:
    """
    Parse a JSON dictionary into the appropriate TranscriptEntry type.

    Enhanced to optionally use official Anthropic types for assistant messages.

    Args:
        data: Dictionary parsed from JSON

    Returns:
        The appropriate TranscriptEntry subclass

    Raises:
        ValueError: If the data doesn't match any known transcript entry type
    """
    entry_type = data.get("type")

    if entry_type == "user":
        # Parse message content if present, using user-specific parser
        data_copy = data.copy()
        if "message" in data_copy and "content" in data_copy["message"]:
            data_copy["message"] = data_copy["message"].copy()
            data_copy["message"]["content"] = parse_message_content(
                data_copy["message"]["content"],
                item_parser=parse_user_content_item,
            )
        # Parse toolUseResult if present and it's a list of content items
        if "toolUseResult" in data_copy and isinstance(
            data_copy["toolUseResult"], list
        ):
            # Check if it's a list of content items (MCP tool results)
            tool_use_result = cast(list[Any], data_copy["toolUseResult"])
            if (
                tool_use_result
                and isinstance(tool_use_result[0], dict)
                and "type" in tool_use_result[0]
            ):
                data_copy["toolUseResult"] = [
                    parse_content_item(cast(dict[str, Any], item))
                    for item in tool_use_result
                    if isinstance(item, dict)
                ]
        return UserTranscriptEntry.model_validate(data_copy)

    elif entry_type == "assistant":
        data_copy = data.copy()

        # Parse assistant message content
        if "message" in data_copy and "content" in data_copy["message"]:
            message_copy = data_copy["message"].copy()
            message_copy["content"] = parse_message_content(
                message_copy["content"],
                item_parser=parse_assistant_content_item,
            )

            # Normalize usage data to support both Anthropic and custom formats
            if "usage" in message_copy:
                message_copy["usage"] = normalize_usage_info(message_copy["usage"])

            data_copy["message"] = message_copy
        return AssistantTranscriptEntry.model_validate(data_copy)

    elif entry_type == "summary":
        return SummaryTranscriptEntry.model_validate(data)

    elif entry_type == "system":
        return SystemTranscriptEntry.model_validate(data)

    elif entry_type == "queue-operation":
        # Parse content if present (in enqueue and remove operations)
        data_copy = data.copy()
        if "content" in data_copy and isinstance(data_copy["content"], list):
            data_copy["content"] = parse_message_content(data_copy["content"])
        return QueueOperationTranscriptEntry.model_validate(data_copy)

    else:
        raise ValueError(f"Unknown transcript entry type: {entry_type}")
