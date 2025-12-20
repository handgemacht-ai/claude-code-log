# Remove Anthropic Types Dependency

## Current Usage

### Imports

| Import | File | Purpose |
|--------|------|---------|
| `AnthropicMessage` | models.py, parser.py | Validate message compatibility |
| `AnthropicUsage` | models.py, parser.py | Convert usage info |
| `StopReason` | models.py | Type alias |

### Methods

| Method | Location | Used? |
|--------|----------|-------|
| `to_anthropic_usage()` | UsageInfo (models.py:711) | **Never** |
| `from_anthropic_usage()` | UsageInfo (models.py:725) | Yes, in `normalize_usage_info()` |
| `from_anthropic_message()` | AssistantMessage (models.py:808) | **Never** |

### Call Sites

| Call | Location | Purpose | Needed? |
|------|----------|---------|---------|
| `AnthropicMessage.model_validate()` | parser.py:933 | Validate JSONL data is compatible | **No** - result unused |
| `AnthropicUsage.model_validate()` | parser.py:731 | Parse usage dict as Anthropic type | **No** - can use UsageInfo directly |
| `UsageInfo.from_anthropic_usage()` | parser.py:725, 732 | Convert Anthropic Usage to ours | **Partially** - simplify |

## Simplification Plan

### Phase 1: Remove dead code
1. Remove `to_anthropic_usage()` - never used
2. Remove `from_anthropic_message()` - never used
3. Remove `AnthropicMessage.model_validate()` validation in parser.py - no-op
4. Remove `StopReason` import - just use `Optional[str]`

### Phase 2: Simplify usage parsing
Replace the Anthropic-aware `normalize_usage_info()` with direct dict-to-UsageInfo conversion:
```python
def normalize_usage_info(usage_data: Any) -> Optional[UsageInfo]:
    if usage_data is None:
        return None
    if isinstance(usage_data, UsageInfo):
        return usage_data
    if isinstance(usage_data, dict):
        return UsageInfo.model_validate(usage_data)
    # Handle object-like access for backwards compatibility
    return UsageInfo(
        input_tokens=getattr(usage_data, "input_tokens", None),
        ...
    )
```

### Phase 3: Remove Anthropic imports
After Phase 1-2, remove from models.py and parser.py:
- `from anthropic.types import Message as AnthropicMessage`
- `from anthropic.types import Usage as AnthropicUsage`
- `from anthropic.types import StopReason`

## Benefits

1. **Simpler dependency** - Don't need anthropic SDK types for parsing our own JSONL
2. **Clearer ownership** - Our models are the canonical types, not wrappers
3. **Easier maintenance** - No need to track Anthropic SDK type changes
4. **Smaller models.py** - Less code, clearer structure

## Open Questions

1. **Was there ever a use case for `from_anthropic_message()`?**
   - Possibly for direct SDK integration, but we only parse JSONL files

2. **Why validate against `AnthropicMessage`?**
   - Historical artifact from when we considered using SDK types directly

3. **Could Anthropic types return in content arrays?**
   - We already removed `ContentBlock` from `ContentItem` - no SDK types in content
