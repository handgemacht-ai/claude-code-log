"""HTML rendering functions for tool use and tool result content.

This module contains all HTML formatters for specific tools:
- AskUserQuestion tool (input + result)
- ExitPlanMode tool (input + result)
- TodoWrite tool
- Read/Write/Edit/Multiedit tools
- Bash tool
- Task tool
- Generic parameter table rendering
- Tool use content dispatcher

These formatters take tool-specific input/output data and generate
HTML for display in transcripts.
"""

import json
import re
from typing import Any, Dict, List

from .html_renderer import (
    escape_html,
    render_file_content_collapsible,
    render_markdown_collapsible,
)
from .models import ToolUseContent
from .renderer_code import render_single_diff


# -- AskUserQuestion Tool -----------------------------------------------------


def format_askuserquestion_content(tool_use: ToolUseContent) -> str:
    """Format AskUserQuestion tool use content with prominent question display.

    Handles multiple questions in a single tool use, each with optional header,
    options (with label and description), and multiSelect flag.
    """
    questions_data = tool_use.input.get("questions", [])
    # Also handle single question format for backwards compatibility
    if not questions_data:
        single_question = tool_use.input.get("question", "")
        if single_question:
            questions_data = [{"question": single_question}]

    if not questions_data:
        return render_params_table(tool_use.input)

    # Build HTML for all questions
    html_parts: List[str] = ['<div class="askuserquestion-content">']

    for q_data in questions_data:
        try:
            question_text = escape_html(str(q_data.get("question", "")))
            header = q_data.get("header", "")
            options = q_data.get("options", [])
            multi_select = q_data.get("multiSelect", False)

            # Question container
            html_parts.append('<div class="question-block">')

            # Header (if present)
            if header:
                escaped_header = escape_html(str(header))
                html_parts.append(
                    f'<div class="question-header">{escaped_header}</div>'
                )

            # Question text with icon
            html_parts.append(f'<div class="question-text">❓ {question_text}</div>')

            # Options (if present)
            if options:
                select_hint = "(select multiple)" if multi_select else "(select one)"
                html_parts.append(
                    f'<div class="question-options-hint">{select_hint}</div>'
                )
                html_parts.append('<ul class="question-options">')
                for opt in options:
                    label = escape_html(str(opt.get("label", "")))
                    desc = opt.get("description", "")
                    if desc:
                        desc_html = f'<span class="option-desc"> — {escape_html(str(desc))}</span>'
                    else:
                        desc_html = ""
                    html_parts.append(
                        f'<li class="question-option"><strong>{label}</strong>{desc_html}</li>'
                    )
                html_parts.append("</ul>")

            html_parts.append("</div>")  # Close question-block
        except (AttributeError, TypeError):
            # Fallback for unexpected format
            html_parts.append(
                f'<div class="question-text">❓ {escape_html(str(q_data))}</div>'
            )

    html_parts.append("</div>")  # Close askuserquestion-content
    return "".join(html_parts)


def format_askuserquestion_result(content: str) -> str:
    """Format AskUserQuestion tool result with styled question/answer pairs.

    Parses the result format:
    'User has answered your questions: "Q1"="A1", "Q2"="A2". You can now continue...'

    Returns HTML with styled Q&A blocks matching the input styling.
    """
    # Check if this is a successful answer
    if not content.startswith("User has answered your question"):
        # Return as-is for errors or unexpected format
        return ""

    # Extract the Q&A portion between the colon and the final sentence
    # Pattern: 'User has answered your questions: "Q"="A", "Q"="A". You can now...'
    match = re.match(
        r"User has answered your questions?: (.+)\. You can now continue",
        content,
        re.DOTALL,
    )
    if not match:
        return ""

    qa_portion = match.group(1)

    # Parse "Question"="Answer" pairs
    # Pattern: "question text"="answer text"
    qa_pattern = re.compile(r'"([^"]+)"="([^"]+)"')
    pairs = qa_pattern.findall(qa_portion)

    if not pairs:
        return ""

    # Build styled HTML
    html_parts: List[str] = [
        '<div class="askuserquestion-content askuserquestion-result">'
    ]

    for question, answer in pairs:
        escaped_q = escape_html(question)
        escaped_a = escape_html(answer)
        html_parts.append('<div class="question-block answered">')
        html_parts.append(f'<div class="question-text">❓ {escaped_q}</div>')
        html_parts.append(f'<div class="answer-text">✅ {escaped_a}</div>')
        html_parts.append("</div>")

    html_parts.append("</div>")
    return "".join(html_parts)


# -- ExitPlanMode Tool --------------------------------------------------------


def format_exitplanmode_content(tool_use: ToolUseContent) -> str:
    """Format ExitPlanMode tool use content with collapsible plan markdown.

    Renders the plan markdown in a collapsible section, similar to Task tool results.
    """
    plan = tool_use.input.get("plan", "")

    if not plan:
        # No plan, show parameters table as fallback
        return render_params_table(tool_use.input)

    return render_markdown_collapsible(plan, "plan-content")


