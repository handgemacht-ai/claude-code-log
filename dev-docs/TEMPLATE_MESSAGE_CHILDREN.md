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

### Phase 1: Foundation (TODO)
- [ ] Add `children` field to TemplateMessage
- [ ] Keep existing flat-list behavior working
- [ ] Add `flatten()` method for backward compatibility

### Phase 2: Tree Building (TODO)
- [ ] Create `_build_message_tree()` function
- [ ] Return root messages instead of flat list
- [ ] Update child counting to work recursively

### Phase 3: Template Migration (TODO)
- [ ] Create recursive render macro
- [ ] Update DOM structure to use nested `.children` divs
- [ ] Migrate JavaScript fold/unfold

### Challenges & Notes

*To be filled as exploration progresses...*

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
