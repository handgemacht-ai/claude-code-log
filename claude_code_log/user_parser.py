"""Parser for user transcript entries.

This module handles parsing of UserTranscriptEntry content into MessageContent subclasses:
- SlashCommandMessage: Slash command invocations
- CommandOutputMessage: Local command output
- BashInputMessage: Bash command input
- BashOutputMessage: Bash command output
- UserTextMessage: Regular user text (with optional IDE notifications)
- UserSlashCommandMessage: Expanded slash command prompts (isMeta)
- CompactedSummaryMessage: Compacted conversation summaries
- UserMemoryMessage: User memory content
- UserSteeringMessage: User steering prompts (queue-operation 'remove')
"""

from typing import Optional

from .models import (
    CompactedSummaryMessage,
    ContentItem,
    MessageContent,
    UserMemoryMessage,
    UserSlashCommandMessage,
)
from .parser import (
    parse_bash_input,
    parse_bash_output,
    parse_command_output,
    parse_slash_command,
    parse_user_message_content,
)


# =============================================================================
# Message Type Detection
# =============================================================================


def is_command_message(text_content: str) -> bool:
    """Check if a message contains command information that should be displayed."""
    return "<command-name>" in text_content and "<command-message>" in text_content


def is_local_command_output(text_content: str) -> bool:
    """Check if a message contains local command output."""
    return "<local-command-stdout>" in text_content


def is_bash_input(text_content: str) -> bool:
    """Check if a message contains bash input command."""
    return "<bash-input>" in text_content and "</bash-input>" in text_content


def is_bash_output(text_content: str) -> bool:
    """Check if a message contains bash command output."""
    return "<bash-stdout>" in text_content or "<bash-stderr>" in text_content


# =============================================================================
# Message Processing Functions
# =============================================================================


def process_command_message(
    text_content: str,
) -> tuple[Optional[MessageContent], str, str]:
    """Process a slash command message and return (content, message_type, message_title).

    These are user messages containing slash command invocations (e.g., /context, /model).
    The JSONL type is "user", not "system".
    """
    # Parse to content model (formatting happens in HtmlRenderer)
    content = parse_slash_command(text_content)
    # If parsing fails, content will be None and caller will handle fallback

    return content, "user", "Slash Command"


def process_local_command_output(
    text_content: str,
) -> tuple[Optional[MessageContent], str, str]:
    """Process slash command output and return (content, message_type, message_title).

    These are user messages containing the output from slash commands (e.g., /context, /model).
    The JSONL type is "user", not "system".
    """
    # Parse to content model (formatting happens in HtmlRenderer)
    content = parse_command_output(text_content)
    # If parsing fails, content will be None and caller will handle fallback

    return content, "user", ""


def process_bash_input(
    text_content: str,
) -> tuple[Optional[MessageContent], str, str]:
    """Process bash input command and return (content, message_type, message_title)."""
    # Parse to content model (formatting happens in HtmlRenderer)
    content = parse_bash_input(text_content)
    # If parsing fails, content will be None and caller will handle fallback

    return content, "bash-input", "Bash command"


def process_bash_output(
    text_content: str,
) -> tuple[Optional[MessageContent], str, str]:
    """Process bash output and return (content, message_type, message_title)."""
    # Parse to content model (formatting happens in HtmlRenderer)
    content = parse_bash_output(text_content)
    # If parsing fails, content will be None - caller/renderer handles empty output

    return content, "bash-output", ""


def process_user_message(
    items: list[ContentItem],
    is_sidechain: bool,
    is_meta: bool = False,
) -> tuple[bool, Optional[MessageContent], str, str]:
    """Process user message and return (is_sidechain, content_model, message_type, message_title).

    Handles user-specific content types:
    - UserSlashCommandMessage (from isMeta=True)
    - CompactedSummaryMessage
    - UserMemoryMessage
    - Regular UserTextMessage

    Note: Sidechain user messages (Sub-assistant prompts) are skipped earlier
    in the main processing loop since they duplicate the Task tool input prompt.

    Args:
        items: List of text/image content items (no tool_use, tool_result, thinking).
        is_sidechain: Whether this is a sidechain message.
        is_meta: True for slash command expanded prompts (isMeta=True in JSONL)

    Returns:
        Tuple of (is_sidechain, content_model, message_type, message_title)
    """
    message_title = "User"  # Default title
    message_type = "user"

    # Parse user content (is_meta triggers UserSlashCommandMessage creation)
    content_model = parse_user_message_content(items, is_slash_command=is_meta)

    # Determine message_title from content type
    if isinstance(content_model, UserSlashCommandMessage):
        message_title = "User (slash command)"
    elif isinstance(content_model, CompactedSummaryMessage):
        message_title = "User (compacted conversation)"
    elif isinstance(content_model, UserMemoryMessage):
        message_title = "Memory"

    return is_sidechain, content_model, message_type, message_title