def format_exitplanmode_result(content: str) -> str:
    """Format ExitPlanMode tool result, truncating the redundant plan echo.

    When a plan is approved, the result contains:
    1. A confirmation message
    2. Path to saved plan file
    3. "## Approved Plan:" followed by full plan text (redundant)

    We truncate everything after "## Approved Plan:" to avoid duplication.
    For error results (plan not approved), we keep the full content.
    """
    # Check if this is a successful approval
    if "User has approved your plan" in content:
        # Truncate at "## Approved Plan:"
        marker = "## Approved Plan:"
        marker_pos = content.find(marker)
        if marker_pos > 0:
            # Keep everything before the marker, strip trailing whitespace
            return content[:marker_pos].rstrip()

    # For errors or other cases, return as-is
    return content


# -- TodoWrite Tool -----------------------------------------------------------


def format_todowrite_content(tool_use: ToolUseContent) -> str:
    """Format TodoWrite tool use content as a todo list."""
    # Parse todos from input
    todos_data = tool_use.input.get("todos", [])
    if not todos_data:
        return """
        <div class="todo-content">
            <p><em>No todos found</em></p>
        </div>
        """

    # Status emojis
    status_emojis = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}

    # Build todo list HTML
    todo_items: List[str] = []
    for todo in todos_data:
        try:
            todo_id = escape_html(str(todo.get("id", "")))
            content = escape_html(str(todo.get("content", "")))
            status = str(todo.get("status", "pending")).lower()
            priority = str(todo.get("priority", "medium")).lower()
            status_emoji = status_emojis.get(status, "⏳")

            # CSS class for styling
            item_class = f"todo-item {status} {priority}"

            todo_items.append(f"""
                <div class="{item_class}">
                    <span class="todo-status">{status_emoji}</span>
                    <span class="todo-content">{content}</span>
                    <span class="todo-id">#{todo_id}</span>
                </div>
            """)
        except AttributeError:
            escaped_fallback = escape_html(str(todo))
            todo_items.append(f"""
                <div class="todo-item pending medium">
                    <span class="todo-status">⏳</span>
                    <span class="todo-content">{escaped_fallback}</span>
                </div>
            """)

    todos_html = "".join(todo_items)

    return f"""
    <div class="todo-list">
        {todos_html}
    </div>
    """


# -- File Tools (Read/Write) --------------------------------------------------


def format_read_tool_content(tool_use: ToolUseContent) -> str:  # noqa: ARG001
    """Format Read tool use content showing file path.

    Note: File path is now shown in the header, so we skip content here.
    """
    # File path is now shown in header, so no content needed
    # Don't show offset/limit parameters as they'll be visible in the result
    return ""


def format_write_tool_content(tool_use: ToolUseContent) -> str:
    """Format Write tool use content with Pygments syntax highlighting.

    Note: File path is now shown in the header, so we skip it here.
    """
    file_path = tool_use.input.get("file_path", "")
    content = tool_use.input.get("content", "")

    return render_file_content_collapsible(content, file_path, "write-tool-content")


# -- Edit Tools (Edit/Multiedit) ----------------------------------------------


def format_edit_tool_content(tool_use: ToolUseContent) -> str:
    """Format Edit tool use content as a diff view with intra-line highlighting.

    Note: File path is now shown in the header, so we skip it here.
    """
    old_string = tool_use.input.get("old_string", "")
    new_string = tool_use.input.get("new_string", "")
    replace_all = tool_use.input.get("replace_all", False)

    html_parts = ["<div class='edit-tool-content'>"]

    # File path is now shown in header, so we skip it here

    if replace_all:
        html_parts.append(
            "<div class='edit-replace-all'>🔄 Replace all occurrences</div>"
        )

    # Use shared diff rendering helper
    html_parts.append(render_single_diff(old_string, new_string))
    html_parts.append("</div>")

    return "".join(html_parts)


def format_multiedit_tool_content(tool_use: ToolUseContent) -> str:
    """Format Multiedit tool use content showing multiple diffs."""
    file_path = tool_use.input.get("file_path", "")
    edits = tool_use.input.get("edits", [])

    escaped_path = escape_html(file_path)

    html_parts = ["<div class='multiedit-tool-content'>"]

    # File path header
    html_parts.append(f"<div class='multiedit-file-path'>📝 {escaped_path}</div>")
    html_parts.append(f"<div class='multiedit-count'>Applying {len(edits)} edits</div>")

    # Render each edit as a diff
    for idx, edit in enumerate(edits, 1):
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")

        html_parts.append(
            f"<div class='multiedit-item'><div class='multiedit-item-header'>Edit #{idx}</div>"
        )
        html_parts.append(render_single_diff(old_string, new_string))
        html_parts.append("</div>")

    html_parts.append("</div>")
    return "".join(html_parts)


# -- Bash Tool ----------------------------------------------------------------


