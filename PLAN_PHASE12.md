# Phase 12: Format-Neutral Decomposition Plan

## Overview

This plan separates format-neutral logic from HTML-specific generation in renderer.py. The goal is to:
1. Create a `TemplateMessage` that stores logical attributes instead of CSS classes
2. Move HTML-specific rendering to a new `html_renderer.py` module
3. Keep format-neutral processing in `renderer.py` (to be renamed later)

## Key Design Decisions

### 1. Replace `css_class` with Typed Attributes

Instead of encoding traits as space-separated CSS classes (e.g., `"user sidechain slash-command"`), we'll use explicit fields:

```python
# In models.py - add MessageModifiers dataclass
@dataclass
class MessageModifiers:
    """Semantic modifiers for message rendering."""
    is_sidechain: bool = False
    is_slash_command: bool = False
    is_command_output: bool = False
    is_compacted: bool = False
    is_error: bool = False
    is_steering: bool = False
    system_level: Optional[str] = None  # "info", "warning", "error", "hook"
```

The `TemplateMessage` will have:
- `type: MessageType` (already have the enum)
- `modifiers: MessageModifiers` (new)
- Remove `css_class` field

### 2. HTML Renderer Module (`html_renderer.py`)

New module containing HTML-specific functions:

```python
# html_renderer.py

def css_class_from_message(msg: TemplateMessage) -> str:
    """Generate CSS class string from message type and modifiers."""
    parts = [msg.type.value]
    if msg.modifiers.is_sidechain:
        parts.append("sidechain")
    if msg.modifiers.is_slash_command:
        parts.append("slash-command")
    if msg.modifiers.is_command_output:
        parts.append("command-output")
    if msg.modifiers.is_compacted:
        parts.append("compacted")
    if msg.modifiers.is_error:
        parts.append("error")
    if msg.modifiers.is_steering:
        parts.append("steering")
    if msg.modifiers.system_level:
        parts.append(f"system-{msg.modifiers.system_level}")
    return " ".join(parts)

def get_message_emoji(msg: TemplateMessage) -> str:
    """Return emoji for message type."""
    # Move emoji logic from template to here

def render_content_html(msg: TemplateMessage) -> str:
    """Render message content to HTML."""
    # Delegates to format_* functions
```

### 3. Keep Format-Neutral Processing in renderer.py

Functions that stay in renderer.py (format-neutral):
- `_process_messages_loop()` - but sets `modifiers` instead of `css_class`
- `_identify_message_pairs()` - pairing logic
- `_build_message_hierarchy()` - but uses `type` and `modifiers` instead of `css_class`
- `_reorder_paired_messages()` - reordering logic
- Deduplication logic
- Token aggregation

### 4. Migration Strategy

The migration will be done in phases to minimize disruption:

**Phase 12a: Add MessageModifiers**
- Add `MessageModifiers` dataclass to `models.py`
- Add `modifiers` field to `TemplateMessage`
- Keep `css_class` field for backward compatibility

**Phase 12b: Populate Modifiers**
- Update all TemplateMessage creation sites to set `modifiers`
- Replace `"x" in css_class` checks with `modifiers.is_x`

**Phase 12c: Create html_renderer.py**
- Move `escape_html()`, `render_markdown()` to html_renderer.py
- Create `css_class_from_message()` function
- Move tool formatters to html_renderer.py

**Phase 12d: Update Templates**
- Modify template to call `css_class_from_message(message)`
- Update emoji logic to use modifiers

**Phase 12e: Remove css_class**
- Remove `css_class` parameter from TemplateMessage
- Clean up any remaining references

## Detailed Implementation

### Phase 12a: Add MessageModifiers (models.py)

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class MessageModifiers:
    """Semantic modifiers that affect message display.

    These are format-neutral flags that renderers can use to determine
    how to display a message. HTML renderer converts these to CSS classes,
    text renderer might use them for indentation or formatting.
    """
    is_sidechain: bool = False
    is_slash_command: bool = False
    is_command_output: bool = False
    is_compacted: bool = False
    is_error: bool = False
    is_steering: bool = False
    # System message level (mutually exclusive)
    system_level: Optional[str] = None  # "info", "warning", "error", "hook"
```

Add to TemplateMessage.__init__:
```python
def __init__(
    self,
    message_type: str,  # Will become MessageType
    content_html: str,
    formatted_timestamp: str,
    css_class: str,  # Keep for now, will remove in 12e
    modifiers: Optional[MessageModifiers] = None,  # New
    # ... other params
):
    self.type = message_type
    self.modifiers = modifiers or MessageModifiers()
    # ... rest
```

### Phase 12b: Populate Modifiers

Update each TemplateMessage creation site. Example from `_process_system_message`:

```python
# Before
css_class = f"{message_type}"
if is_sidechain:
    css_class = f"{css_class} sidechain"

# After
modifiers = MessageModifiers(is_sidechain=is_sidechain)
css_class = f"{message_type}"  # Keep for backward compat
if is_sidechain:
    css_class = f"{css_class} sidechain"
