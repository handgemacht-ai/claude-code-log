"""HTML formatters for user message content.

This module formats non-tool user message content types to HTML.
Part of the thematic formatter organization:
- system_formatters.py: SystemContent, HookSummaryContent
- user_formatters.py: SlashCommandContent, CommandOutputContent, etc.
- assistant_formatters.py: (future) assistant message variants
- tool_formatters.py: tool use/result content
"""

import re
from dataclasses import dataclass
from typing import List, Optional

import mistune

from ..ansi_colors import convert_ansi_to_html
from ..models import MessageContent
from .utils import escape_html, render_collapsible_code


# =============================================================================
# User Message Content Models
# =============================================================================


@dataclass
class SlashCommandContent(MessageContent):
    """Content for slash command invocations (e.g., /context, /model).

    These are user messages containing command-name, command-args, and
    command-contents tags parsed from the text.
    """

    command_name: str
    command_args: str
    command_contents: str


@dataclass
class CommandOutputContent(MessageContent):
    """Content for local command output (e.g., output from /context).

    These are user messages containing local-command-stdout tags.
    """

    stdout: str
    is_markdown: bool  # True if content appears to be markdown


@dataclass
class BashInputContent(MessageContent):
    """Content for inline bash commands in user messages.

    These are user messages containing bash-input tags.
    """

    command: str


@dataclass
class CompactedSummaryContent(MessageContent):
    """Content for compacted session summaries.

    These are user messages that contain previous conversation context
    in a compacted format.
    """

    summary_text: str


@dataclass
class UserMemoryContent(MessageContent):
    """Content for user memory input.

    These are user messages containing user-memory-input tags.
    """

    memory_text: str


@dataclass
class IdeNotificationContent(MessageContent):
    """Content for IDE notification tags.

    These are user messages containing ide-notification-* tags.
    """

    notifications: List[str]  # HTML strings for each notification
    remaining_text: str  # Text after notifications extracted


# =============================================================================
# Formatting Functions
# =============================================================================


def format_slash_command_content(content: SlashCommandContent) -> str:
    """Format slash command content as HTML.

    Args:
        content: SlashCommandContent with command name, args, and contents

    Returns:
        HTML string for the slash command display
    """
    escaped_command_name = escape_html(content.command_name)
    escaped_command_args = escape_html(content.command_args)

    # Format the command contents with proper line breaks
    formatted_contents = content.command_contents.replace("\\n", "\n")
    escaped_command_contents = escape_html(formatted_contents)

    # Build the content HTML - command name is the primary content
    content_parts: List[str] = [f"<code>{escaped_command_name}</code>"]
    if content.command_args:
        content_parts.append(f"<strong>Args:</strong> {escaped_command_args}")
    if content.command_contents:
        lines = escaped_command_contents.splitlines()
        line_count = len(lines)
        if line_count <= 12:
            # Short content, show inline
            details_html = (
                f"<strong>Content:</strong><pre>{escaped_command_contents}</pre>"
            )
        else:
            # Long content, make collapsible
            preview = "\n".join(lines[:5])
            collapsible = render_collapsible_code(
                f"<pre>{preview}</pre>",
                f"<pre>{escaped_command_contents}</pre>",
                line_count,
            )
            details_html = f"<strong>Content:</strong>{collapsible}"
        content_parts.append(details_html)

    return "<br>".join(content_parts)


def format_command_output_content(content: CommandOutputContent) -> str:
    """Format command output content as HTML.

    Args:
        content: CommandOutputContent with stdout and is_markdown flag

    Returns:
        HTML string for the command output display
    """
    if content.is_markdown:
        # Render as markdown
        markdown_html = mistune.html(content.stdout)
        return f"<div class='command-output-content'>{markdown_html}</div>"
    else:
        # Convert ANSI codes to HTML for colored display
        html_content = convert_ansi_to_html(content.stdout)
        # Use <pre> to preserve formatting and line breaks
        return f"<pre class='command-output-content'>{html_content}</pre>"


def format_bash_input_content(content: BashInputContent) -> str:
    """Format bash input content as HTML.

    Args:
        content: BashInputContent with the bash command

    Returns:
        HTML string for the bash input display
    """
    escaped_command = escape_html(content.command)
    return (
        f"<span class='bash-prompt'>❯</span> "
        f"<code class='bash-command'>{escaped_command}</code>"
    )


# =============================================================================
# Parsing Helpers
# =============================================================================


def parse_slash_command(text: str) -> Optional[SlashCommandContent]:
    """Parse slash command tags from text.

    Args:
        text: Raw text that may contain command-name, command-args, command-contents tags

    Returns:
        SlashCommandContent if tags found, None otherwise
    """
    import json
    from typing import Any, Dict, cast

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
                text_dict = cast(Dict[str, Any], contents_json)
                text_value = text_dict["text"]
                command_contents = str(text_value)
            else:
                command_contents = contents_text
        except json.JSONDecodeError:
            command_contents = contents_text

    return SlashCommandContent(
        command_name=command_name,
        command_args=command_args,
        command_contents=command_contents,
    )


def parse_command_output(text: str) -> Optional[CommandOutputContent]:
    """Parse command output tags from text.

    Args:
        text: Raw text that may contain local-command-stdout tags

    Returns:
        CommandOutputContent if tags found, None otherwise
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

    return CommandOutputContent(stdout=stdout_content, is_markdown=is_markdown)


def parse_bash_input(text: str) -> Optional[BashInputContent]:
    """Parse bash input tags from text.

    Args:
        text: Raw text that may contain bash-input tags

    Returns:
        BashInputContent if tags found, None otherwise
    """
    bash_match = re.search(r"<bash-input>(.*?)</bash-input>", text, re.DOTALL)
    if not bash_match:
        return None

    return BashInputContent(command=bash_match.group(1).strip())


# =============================================================================
# Public Exports
# =============================================================================

__all__ = [
    # Content models
    "SlashCommandContent",
    "CommandOutputContent",
    "BashInputContent",
    "CompactedSummaryContent",
    "UserMemoryContent",
    "IdeNotificationContent",
    # Formatting functions
    "format_slash_command_content",
    "format_command_output_content",
    "format_bash_input_content",
    # Parsing helpers
    "parse_slash_command",
    "parse_command_output",
    "parse_bash_input",
]
