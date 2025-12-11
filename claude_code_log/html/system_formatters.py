"""HTML formatters for system message content.

This module formats SystemTranscriptEntry-derived content types to HTML.
Part of the thematic formatter organization:
- system_formatters.py: SystemContent, HookSummaryContent
- user_formatters.py: (future) user message variants
- assistant_formatters.py: (future) assistant message variants
- tool_renderers.py: tool use/result content
"""

import html

from ..ansi_colors import convert_ansi_to_html
from ..models import (
    HookSummaryContent,
    SystemContent,
)


def format_system_content(content: SystemContent) -> str:
    """Format a system message with level-specific icon.

    Args:
        content: SystemContent with level and text

    Returns:
        HTML with icon and ANSI-converted text
    """
    level_icon = {"warning": "⚠️", "error": "❌", "info": "ℹ️"}.get(content.level, "ℹ️")
    html_content = convert_ansi_to_html(content.text)
    return f"<strong>{level_icon}</strong> {html_content}"


def format_hook_summary_content(content: HookSummaryContent) -> str:
    """Format a hook summary as collapsible details.

    Shows a compact summary with expandable hook commands and error output.

    Args:
        content: HookSummaryContent with execution details

    Returns:
        HTML with collapsible details section
    """
    # Determine if this is a failure or just output
    has_errors = bool(content.hook_errors)
    summary_icon = "🪝"
    summary_text = "Hook failed" if has_errors else "Hook output"

    # Build the command section
    command_html = ""
    if content.hook_infos:
        command_html = '<div class="hook-commands">'
        for info in content.hook_infos:
            # Truncate very long commands
            cmd = info.command
            display_cmd = cmd if len(cmd) <= 100 else cmd[:97] + "..."
            command_html += f"<code>{html.escape(display_cmd)}</code>"
        command_html += "</div>"

    # Build the error output section
    error_html = ""
    if content.hook_errors:
        error_html = '<div class="hook-errors">'
        for err in content.hook_errors:
            # Convert ANSI codes in error output
            formatted_err = convert_ansi_to_html(err)
            error_html += f'<pre class="hook-error">{formatted_err}</pre>'
        error_html += "</div>"

    return f"""<details class="hook-summary">
<summary><strong>{summary_icon}</strong> {summary_text}</summary>
<div class="hook-details">
{command_html}
{error_html}
</div>
</details>"""
