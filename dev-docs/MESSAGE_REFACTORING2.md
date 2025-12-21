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
- **MessageModifiers removed** - only `is_sidechain` remains as a flag on `TemplateMessage`
- **UserSteeringMessage** created for queue-operation "remove" messages
- **IdeNotificationContent** is now a plain dataclass (not a MessageContent subclass)

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

### Remaining Goals

| Goal | Status | Notes |
|------|--------|-------|
| Inverted relationship | ❌ Pending | Still `TemplateMessage.content: MessageContent`, not `MessageContent.meta` |
| Leaner TemplateMessage | ❌ Pending | Still has `has_markdown`, `raw_text_content` |
| Models split | ❌ Pending | Still single `models.py` |

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

## Related Work

See [REMOVE_ANTHROPIC_TYPES.md](REMOVE_ANTHROPIC_TYPES.md) for simplifying Anthropic SDK dependencies.
