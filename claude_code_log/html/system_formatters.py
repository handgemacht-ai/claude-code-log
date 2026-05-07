"""HTML formatters for system message content.

This module formats SystemTranscriptEntry-derived content types to HTML.
Part of the thematic formatter organization:
- system_formatters.py: SystemMessage, HookSummaryMessage, AwaySummaryMessage,
  HookAttachmentMessage
- user_formatters.py: SlashCommandMessage, CommandOutputMessage, etc.
- assistant_formatters.py: AssistantTextMessage, ThinkingMessage, ImageContent
- tool_formatters.py: tool use/result content
"""

import html

from .ansi_colors import convert_ansi_to_html
from .utils import render_markdown
from ..models import (
    AwaySummaryMessage,
    HookAttachmentMessage,
    HookSummaryMessage,
    SessionHeaderMessage,
    SystemMessage,
)


def format_system_content(content: SystemMessage) -> str:
    """Format a system message with level-specific icon.

    Multi-line content (ASCII visualisations from ``/context``,
    ``/cost``, etc., or any system entry whose cleaned text spans more
    than one line) renders inside a ``<pre>`` block so whitespace and
    grid alignment are preserved. Single-line system messages
    (``/status`` dialog hints, ``/init`` cleaned-name forms, …) keep
    the existing inline rendering — adding a block-level ``<pre>`` to a
    one-liner would cost vertical space without benefit.

    Args:
        content: SystemMessage with level and text

    Returns:
        HTML with icon and ANSI-converted text
    """
    level_icon = {"warning": "⚠️", "error": "❌", "info": "ℹ️"}.get(content.level, "ℹ️")
    html_content = convert_ansi_to_html(content.text)
    if "\n" in content.text:
        return (
            f"<strong>{level_icon}</strong>"
            f"<pre class='system-content'>{html_content}</pre>"
        )
    return f"<strong>{level_icon}</strong> {html_content}"


