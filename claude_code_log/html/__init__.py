"""HTML-specific rendering utilities package.

Re-exports all functions from utils and tool_renderers modules for backward compatibility.
"""

from .utils import (
    css_class_from_message,
    escape_html,
    get_message_emoji,
    get_template_environment,
    render_collapsible_code,
    render_file_content_collapsible,
    render_markdown,
    render_markdown_collapsible,
    starts_with_emoji,
)
from .tool_renderers import (
    format_askuserquestion_content,
    format_askuserquestion_result,
    format_bash_tool_content,
    format_edit_tool_content,
    format_exitplanmode_content,
    format_exitplanmode_result,
    format_multiedit_tool_content,
    format_read_tool_content,
    format_task_tool_content,
    format_todowrite_content,
    format_tool_use_content,
    format_tool_use_title,
    format_write_tool_content,
    get_tool_summary,
    render_params_table,
)

__all__ = [
    # utils
    "css_class_from_message",
    "escape_html",
    "get_message_emoji",
    "get_template_environment",
    "render_collapsible_code",
    "render_file_content_collapsible",
    "render_markdown",
    "render_markdown_collapsible",
    "starts_with_emoji",
    # tool_renderers
    "format_askuserquestion_content",
    "format_askuserquestion_result",
    "format_bash_tool_content",
    "format_edit_tool_content",
    "format_exitplanmode_content",
    "format_exitplanmode_result",
    "format_multiedit_tool_content",
    "format_read_tool_content",
    "format_task_tool_content",
    "format_todowrite_content",
    "format_tool_use_content",
    "format_tool_use_title",
    "format_write_tool_content",
    "get_tool_summary",
    "render_params_table",
]
