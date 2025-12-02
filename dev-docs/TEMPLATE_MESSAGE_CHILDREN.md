# Template Message Children Architecture

This document tracks the exploration of a children-based architecture for `TemplateMessage`, where messages can have nested children to form an explicit tree structure.

## Current Architecture

### TemplateMessage (current)
- Flat list of messages with `message_id` and `ancestry` fields
- Ancestry is a list of parent message IDs (from root to immediate parent)
- Hierarchy is determined by levels based on message type/css_class
- Multiple reordering passes: session → pairs → sidechains → build_hierarchy

### Hierarchy Levels (current)
```
Level 0: Session headers
Level 1: User messages
Level 2: Assistant, System, Thinking
Level 3: Tool use/result
Level 4: Sidechain assistant/thinking
Level 5: Sidechain tools
```

### Template Rendering (current)
- Single `{% for message in messages %}` loop
- Ancestry rendered as CSS classes for JavaScript DOM queries
- Fold/unfold uses `document.querySelectorAll('.message.${targetId}')`

## Proposed Architecture

### TemplateMessage (proposed)
Add `children: List[TemplateMessage]` field to make hierarchy explicit.

```python
class TemplateMessage:
    # ... existing fields ...
    children: List["TemplateMessage"] = []
```

### Tree Building
Replace flat list processing with tree construction:
1. Session headers become root nodes
2. User messages are children of sessions
3. Assistant/System are children of users
4. Tools are children of assistants
5. Sidechains are children of Task tool_results

### Template Rendering (proposed)
Recursive macro approach:
```jinja2
{% macro render_message(message, depth=0) %}
<div class='message {{ message.css_class }}' data-depth='{{ depth }}'>
    <div class='content'>{{ message.content_html | safe }}</div>
    {% if message.children %}
    <div class='children'>
        {% for child in message.children %}
        {{ render_message(child, depth + 1) }}
        {% endfor %}
    </div>
    {% endif %}
</div>
{% endmacro %}
```

### JavaScript Simplification
With nested DOM structure, fold/unfold becomes trivial:
```javascript
// Hide all children
messageEl.querySelector('.children').style.display = 'none';
// Show children
messageEl.querySelector('.children').style.display = '';
```

## Exploration Log

### Phase 1: Foundation ✅ COMPLETE
- [x] Add `children` field to TemplateMessage (commit `7077f68`)
- [x] Keep existing flat-list behavior working
- [x] Add `flatten()` method for backward compatibility (commit `ed4d7b3`)
  - Instance method `flatten()` returns self + all descendants in depth-first order
  - Static method `flatten_all()` flattens list of root messages
  - Unit tests in `test/test_template_data.py::TestTemplateMessageTree`

### Phase 2: Tree Building ✅ COMPLETE
- [x] Create `_build_message_tree()` function (commit `83fcf31`)
  - Takes flat list with `message_id` and `ancestry` already set
  - Populates `children` field based on ancestry
  - Returns list of root messages (those with empty ancestry)
- [x] Called after `_mark_messages_with_children()` in render pipeline
- [x] Root messages stored but flat list still passed to template
- [x] Integration tests verify tree building doesn't break HTML generation

### Phase 3: Template Migration (TODO - Future Work)
- [ ] Create recursive render macro
- [ ] Update DOM structure to use nested `.children` divs
- [ ] Migrate JavaScript fold/unfold
- [ ] Pass `root_messages` to template instead of flat list

### Challenges & Notes

**Current State (2025-12-02):**
- Tree is built internally but not yet used for rendering
- Both data structures exist: flat list (used by template) and tree (populated but unused)
- This allows incremental migration - template can switch to tree rendering later

**Why Keep Both:**
1. Backward compatibility with existing template
2. Can test tree-building logic without breaking rendering
3. `flatten_all()` provides escape hatch if tree rendering has issues

**Performance Consideration:**
- Tree building is O(n) where n = number of messages
- No significant overhead observed in timing logs
- Most time spent in template rendering, not data structure manipulation

## Related Work

### golergka's text-output-format PR
Created `content_extractor.py` for shared content parsing:
- Separates data extraction from presentation
- Dataclasses for extracted content: `ExtractedText`, `ExtractedToolUse`, etc.
- Could be extended for the tree-building approach

### Visitor Pattern Consideration
For multi-format output (HTML, Markdown, JSON), consider:
- TemplateMessage as a tree data structure (no rendering logic)
- Visitor implementations for each output format
- Preparation in converter.py before any rendering
