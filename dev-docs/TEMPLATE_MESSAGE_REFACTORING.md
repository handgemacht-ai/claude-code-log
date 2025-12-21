# TemplateMessage Simplification Plan

## Goal

Simplify `TemplateMessage` by moving redundant fields to `MessageMeta` (accessible via `content.meta`) and adding properties to `MessageContent` subclasses. This prepares for the eventual replacement of `TemplateMessage` with `MessageContent` directly.

## Completed Changes ✓

### Phase 1: Added `message_type` property to MessageContent subclasses ✓

Added to these subclasses that were missing it:
- `SystemMessage` → returns "system"
- `HookSummaryMessage` → returns "system"
- `ToolResultMessage` → returns "tool_result"
- `ToolUseMessage` → returns "tool_use"
- `UnknownMessage` → returns "unknown"
- `SessionHeaderMessage` → returns "session_header"
- `DedupNoticeMessage` → returns "dedup_notice"

### Phase 2: Added `has_markdown` property ✓

- Added to `MessageContent` base class (returns `False` by default)
- Override in `AssistantTextMessage` → returns `True`
- Override in `ThinkingMessage` → returns `True`
- Override in `CompactedSummaryMessage` → returns `True`

### Phase 3: Skip tool_use_id on base ✓

`tool_use_id` already exists as a field on `ToolUseMessage` and `ToolResultMessage`.
No base class property needed - access via `message.content.tool_use_id` when needed.

### Phase 4: Added `meta` field to TemplateMessage ✓

Added `self.meta = content.meta if content else None` for easy transition.

### Phase 5: Updated template to use new accessors ✓

- Changed `message.is_session_header` → `is_session_header(message)` (helper function)
- Changed `message.has_markdown` → `message.content.has_markdown if message.content else false`
- Removed dead `session_subtitle` code from template
- Added `is_session_header` helper to `html/utils.py` and template context

### Phase 6: Converted parameters to properties ✓

In `TemplateMessage`:
- Removed `is_session_header` parameter, added property that checks `isinstance(self.content, SessionHeaderMessage)`
- Removed `has_markdown` parameter, added property that returns `self.content.has_markdown if self.content else False`
- Removed `session_subtitle` assignment (was never set anyway)
- Removed unused imports (`CompactedSummaryMessage`, `ThinkingMessage`)

## Current TemplateMessage State

### Parameters (in `__init__`)

| Parameter | Status | Notes |
|-----------|--------|-------|
| `message_type` | KEEP | Still used for now |
| `raw_timestamp` | KEEP | Still used |
| `session_summary` | KEEP | Complex async matching |
| `session_id` | KEEP | Still used |
| `token_usage` | KEEP | Formatted display string |
| `tool_use_id` | KEEP | Used for tool messages |
| `title_hint` | KEEP | Used for tooltips |
| `message_title` | KEEP | Display title |
| `message_id` | KEEP | Hierarchy-assigned |
| `ancestry` | KEEP | Parent chain |
| `has_children` | KEEP | Tree structure flag |
| `uuid` | KEEP | Still used |
| `parent_uuid` | KEEP | Still used |
| `agent_id` | KEEP | Still used |
| `is_sidechain` | KEEP | Still used |
| `content` | KEEP | The MessageContent |

### Properties (derived from content)

| Property | Derivation |
|----------|------------|
| `meta` | `content.meta if content else None` |
| `is_session_header` | `isinstance(self.content, SessionHeaderMessage)` |
| `has_markdown` | `self.content.has_markdown if self.content else False` |

### Instance attributes (set after init)

- `raw_text_content` - For deduplication
- Fold/unfold counts and type maps
- Pairing metadata (`is_paired`, `pair_role`, `pair_duration`)
- `children` - Tree structure

## Future Work

The following fields could still be derived from `content.meta` in future refactoring:
- `raw_timestamp` → `content.meta.timestamp`
- `session_id` → `content.meta.session_id`
- `uuid` → `content.meta.uuid`
- `parent_uuid` → `content.meta.parent_uuid`
- `agent_id` → `content.meta.agent_id`
- `is_sidechain` → `content.meta.is_sidechain`
- `message_type` → `content.message_type`
- `message_title` → `content.message_title()`
