# Message Refactoring Phase 2

## Vision

The goal is to achieve a cleaner, type-driven architecture where:
1. **MessageContent type is the source of truth** - No need for separate `MessageModifiers` or `MessageType` checks
2. **Inverted relationship** - Instead of `TemplateMessage.content: MessageContent`, have `MessageContent.meta: MessageMeta`
3. **Leaner models** - Remove derived/redundant fields like `has_children`, `has_markdown`, `is_session_header`, `raw_text_content`
4. **Modular organization** - Split into `user_models.py`, `assistant_models.py`, `tools_models.py` with corresponding factories

## Current State Analysis

### What we've achieved ✓

- **Content types now determine behavior** (e.g., `UserSlashCommandMessage` vs `UserTextMessage`)
- **Dispatcher pattern** routes formatting based on content type
- **Removed `ContentBlock`** from `ContentItem` union - using our own types
- **Simplified `_process_regular_message`** - content type detection drives rendering
- **CSS_CLASS_REGISTRY** derives CSS classes from content types (in `html/utils.py`)
- **MessageModifiers removed** - only `is_sidechain` remains as a flag on `MessageMeta`
- **UserSteeringMessage** created for queue-operation "remove" messages
- **IdeNotificationContent** is now a plain dataclass (not a MessageContent subclass)
- **Inverted relationship achieved** - `MessageContent.meta` is the source of truth, `TemplateMessage.meta = content.meta`
- **Leaner TemplateMessage** - `has_markdown` delegates to content, `raw_text_content` moved to content classes
- **Title dispatch pattern** - `Renderer.title_content()` dispatches to `title_{ClassName}` methods

### Factory Organization ✓

Completed reorganization from parsers to factories:

```
factories/
├── __init__.py           # Re-exports all public symbols
├── meta_factory.py       # create_meta(transcript) -> MessageMeta
├── system_factory.py     # create_system_message()
├── user_factory.py       # create_user_message(), create_*_message()
├── assistant_factory.py  # create_assistant_message(), create_thinking_message()
├── tool_factory.py       # create_tool_use_message(), create_tool_result_message()
└── transcript_factory.py # create_transcript_entry(), create_content_item()
```

### MessageMeta as Required First Parameter ✓

All factory functions now require `MessageMeta` as the first positional parameter:

```python
def create_user_message(meta: MessageMeta, content_list: list[ContentItem], ...) -> ...
def create_assistant_message(meta: MessageMeta, items: list[ContentItem]) -> ...
def create_tool_use_message(meta: MessageMeta, tool_item: ContentItem, ...) -> ...
def create_tool_result_message(meta: MessageMeta, tool_item: ContentItem, ...) -> ...
def create_thinking_message(meta: MessageMeta, tool_item: ContentItem) -> ...
```

This ensures every `MessageContent` subclass has valid metadata.

### Goals Status

| Goal | Status | Notes |
|------|--------|-------|
| Inverted relationship | ✅ Done | `MessageContent.meta` is source of truth, `TemplateMessage.meta = content.meta` |
| Leaner TemplateMessage | ✅ Done | `has_markdown` delegates to content, `raw_text_content` on content classes |
| Title dispatch | ✅ Done | `Renderer.title_content()` with `title_{ClassName}` methods |
| Pure MessageContent | ✅ Done | MessageContent has no render-time fields (relationship data on TemplateMessage) |
| TemplateMessage as primary | ✅ Done | RenderingContext registers TemplateMessage, holds pairing/hierarchy data |
| Models split | ❌ Optional | Still single `models.py` - could split if needed |

### TemplateMessage Architecture ✓

TemplateMessage is now the primary render-time object, with clear separation of concerns:

**MessageContent** (pure transcript data):
- `meta: MessageMeta` - metadata from transcript
- `message_type` property - type identifier
- `has_markdown` property - whether content has markdown

**TemplateMessage** (render-time wrapper):
- `content: MessageContent` - the wrapped content
- `meta = content.meta` - convenience alias
- `message_index: Optional[int]` - index in RenderingContext.messages
- `message_id` property - formatted ID for HTML ("d-{index}" or "session-{id}")
- Pairing fields: `pair_first`, `pair_last`, `pair_duration`
- Pairing properties: `is_paired`, `is_first_in_pair`, `is_last_in_pair`, `pair_role`
- Hierarchy fields: `ancestry`, `children`
- Fold/unfold counts: `immediate_children_count`, `total_descendants_count`, etc.

**RenderingContext**:
- `messages: list[TemplateMessage]` - registry of all messages
- `register(message: TemplateMessage) -> int` - assigns `message_index`
- `get(message_index: int) -> TemplateMessage` - lookup by index
- `tool_use_context: dict[str, ToolUseContent]` - for tool result pairing
- `session_first_message: dict[str, int]` - session header indices

## Cache Considerations

**Good news**: The cache stores `TranscriptEntry` objects (raw parsed data), not `TemplateMessage`:
```python
class CacheManager:
    def load_cached_entries(...) -> Optional[list[TranscriptEntry]]
    def save_cached_entries(...)
```

This means:
- Cache is at the parsing layer, not rendering layer
- Changing `TemplateMessage` structure won't break cache compatibility
- If we store `MessageContent` class names for deserialization, it's a parsing concern

**Feasibility of the inversion**: Yes, because:
1. Cache stores raw transcript entries, not TemplateMessages
2. TemplateMessage is generated fresh from entries on each render
3. The relationship between MessageContent and its metadata is internal to rendering

## Future: Models Split (Optional)

If we decide to split models.py:

- `models.py` - Base classes (`MessageContent`, `TranscriptEntry`, etc.)
- `user_models.py` - User message content types
- `assistant_models.py` - Assistant message content types
- `tools_models.py` - Tool use/result models

This is optional and primarily a code organization improvement.