def format_bash_tool_content(tool_use: ToolUseContent) -> str:
    """Format Bash tool use content in VS Code extension style.

    Note: Description is now shown in the header, so we skip it here.
    """
    command = tool_use.input.get("command", "")

    escaped_command = escape_html(command)

    html_parts = ["<div class='bash-tool-content'>"]

    # Description is now shown in header, so we skip it here

    # Add command in preformatted block
    html_parts.append(f"<pre class='bash-tool-command'>{escaped_command}</pre>")
    html_parts.append("</div>")

    return "".join(html_parts)


# -- Task Tool ----------------------------------------------------------------


def format_task_tool_content(tool_use: ToolUseContent) -> str:
    """Format Task tool content with markdown-rendered prompt.

    Task tool spawns sub-agents. We render the prompt as the main content.
    The sidechain user message (which would duplicate this prompt) is skipped.

    For long prompts (>20 lines), the content is made collapsible with a
    preview of the first few lines to keep the transcript vertically compact.
    """
    prompt = tool_use.input.get("prompt", "")

    if not prompt:
        # No prompt, show parameters table as fallback
        return render_params_table(tool_use.input)

    return render_markdown_collapsible(prompt, "task-prompt")


# -- Generic Parameter Table --------------------------------------------------


def render_params_table(params: Dict[str, Any]) -> str:
    """Render a dictionary of parameters as an HTML table.

    Reusable for tool parameters, diagnostic objects, etc.
    """
    if not params:
        return "<div class='tool-params-empty'>No parameters</div>"

    html_parts = ["<table class='tool-params-table'>"]

    for key, value in params.items():
        escaped_key = escape_html(str(key))

        # If value is structured (dict/list), render as JSON
        if isinstance(value, (dict, list)):
            try:
                formatted_value = json.dumps(value, indent=2, ensure_ascii=False)  # type: ignore[arg-type]
                escaped_value = escape_html(formatted_value)

                # Make long structured values collapsible
                if len(formatted_value) > 200:
                    preview = escape_html(formatted_value[:100]) + "..."
                    value_html = f"""
                        <details class='tool-param-collapsible'>
                            <summary>{preview}</summary>
                            <pre class='tool-param-structured'>{escaped_value}</pre>
                        </details>
                    """
                else:
                    value_html = (
                        f"<pre class='tool-param-structured'>{escaped_value}</pre>"
                    )
            except (TypeError, ValueError):
                escaped_value = escape_html(str(value))  # type: ignore[arg-type]
                value_html = escaped_value
        else:
            # Simple value, render as-is (or collapsible if long)
            escaped_value = escape_html(str(value))

            # Make long string values collapsible
            if len(str(value)) > 100:
                preview = escape_html(str(value)[:80]) + "..."
                value_html = f"""
                    <details class='tool-param-collapsible'>
                        <summary>{preview}</summary>
                        <div class='tool-param-full'>{escaped_value}</div>
                    </details>
                """
            else:
                value_html = escaped_value

        html_parts.append(f"""
            <tr>
                <td class='tool-param-key'>{escaped_key}</td>
                <td class='tool-param-value'>{value_html}</td>
            </tr>
        """)

    html_parts.append("</table>")
    return "".join(html_parts)


# -- Tool Use Dispatcher ------------------------------------------------------


def format_tool_use_content(tool_use: ToolUseContent) -> str:
    """Format tool use content as HTML."""
    # Special handling for TodoWrite
    if tool_use.name == "TodoWrite":
        return format_todowrite_content(tool_use)

    # Special handling for Bash
    if tool_use.name == "Bash":
        return format_bash_tool_content(tool_use)

    # Special handling for Edit
    if tool_use.name == "Edit":
        return format_edit_tool_content(tool_use)

    # Special handling for Multiedit
    if tool_use.name == "Multiedit":
        return format_multiedit_tool_content(tool_use)

    # Special handling for Read
    if tool_use.name == "Read":
        return format_read_tool_content(tool_use)

    # Special handling for Write
    if tool_use.name == "Write":
        return format_write_tool_content(tool_use)

    # Special handling for Task (agent spawning)
    if tool_use.name == "Task":
        return format_task_tool_content(tool_use)

    # Special handling for AskUserQuestion
    if tool_use.name == "AskUserQuestion":
        return format_askuserquestion_content(tool_use)

    # Special handling for ExitPlanMode
    if tool_use.name == "ExitPlanMode":
        return format_exitplanmode_content(tool_use)

    # Default: render as key/value table using shared renderer
    return render_params_table(tool_use.input)


# -- Public Exports -----------------------------------------------------------

__all__ = [
    # AskUserQuestion
    "format_askuserquestion_content",
    "format_askuserquestion_result",
    # ExitPlanMode
    "format_exitplanmode_content",
    "format_exitplanmode_result",
    # TodoWrite
    "format_todowrite_content",
    # File tools
    "format_read_tool_content",
    "format_write_tool_content",
    # Edit tools
    "format_edit_tool_content",
    "format_multiedit_tool_content",
    # Bash
    "format_bash_tool_content",
    # Task
    "format_task_tool_content",
    # Generic
    "render_params_table",
    # Dispatcher
    "format_tool_use_content",
]
