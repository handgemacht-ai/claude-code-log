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
    BashOutputContent,
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


def format_bash_output_content(
    content: BashOutputContent,
    collapse_threshold: int = 10,
    preview_lines: int = 3,
) -> str:
    """Format bash output content as HTML.

    Args:
        content: BashOutputContent with stdout and/or stderr
        collapse_threshold: Number of lines before output becomes collapsible
        preview_lines: Number of preview lines to show when collapsed

    Returns:
        HTML string for the bash output display
    """
    output_parts: List[tuple[str, str, int, str]] = []
    total_lines = 0

    if content.stdout:
        escaped_stdout = convert_ansi_to_html(content.stdout)
        stdout_lines = content.stdout.count("\n") + 1
        total_lines += stdout_lines
        output_parts.append(("stdout", escaped_stdout, stdout_lines, content.stdout))

    if content.stderr:
        escaped_stderr = convert_ansi_to_html(content.stderr)
        stderr_lines = content.stderr.count("\n") + 1
        total_lines += stderr_lines
        output_parts.append(("stderr", escaped_stderr, stderr_lines, content.stderr))

    if not output_parts:
        # Empty output
        return (
            "<pre class='bash-stdout'><span class='bash-empty'>(no output)</span></pre>"
        )

    # Build the HTML parts
    html_parts: List[str] = []
    for output_type, escaped_content, _, _ in output_parts:
        css_name = f"bash-{output_type}"
        html_parts.append(f"<pre class='{css_name}'>{escaped_content}</pre>")

    full_html = "".join(html_parts)

    # Wrap in collapsible if output is large
    if total_lines > collapse_threshold:
        # Create preview (first few lines)
        first_output = output_parts[0]
        raw_preview = "\n".join(first_output[3].split("\n")[:preview_lines])
        preview_html = escape_html(raw_preview)
        if total_lines > preview_lines:
            preview_html += "\n..."

        return f"""<details class='collapsible-code'>
            <summary>
                <span class='line-count'>{total_lines} lines</span>
                <pre class='preview-content bash-stdout'>{preview_html}</pre>
            </summary>
            <div class='code-full'>{full_html}</div>
        </details>"""

    return full_html


# =============================================================================
# Public Exports
# =============================================================================

__all__ = [
    # Formatting functions
    "format_slash_command_content",
    "format_command_output_content",
    "format_bash_input_content",
    "format_bash_output_content",
]
