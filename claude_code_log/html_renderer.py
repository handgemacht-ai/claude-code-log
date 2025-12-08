"""HTML-specific rendering utilities.

This module contains all HTML generation code:
- CSS class computation from message type and modifiers
- Message emoji generation
- HTML escaping and markdown rendering
- Collapsible content rendering
- Tool-specific HTML formatters
- Message content HTML rendering
- Template environment management

The functions here transform format-neutral TemplateMessage data into
HTML-specific output.
"""

import html
from typing import Any, Optional, TYPE_CHECKING

import mistune

from .renderer_timings import timing_stat

if TYPE_CHECKING:
    from .renderer import TemplateMessage


# -- CSS and Message Display --------------------------------------------------


def css_class_from_message(msg: "TemplateMessage") -> str:
    """Generate CSS class string from message type and modifiers.

    This reconstructs the original css_class format for backward
    compatibility with existing CSS and JavaScript.

    The order of classes follows the original pattern:
    1. Message type (required)
    2. Modifier flags in order: slash-command, command-output, compacted,
       error, steering, sidechain
    3. System level suffix (e.g., "system-info", "system-warning")

    Args:
        msg: The template message to generate CSS classes for

    Returns:
        Space-separated CSS class string (e.g., "user slash-command sidechain")
    """
    parts = [msg.type]

    mods = msg.modifiers
    if mods.is_slash_command:
        parts.append("slash-command")
    if mods.is_command_output:
        parts.append("command-output")
    if mods.is_compacted:
        parts.append("compacted")
    if mods.is_error:
        parts.append("error")
    if mods.is_steering:
        parts.append("steering")
    if mods.is_sidechain:
        parts.append("sidechain")
    if mods.system_level:
        parts.append(f"system-{mods.system_level}")

    return " ".join(parts)


def get_message_emoji(msg: "TemplateMessage") -> str:
    """Return appropriate emoji for message type.

    Args:
        msg: The template message to get emoji for

    Returns:
        Emoji string for the message type, or empty string if no emoji
    """
    msg_type = msg.type

    if msg_type == "session_header":
        return "📋"
    elif msg_type == "user":
        return "🤷"
    elif msg_type == "assistant":
        return "🤖"
    elif msg_type == "system":
        return "⚙️"
    elif msg_type == "tool_use":
        return "🛠️"
    elif msg_type == "tool_result":
        if msg.modifiers.is_error:
            return "🚨"
        return "🧰"
    elif msg_type == "thinking":
        return "💭"
    elif msg_type == "image":
        return "🖼️"
    return ""


# -- HTML Utilities -----------------------------------------------------------


def escape_html(text: str) -> str:
    """Escape HTML special characters in text.

    Also normalizes line endings (CRLF -> LF) to prevent double spacing in <pre> blocks.
    """
    # Normalize CRLF to LF to prevent double line breaks in HTML
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return html.escape(normalized)


def _create_pygments_plugin() -> Any:
    """Create a mistune plugin that uses Pygments for code block syntax highlighting."""
    from pygments import highlight  # type: ignore[reportUnknownVariableType]
    from pygments.lexers import get_lexer_by_name, TextLexer  # type: ignore[reportUnknownVariableType]
    from pygments.formatters import HtmlFormatter  # type: ignore[reportUnknownVariableType]
    from pygments.util import ClassNotFound  # type: ignore[reportUnknownVariableType]

    def plugin_pygments(md: Any) -> None:
        """Plugin to add Pygments syntax highlighting to code blocks."""
        original_render = md.renderer.block_code

        def block_code(code: str, info: Optional[str] = None) -> str:
            """Render code block with Pygments syntax highlighting if language is specified."""
            if info:
                # Language hint provided, use Pygments
                lang = info.split()[0] if info else ""
                try:
                    lexer = get_lexer_by_name(lang, stripall=True)  # type: ignore[reportUnknownVariableType]
                except ClassNotFound:
                    lexer = TextLexer()  # type: ignore[reportUnknownVariableType]

                formatter = HtmlFormatter(  # type: ignore[reportUnknownVariableType]
                    linenos=False,  # No line numbers in markdown code blocks
                    cssclass="highlight",
                    wrapcode=True,
                )
                # Track Pygments timing if enabled
                with timing_stat("_pygments_timings"):
                    return str(highlight(code, lexer, formatter))  # type: ignore[reportUnknownArgumentType]
            else:
                # No language hint, use default rendering
                return original_render(code, info)

        md.renderer.block_code = block_code

    return plugin_pygments


def render_markdown(text: str) -> str:
    """Convert markdown text to HTML using mistune with Pygments syntax highlighting."""
    # Track markdown rendering time if enabled
    with timing_stat("_markdown_timings"):
        # Configure mistune with GitHub-flavored markdown features
        renderer = mistune.create_markdown(
            plugins=[
                "strikethrough",
                "footnotes",
                "table",
                "url",
                "task_lists",
                "def_list",
                _create_pygments_plugin(),
            ],
            escape=False,  # Don't escape HTML since we want to render markdown properly
            hard_wrap=True,  # Line break for newlines (checklists in Assistant messages)
        )
        return str(renderer(text))
