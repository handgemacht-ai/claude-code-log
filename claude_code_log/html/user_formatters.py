"""HTML formatters for user message content.

This module formats non-tool user message content types to HTML.
Part of the thematic formatter organization:
- system_formatters.py: SystemContent, HookSummaryContent
- user_formatters.py: SlashCommandContent, CommandOutputContent, etc.
- assistant_formatters.py: (future) assistant message variants
- tool_formatters.py: tool use/result content
"""

from typing import List

import mistune

from ..ansi_colors import convert_ansi_to_html
from ..models import (
    BashInputContent,
    CommandOutputContent,
    SlashCommandContent,
)
from .utils import escape_html, render_collapsible_code


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
# Public Exports
# =============================================================================

__all__ = [
    # Formatting functions
    "format_slash_command_content",
    "format_command_output_content",
    "format_bash_input_content",
]
