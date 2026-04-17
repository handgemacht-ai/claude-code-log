# Phase C: Agent Transcript Rework

## Status: Steps 1-2 Complete (DAG Integration)

## What Changed

### Step 1: Agent Data Shapes (Analysis Complete)

Key findings from real data analysis:

- **Agent entries share `sessionId`** with their parent session
- All agent entries have `isSidechain: true` and `agentId`
- First entry always has `parentUuid: null` (top-level agents)
- Internal `parentUuid` chains form the same fork patterns as main sessions
  (tool-result side-branches)
- `agentId` reference in main session: either entry-level `agentId` (old Task
  tool) or `toolUseResult.agentId` (new Agent tool, copied to entry level by
  converter.py parsing code)

### Step 2: DAG-Level Agent Integration (Implemented)

**`converter.py` — `_integrate_agent_entries()`**:
1. Builds `agentId -> anchor_uuid` map from main-session entries with `agentId`
2. For each sidechain entry: assigns synthetic `sessionId`
   (`{sessionId}#agent-{agentId}`) so agents form separate DAG-lines
3. Parents root entries (`parentUuid=None`) to the anchor UUID

**Effect**: Agent entries are included in the DAG. The existing DAG machinery
(build_dag, extract_session_dag_lines, build_session_tree, traverse_session_tree)
handles them as child sessions of the main session, spliced at the anchor point.

**Key constraint**: `entry.sessionId` on disk / in cache is NEVER mutated.
The synthetic ID is only assigned in-memory during `load_directory_transcripts()`.

### Renderer Changes

- Agent sessions (`#agent-` in session_id) **don't get session headers**
- Agent messages use parent session's `render_session_id` for correct grouping
  in `_reorder_session_template_messages()`
- Agent sessions excluded from session navigation and individual file generation

### What Was Kept

- `_cleanup_sidechain_duplicates()` — still needed for Task tool dedup
  (first user message = Task input, last assistant = Task output).
  This is content-level dedup that can't be handled at the DAG level.
- `sidechain_uuids` parameter in `build_dag()` — still needed for unloaded
  subagent files (e.g. aprompt_suggestion agents never referenced via agentId)

### What Was Removed (Step 4)

- `_reorder_sidechain_template_messages()` — removed. With DAG integration,
  agent messages are already in correct order via DAG traversal. Single-file
  mode now also calls `_integrate_agent_entries()` so both paths use DAG-based
  ordering.

## Remaining Steps

### Step 3: Session Tree Integration (Partially Done)

Agent DAG-lines already appear as child sessions in the tree. The
`traverse_session_tree()` naturally visits them at the junction point.
What's left:
- Verify rendering hierarchy (levels 4/5) works correctly for all cases
- Test with projects that have nested agents (agent spawning sub-agents)

### Step 4: Rendering Cleanup (Done)

- Removed `_reorder_sidechain_template_messages()` — no longer needed with
  DAG-based ordering. Added `_integrate_agent_entries()` to single-file mode
  in `converter.py` so both code paths use consistent DAG integration.
- `_cleanup_sidechain_duplicates()` — kept as-is. Content-level dedup
  (Task input/output duplicated in sidechain) cannot be handled at the DAG
  level since it requires text comparison, not structural ordering.

### Step 5: Agent Tool Renderer (separate PR, `dev/user-sidechain`)

- Specialized rendering for Agent tool_use/tool_result (like old Task tool had)
- Sidechain user messages rendered as markdown (already on `dev/user-sidechain`)

## Test Coverage

4 new integration tests in `TestAgentDagIntegration`:
- `test_agent_entries_parented_to_anchor` — agent root gets parentUuid to anchor
- `test_agent_session_in_tree` — synthetic session created, tree structure correct
- `test_agent_no_session_header` — no session header generated for agents
- `test_multiple_agents_ordered` — multiple agents placed at respective anchors
