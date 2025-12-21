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

import json
import re
from typing import Any, Optional, Union, cast

from .models import (
    BashInputMessage,
    BashOutputMessage,
    CommandOutputMessage,
    CompactedSummaryMessage,
    ContentItem,
    IdeDiagnostic,
    IdeNotificationContent,
    IdeOpenedFile,
    IdeSelection,
    ImageContent,
    SlashCommandMessage,
    TextContent,
    UserMemoryMessage,
    UserSlashCommandMessage,
    UserTextMessage,
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
# Slash Command Parsing
# =============================================================================


def parse_slash_command(text: str) -> Optional[SlashCommandMessage]:
    """Parse slash command tags from text.

    Args:
        text: Raw text that may contain command-name, command-args, command-contents tags

    Returns:
        SlashCommandMessage if tags found, None otherwise
    """
    command_name_match = re.search(r"<command-name>([^<]+)</command-name>", text)
    if not command_name_match:
        return None

    command_name = command_name_match.group(1).strip()

    command_args_match = re.search(r"<command-args>([^<]*)</command-args>", text)
    command_args = command_args_match.group(1).strip() if command_args_match else ""

    # Parse command contents, handling JSON format
    command_contents_match = re.search(
        r"<command-contents>(.+?)</command-contents>", text, re.DOTALL
    )
    command_contents = ""
    if command_contents_match:
        contents_text = command_contents_match.group(1).strip()
        # Try to parse as JSON and extract the text field
        try:
            contents_json: Any = json.loads(contents_text)
            if isinstance(contents_json, dict) and "text" in contents_json:
                text_dict = cast(dict[str, Any], contents_json)
                text_value = text_dict["text"]
                command_contents = str(text_value)
            else:
                command_contents = contents_text
        except json.JSONDecodeError:
            command_contents = contents_text

    return SlashCommandMessage(
        command_name=command_name,
        command_args=command_args,
        command_contents=command_contents,
    )


def parse_command_output(text: str) -> Optional[CommandOutputMessage]:
    """Parse command output tags from text.

    Args:
        text: Raw text that may contain local-command-stdout tags

    Returns:
        CommandOutputMessage if tags found, None otherwise
    """
    stdout_match = re.search(
        r"<local-command-stdout>(.*?)</local-command-stdout>",
        text,
        re.DOTALL,
    )
    if not stdout_match:
        return None

    stdout_content = stdout_match.group(1).strip()
    # Check if content looks like markdown (starts with markdown headers)
    is_markdown = bool(re.match(r"^#+\s+", stdout_content, re.MULTILINE))

    return CommandOutputMessage(stdout=stdout_content, is_markdown=is_markdown)


# =============================================================================
# Bash Input/Output Parsing
# =============================================================================


def parse_bash_input(text: str) -> Optional[BashInputMessage]:
    """Parse bash input tags from text.

    Args:
        text: Raw text that may contain bash-input tags

    Returns:
        BashInputMessage if tags found, None otherwise
    """
    bash_match = re.search(r"<bash-input>(.*?)</bash-input>", text, re.DOTALL)
    if not bash_match:
        return None

    return BashInputMessage(command=bash_match.group(1).strip())


def parse_bash_output(text: str) -> Optional[BashOutputMessage]:
    """Parse bash output tags from text.

    Args:
        text: Raw text that may contain bash-stdout/bash-stderr tags

    Returns:
        BashOutputMessage if tags found, None otherwise
    """
    stdout_match = re.search(r"<bash-stdout>(.*?)</bash-stdout>", text, re.DOTALL)
    stderr_match = re.search(r"<bash-stderr>(.*?)</bash-stderr>", text, re.DOTALL)

    if not stdout_match and not stderr_match:
        return None

    stdout = stdout_match.group(1).strip() if stdout_match else None
    stderr = stderr_match.group(1).strip() if stderr_match else None

    # Convert empty strings to None for cleaner representation
    if stdout == "":
        stdout = None
    if stderr == "":
        stderr = None

    return BashOutputMessage(stdout=stdout, stderr=stderr)


# =============================================================================
# IDE Notification Parsing
# =============================================================================

# Shared regex patterns for IDE notification tags
IDE_OPENED_FILE_PATTERN = re.compile(
    r"<ide_opened_file>(.*?)</ide_opened_file>", re.DOTALL
)
IDE_SELECTION_PATTERN = re.compile(r"<ide_selection>(.*?)</ide_selection>", re.DOTALL)
IDE_DIAGNOSTICS_PATTERN = re.compile(
    r"<post-tool-use-hook>\s*<ide_diagnostics>(.*?)</ide_diagnostics>\s*</post-tool-use-hook>",
    re.DOTALL,
)


def parse_ide_notifications(text: str) -> Optional[IdeNotificationContent]:
    """Parse IDE notification tags from text.

    Handles:
    - <ide_opened_file>: Simple file open notifications
    - <ide_selection>: Code selection notifications
    - <post-tool-use-hook><ide_diagnostics>: JSON diagnostic arrays

    Args:
        text: Raw text that may contain IDE notification tags

    Returns:
        IdeNotificationContent if any tags found, None otherwise
    """
    opened_files: list[IdeOpenedFile] = []
    selections: list[IdeSelection] = []
    diagnostics: list[IdeDiagnostic] = []
    remaining_text = text

    # Pattern 1: <ide_opened_file>content</ide_opened_file>
    for match in IDE_OPENED_FILE_PATTERN.finditer(remaining_text):
        content = match.group(1).strip()
        opened_files.append(IdeOpenedFile(content=content))

    remaining_text = IDE_OPENED_FILE_PATTERN.sub("", remaining_text)

    # Pattern 2: <ide_selection>content</ide_selection>
    for match in IDE_SELECTION_PATTERN.finditer(remaining_text):
        content = match.group(1).strip()
        selections.append(IdeSelection(content=content))

    remaining_text = IDE_SELECTION_PATTERN.sub("", remaining_text)

    # Pattern 3: <post-tool-use-hook><ide_diagnostics>JSON</ide_diagnostics></post-tool-use-hook>
    for match in IDE_DIAGNOSTICS_PATTERN.finditer(remaining_text):
        json_content = match.group(1).strip()
        try:
            parsed_diagnostics: Any = json.loads(json_content)
            if isinstance(parsed_diagnostics, list):
                diagnostics.append(
                    IdeDiagnostic(
                        diagnostics=cast(list[dict[str, Any]], parsed_diagnostics)
                    )
                )
            else:
                # Not a list, store as raw content
                diagnostics.append(IdeDiagnostic(raw_content=json_content))
        except (json.JSONDecodeError, ValueError):
            # JSON parsing failed, store raw content
            diagnostics.append(IdeDiagnostic(raw_content=json_content))

    remaining_text = IDE_DIAGNOSTICS_PATTERN.sub("", remaining_text)

    # Only return if we found any IDE tags
    if not opened_files and not selections and not diagnostics:
        return None

    return IdeNotificationContent(
        opened_files=opened_files,
        selections=selections,
        diagnostics=diagnostics,
        remaining_text=remaining_text.strip(),
    )


# =============================================================================
# Compacted Summary and User Memory Parsing
# =============================================================================

# Pattern for compacted session summary detection
COMPACTED_SUMMARY_PREFIX = "This session is being continued from a previous conversation that ran out of context"


def parse_compacted_summary(
    content_list: list[ContentItem],
) -> Optional[CompactedSummaryMessage]:
    """Parse compacted session summary from content list.

    Compacted summaries are generated when a session runs out of context and
    needs to be continued. They contain a summary of the previous conversation.

    If the first text item starts with the compacted summary prefix, all text
    items are combined into a single CompactedSummaryMessage.

    Args:
        content_list: List of ContentItem from user message

    Returns:
        CompactedSummaryMessage if first text is a compacted summary, None otherwise
    """
    if not content_list or not hasattr(content_list[0], "text"):
        return None

    first_text = getattr(content_list[0], "text", "")
    if not first_text.startswith(COMPACTED_SUMMARY_PREFIX):
        return None

    # Combine all text content for compacted summaries
    # Use hasattr check to handle both TextContent models and SDK TextBlock objects
    texts = cast(
        list[str],
        [item.text for item in content_list if hasattr(item, "text")],  # type: ignore[union-attr]
    )
    all_text = "\n\n".join(texts)
    return CompactedSummaryMessage(summary_text=all_text)


# Pattern for user memory input tag
USER_MEMORY_PATTERN = re.compile(
    r"<user-memory-input>(.*?)</user-memory-input>", re.DOTALL
)


def parse_user_memory(text: str) -> Optional[UserMemoryMessage]:
    """Parse user memory input tag from text.

    User memory input contains context that the user has provided from
    their CLAUDE.md or other memory sources.

    Args:
        text: Raw text that may contain user memory input tag

    Returns:
        UserMemoryMessage if tag found, None otherwise
    """
    match = USER_MEMORY_PATTERN.search(text)
    if match:
        memory_content = match.group(1).strip()
        return UserMemoryMessage(memory_text=memory_content)
    return None


# =============================================================================
# User Message Content Parsing
# =============================================================================

# Type alias for content models returned by parse_user_message_content
UserMessageContent = Union[
    CompactedSummaryMessage, UserMemoryMessage, UserSlashCommandMessage, UserTextMessage
]


def parse_user_message_content(
    content_list: list[ContentItem],
    is_slash_command: bool = False,
) -> Optional[UserMessageContent]:
    """Parse user message content into a structured content model.

    Returns a content model for HtmlRenderer to format. The caller can use
    isinstance() checks to determine the content type:
    - UserSlashCommandMessage: Slash command expanded prompts (isMeta=True)
    - CompactedSummaryMessage: Session continuation summaries
    - UserMemoryMessage: User memory input from CLAUDE.md
    - UserTextMessage: Normal user text with optional IDE notifications and images

    This function processes content items preserving their original order:
    - TextContent items have IDE notifications extracted, producing
      [IdeNotificationContent, TextContent] pairs
    - ImageContent items are preserved as-is

    Args:
        content_list: List of ContentItem from user message
        is_slash_command: True for slash command expanded prompts (isMeta=True)

    Returns:
        A content model, or None if content_list is empty.
    """
    if not content_list:
        return None

    # Slash command expanded prompts - combine all text as markdown
    if is_slash_command:
        all_text = "\n\n".join(
            getattr(item, "text", "") for item in content_list if hasattr(item, "text")
        )
        return UserSlashCommandMessage(text=all_text) if all_text else None

    # Get first text item for special case detection
    first_text_item = next(
        (item for item in content_list if hasattr(item, "text")),
        None,
    )
    first_text = getattr(first_text_item, "text", "") if first_text_item else ""

    # Check for compacted session summary first (handles text combining internally)
    compacted = parse_compacted_summary(content_list)
    if compacted:
        return compacted

    # Check for user memory input
    user_memory = parse_user_memory(first_text)
    if user_memory:
        return user_memory

    # Build items list preserving order, extracting IDE notifications from text
    items: list[TextContent | ImageContent | IdeNotificationContent] = []

    for item in content_list:
        # Check for text content
        if hasattr(item, "text"):
            item_text: str = getattr(item, "text")  # type: ignore[assignment]
            ide_content = parse_ide_notifications(item_text)

            if ide_content:
                # Add IDE notification item first
                items.append(ide_content)
                remaining_text: str = ide_content.remaining_text
            else:
                remaining_text = item_text

            # Add remaining text as TextContent if non-empty
            if remaining_text.strip():
                items.append(TextContent(type="text", text=remaining_text))
        elif isinstance(item, ImageContent):
            # ImageContent model - use as-is
            items.append(item)
        elif hasattr(item, "source") and getattr(item, "type", None) == "image":
            # Anthropic ImageContent - convert to our model
            items.append(ImageContent.model_validate(item.model_dump()))  # type: ignore[union-attr]

    # Return UserTextMessage with items list
    return UserTextMessage(items=items)
