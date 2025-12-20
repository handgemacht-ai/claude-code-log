# Message Refactoring Phase 2

## Vision

The goal is to achieve a cleaner, type-driven architecture where:
1. **MessageContent type is the source of truth** - No need for separate `MessageModifiers` or `MessageType` checks
2. **Inverted relationship** - Instead of `TemplateMessage.content: MessageContent`, have `MessageContent.meta: MessageMetadata`
3. **Leaner models** - Remove derived/redundant fields like `has_children`, `has_markdown`, `is_session_header`, `raw_text_content`
4. **Modular organization** - Split into `user_models.py`, `assistant_models.py`, `tools_models.py` with corresponding parsers

## Current State Analysis

### What we've achieved so far
- Content types now determine behavior (e.g., `UserSlashCommandContent` vs `UserTextContent`)
- Dispatcher pattern routes formatting based on content type
- Removed `ContentBlock` from `ContentItem` union - using our own types
- Simplified `_process_regular_message` - content type detection drives rendering
- **CSS_CLASS_REGISTRY** derives CSS classes from content types (in `html/utils.py`)
- **MessageModifiers removed** - only `is_sidechain` remains as a flag on `TemplateMessage`
- **UserSteeringContent** created for queue-operation "remove" messages

### Remaining goals
- `TemplateMessage` still owns `content` rather than the reverse (inverted relationship)

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

## Modular Organization Plan

### Models split
- `models.py` - Base classes (`MessageContent`, `TranscriptEntry`, etc.)
- `user_models.py` - User message content types
- `assistant_models.py` - Assistant message content types
- `tools_models.py` - Tool use/result models

### Parser split
- `parser.py` - Base parsing, entry point
- `user_parser.py` - User message parsing
- `assistant_parser.py` - Assistant message parsing

### Renderer reorganization
- `renderer.py` - Main message reorganization (`_render_messages`, tree building)
- Move `_process_*` functions to appropriate parser modules

## Related Work

See [REMOVE_ANTHROPIC_TYPES.md](REMOVE_ANTHROPIC_TYPES.md) for simplifying Anthropic SDK dependencies.
