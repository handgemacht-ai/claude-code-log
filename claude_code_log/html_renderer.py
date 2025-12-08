"""HTML-specific rendering utilities.

This module contains all HTML generation code:
- CSS class computation from message type and modifiers
- Message emoji generation
- (Future: HTML escaping, markdown rendering, tool formatters)

The functions here transform format-neutral TemplateMessage data into
HTML-specific attributes like CSS classes and display emojis.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .renderer import TemplateMessage


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