def format_hook_summary_content(content: HookSummaryMessage) -> str:
    """Format a hook summary as collapsible details.

    Shows a compact summary with expandable hook commands and error output.

    Args:
        content: HookSummaryMessage with execution details

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


def format_hook_attachment_content(content: HookAttachmentMessage) -> str:
    """Format a hook attachment payload as collapsible details.

    Surfaces the hook command, exit code, duration and any
    stdout/stderr/blocking-error text. Folded by default; visible only
    at full detail (post-render filter drops HookAttachmentMessage at
    HIGH and below alongside HookSummaryMessage).

    Args:
        content: HookAttachmentMessage with parsed hook payload.

    Returns:
        HTML for a ``<details>`` block with header summary and body.
    """
    is_error = content.kind in ("blocking_error", "non_blocking_error")
    summary_icon = "🚨" if is_error else "🪝"

    if content.kind == "blocking_error":
        summary_label = "Hook blocked"
    elif content.kind == "non_blocking_error":
        summary_label = "Hook errored"
    elif content.kind == "additional_context":
        summary_label = "Hook added context"
    else:
        summary_label = "Hook output"

    header_pieces: list[str] = []
    if content.hook_name:
        header_pieces.append(html.escape(content.hook_name))
    elif content.hook_event:
        header_pieces.append(html.escape(content.hook_event))
    if content.exit_code is not None:
        header_pieces.append(f"exit {content.exit_code}")
    if content.duration_ms is not None:
        header_pieces.append(f"{content.duration_ms} ms")
    header_extra = (
        f' <span class="hook-attachment-meta">· {" · ".join(header_pieces)}</span>'
        if header_pieces
        else ""
    )

    body_parts: list[str] = []
    if content.command:
        body_parts.append(
            '<div class="hook-commands">'
            f"<code>{html.escape(content.command)}</code>"
            "</div>"
        )
    if content.blocking_error:
        rendered = convert_ansi_to_html(content.blocking_error)
        body_parts.append(
            f'<div class="hook-errors"><pre class="hook-error">{rendered}</pre></div>'
        )
    if content.content:
        rendered = convert_ansi_to_html(content.content)
        body_parts.append(f'<pre class="hook-attachment-content">{rendered}</pre>')
    if content.stdout:
        rendered = convert_ansi_to_html(content.stdout)
        body_parts.append(
            '<div class="hook-attachment-stream">'
            '<div class="hook-attachment-stream-label">stdout</div>'
            f'<pre class="hook-attachment-output">{rendered}</pre>'
            "</div>"
        )
    if content.stderr:
        rendered = convert_ansi_to_html(content.stderr)
        body_parts.append(
            '<div class="hook-attachment-stream">'
            '<div class="hook-attachment-stream-label">stderr</div>'
            f'<pre class="hook-attachment-output hook-attachment-stderr">{rendered}</pre>'
            "</div>"
        )

    body = (
        f'<div class="hook-details">{"".join(body_parts)}</div>' if body_parts else ""
    )
    return (
        f'<details class="hook-attachment">'
        f"<summary><strong>{summary_icon}</strong> "
        f"{summary_label}{header_extra}</summary>"
        f"{body}"
        "</details>"
    )


def format_away_summary_content(content: AwaySummaryMessage) -> str:
    """Format an away_summary recap as HTML.

    Renders Claude's narrative recap as markdown — the harness emits
    short prose that may include light markdown (lists, code spans).
    The "📝 Recap" label is supplied by the message header (icon from
    get_message_emoji + title_AwaySummaryMessage); the body is plain
    rendered markdown so block elements (<p>, <ul>) sit at the same
    level rather than inline beside a stray <strong>.

    Args:
        content: AwaySummaryMessage with recap text.

    Returns:
        Rendered markdown HTML.
    """
    return render_markdown(content.text)


def _team_badge(team_name: str) -> str:
    """Render a colored 'Team: …' pill for the session header (teammates feature).

    Picks the team-card palette token (`--cc-purple`) so the badge reads as
    structurally related to the TeamCreate cards from PR #122.
    """
    return (
        f'<span class="session-team-badge" '
        f'style="--cc-color: var(--cc-purple); '
        f'--cc-color-bg: var(--cc-purple-bg);">'
        f'<span class="session-team-icon">👥</span>Team: '
        f"{html.escape(team_name)}</span>"
    )


def format_session_header_content(content: SessionHeaderMessage) -> str:
    """Format a session header as HTML.

    Args:
        content: SessionHeaderMessage with title, session_id, and optional summary

    Returns:
        HTML for the session header display
    """
    escaped_title = html.escape(content.title)
    badges = _team_badge(content.team_name) if content.team_name else ""
    if content.is_branch and content.parent_message_index is not None:
        # Branch header: compact with back-reference to fork point
        # Show session info for cross-session branches (different real session)
        session_info = ""
        if content.original_session_id and content.parent_session_id:
            parent_real_sid = content.parent_session_id.split("@")[0]
            if content.original_session_id != parent_real_sid:
                esc_sid = html.escape(content.original_session_id[:8])
                session_info = (
                    f' <span class="branch-session">(in Session {esc_sid})</span>'
                )
        fork_backref = ""
        if content.parent_session_summary:
            escaped_fork = html.escape(content.parent_session_summary)
            fork_backref = (
                f'<div class="branch-from">'
                f'from <a href="#msg-d-{content.parent_message_index}" '
                f'class="branch-backlink">'
                f"&#x2442; Fork point &bull; {escaped_fork}</a></div>"
            )
        else:
            fork_backref = (
                f'<div class="branch-from">'
                f'from <a href="#msg-d-{content.parent_message_index}" '
                f'class="branch-backlink">'
                f"&#x2442; Fork point</a></div>"
            )
        return f"{escaped_title}{badges}{session_info}{fork_backref}"
    if content.parent_session_id:
        parent_label = content.parent_session_summary or content.parent_session_id[:8]
        escaped_parent = html.escape(parent_label)
        if content.parent_message_index is not None:
            link = (
                f'<a href="#msg-d-{content.parent_message_index}" '
                f'class="session-backlink">&#x21b3; continues from '
                f"{escaped_parent}</a>"
            )
        else:
            link = (
                f'<span class="session-backlink">&#x21b3; continues from '
                f"{escaped_parent}</span>"
            )
        return f"{link}{escaped_title}{badges}"
    return f"{escaped_title}{badges}"


__all__ = [
    "format_system_content",
    "format_hook_summary_content",
    "format_hook_attachment_content",
    "format_away_summary_content",
    "format_session_header_content",
]