```

Update `_get_message_hierarchy_level()`:
```python
# Before
if "sidechain" in css_class:
    ...

# After
def _get_message_hierarchy_level(msg: TemplateMessage) -> int:
    is_sidechain = msg.modifiers.is_sidechain
    msg_type = msg.type

    if msg_type == MessageType.USER and not is_sidechain:
        return 1
    # ...
```

### Phase 12c: Create html_renderer.py

```python
"""HTML-specific rendering utilities.

This module contains all HTML generation code:
- CSS class computation
- HTML escaping
- Markdown rendering
- Tool-specific formatters
"""

from html import escape
from typing import Optional, List
import mistune

from .models import MessageType, MessageModifiers, TemplateMessage


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return escape(text, quote=True)


def render_markdown(text: str) -> str:
    """Convert markdown to HTML."""
    return mistune.html(text)


def css_class_from_message(msg: TemplateMessage) -> str:
    """Generate CSS class string from message type and modifiers.

    This reconstructs the original css_class format for backward
    compatibility with existing CSS and JavaScript.
    """
    parts: List[str] = [msg.type.value if isinstance(msg.type, MessageType) else msg.type]

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


def get_message_emoji(msg: TemplateMessage) -> str:
    """Return appropriate emoji for message type."""
    msg_type = msg.type if isinstance(msg.type, MessageType) else msg.type

    if msg_type == MessageType.SESSION_HEADER:
        return "📋"
    elif msg_type == MessageType.USER:
        return "🤷"
    elif msg_type == MessageType.ASSISTANT:
        return "🤖"
    elif msg_type == MessageType.SYSTEM:
        return "⚙️"
    elif msg_type == MessageType.TOOL_USE:
        return "🛠️"
    elif msg_type == MessageType.TOOL_RESULT:
        if msg.modifiers.is_error:
            return "🚨"
        return "🧰"
    elif msg_type == MessageType.THINKING:
        return "💭"
    elif msg_type == MessageType.IMAGE:
        return "🖼️"
    return ""


# Move format_* tool functions here:
# - format_ask_user_question_tool_content
# - format_todo_write_tool_content
# - format_bash_tool_content
# etc.
```

### Phase 12d: Update Templates

Update transcript.html to use the new functions. Register them as Jinja filters or pass as context:

```python
# In renderer.py when rendering template
from .html_renderer import css_class_from_message, get_message_emoji

template = env.get_template("transcript.html")
html = template.render(
    messages=messages,
    css_class_from_message=css_class_from_message,
    get_message_emoji=get_message_emoji,
    # ...
)
```

Template changes:
```jinja
{# Before #}
<div class='message {{ message.css_class }}{% if message.is_paired %} {{ message.pair_role }}{% endif %}'>

{# After #}
<div class='message {{ css_class_from_message(message) }}{% if message.is_paired %} {{ message.pair_role }}{% endif %}'>
```

### Phase 12e: Remove css_class

Once all references use modifiers:
1. Remove `css_class` parameter from `TemplateMessage.__init__`
2. Remove `self.css_class = css_class`
3. Clean up all `css_class=...` at creation sites
4. Update tests to use modifiers

## Files Changed

| File | Changes |
|------|---------|
| `models.py` | Add `MessageModifiers` dataclass |
| `renderer.py` | Update TemplateMessage, populate modifiers, update hierarchy logic |
| `html_renderer.py` | New file with HTML utilities and css_class_from_message |
| `templates/transcript.html` | Use css_class_from_message filter |
| `test_*.py` | Update tests to use modifiers |

## Testing Strategy

1. **Snapshot tests**: Run after each phase to verify HTML output unchanged
2. **Unit tests for css_class_from_message**: Verify it produces same strings
3. **Unit tests for modifiers**: Test each modifier flag
4. **Integration tests**: Full render with real transcripts

## Commit Plan

1. `Add MessageModifiers dataclass to models.py` (12a)
2. `Add modifiers field to TemplateMessage` (12a)
3. `Populate modifiers in message processing` (12b part 1)
4. `Update hierarchy logic to use modifiers` (12b part 2)
5. `Create html_renderer.py with css_class_from_message` (12c)
6. `Move escape_html and render_markdown to html_renderer` (12c)
7. `Update template to use css_class_from_message` (12d)
8. `Remove css_class field from TemplateMessage` (12e)

## Risk Assessment

- **Low risk**: MessageModifiers is additive, doesn't break existing code
- **Medium risk**: Moving functions to html_renderer.py requires import updates
- **High risk**: Template changes and css_class removal need careful testing

## Estimated Scope

- Phase 12a: ~30 lines added to models.py, ~10 lines to renderer.py
- Phase 12b: ~50 modifications across renderer.py
- Phase 12c: ~200 lines new file, ~200 lines moved from renderer.py
- Phase 12d: ~10 lines template changes
- Phase 12e: ~20 lines removed

Total: Moderate refactoring, ~5-8 commits
