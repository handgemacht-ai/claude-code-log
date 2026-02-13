"""DAG-based message ordering for Claude Code transcripts.

Replaces timestamp-based ordering with parentUuid → uuid graph traversal.
Works at the TranscriptEntry level (before factory/rendering).

See dev-docs/dag.md for the full architecture spec.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from .models import (
    TranscriptEntry,
    SummaryTranscriptEntry,
    QueueOperationTranscriptEntry,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class MessageNode:
    """A deduplicated message in the DAG."""

    uuid: str
    parent_uuid: Optional[str]
    session_id: str
    timestamp: str
    entry: TranscriptEntry
    children_uuids: list[str] = field(default_factory=list)


@dataclass
class SessionDAGLine:
    """A session's ordered chain of unique messages."""

    session_id: str
    uuids: list[str]  # Ordered by parent→child chain traversal
    first_timestamp: str
    parent_session_id: Optional[str] = None
    attachment_uuid: Optional[str] = None  # UUID in parent where this attaches


@dataclass
class JunctionPoint:
    """A message where other sessions fork or continue."""

    uuid: str
    session_id: str  # The session this message belongs to
    target_sessions: list[str] = field(default_factory=list)


@dataclass
class SessionTree:
    """The complete session hierarchy for a project."""

    nodes: dict[str, MessageNode]
    sessions: dict[str, SessionDAGLine]
    roots: list[str]  # Root session IDs (no parent session)
    junction_points: dict[str, JunctionPoint]


# =============================================================================
# Step 1: Load and Index
# =============================================================================


def build_message_index(
    entries: list[TranscriptEntry],
) -> dict[str, MessageNode]:
    """Build a deduplicated message index from transcript entries.

    Skips SummaryTranscriptEntry (no uuid/sessionId) and
    QueueOperationTranscriptEntry (no uuid). For duplicate uuids,
    keeps the entry from the earliest session (by first entry timestamp).
    """
    # First pass: determine earliest timestamp per session
    session_first_ts: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, (SummaryTranscriptEntry, QueueOperationTranscriptEntry)):
            continue
        sid = entry.sessionId
        ts = entry.timestamp
        if sid not in session_first_ts or ts < session_first_ts[sid]:
            session_first_ts[sid] = ts

    # Second pass: build nodes, deduplicating by uuid (earliest session wins)
    nodes: dict[str, MessageNode] = {}
    for entry in entries:
        if isinstance(entry, (SummaryTranscriptEntry, QueueOperationTranscriptEntry)):
            continue
        uuid = entry.uuid
        sid = entry.sessionId
        if uuid in nodes:
            existing = nodes[uuid]
            existing_session_ts = session_first_ts.get(existing.session_id, "")
            new_session_ts = session_first_ts.get(sid, "")
            if new_session_ts < existing_session_ts:
                # Replace with entry from earlier session
                nodes[uuid] = MessageNode(
                    uuid=uuid,
                    parent_uuid=entry.parentUuid,
                    session_id=sid,
                    timestamp=entry.timestamp,
                    entry=entry,
                )
        else:
            nodes[uuid] = MessageNode(
                uuid=uuid,
                parent_uuid=entry.parentUuid,
                session_id=sid,
                timestamp=entry.timestamp,
                entry=entry,
            )

    return nodes


# =============================================================================
# Step 2: Build DAG (parent→children links)
# =============================================================================


def build_dag(nodes: dict[str, MessageNode]) -> None:
    """Populate children_uuids on each node. Mutates nodes in place.

    Warns about orphan nodes (parentUuid points outside loaded data)
    and validates acyclicity.
    """
    # Clear existing children
    for node in nodes.values():
        node.children_uuids = []

    # Build parent→children links
    for node in nodes.values():
        if node.parent_uuid is not None:
            parent = nodes.get(node.parent_uuid)
            if parent is not None:
                parent.children_uuids.append(node.uuid)
            else:
                logger.warning(
                    "Orphan node %s: parentUuid %s not found in loaded data",
                    node.uuid,
                    node.parent_uuid,
                )

    # Validate: no cycles (walk parent chain for each node)
    for node in nodes.values():
        visited: set[str] = set()
        current: Optional[str] = node.uuid
        while current is not None:
            if current in visited:
                logger.warning("Cycle detected in parent chain at uuid %s", current)
                break
            visited.add(current)
            parent = nodes.get(current)
            if parent is None:
                break
            current = parent.parent_uuid


# =============================================================================
# Step 3: Extract Session DAG-lines
# =============================================================================


def extract_session_dag_lines(
    nodes: dict[str, MessageNode],
) -> dict[str, SessionDAGLine]:
    """Extract per-session ordered chains from the DAG.

    For each session, finds the root node (parent_uuid is null or points
    to a different session), then walks forward via children_uuids filtering
    to same-session children.

    Verifies linearity: each node has at most one child in the same session.
    Falls back to timestamp sort if violated.
    """
    # Group nodes by session
    session_nodes: dict[str, list[MessageNode]] = {}
    for node in nodes.values():
        session_nodes.setdefault(node.session_id, []).append(node)

    sessions: dict[str, SessionDAGLine] = {}
    for session_id, snodes in session_nodes.items():
        session_uuids = {n.uuid for n in snodes}

        # Find root(s): nodes whose parent_uuid is null or outside this session
        roots = [
            n
            for n in snodes
            if n.parent_uuid is None or n.parent_uuid not in session_uuids
        ]

        if not roots:
            logger.warning(
                "Session %s: no root found, falling back to timestamp sort",
                session_id,
            )
            sorted_nodes = sorted(snodes, key=lambda n: n.timestamp)
            sessions[session_id] = SessionDAGLine(
                session_id=session_id,
                uuids=[n.uuid for n in sorted_nodes],
                first_timestamp=sorted_nodes[0].timestamp,
            )
            continue

        if len(roots) > 1:
            # Multiple roots - pick the earliest by timestamp
            roots.sort(key=lambda n: n.timestamp)
            logger.warning(
                "Session %s: %d roots found, using earliest (%s)",
                session_id,
                len(roots),
                roots[0].uuid,
            )

        # Walk forward from root, following same-session children
        chain: list[str] = []
        current: Optional[MessageNode] = roots[0]
        linear = True

        while current is not None:
            chain.append(current.uuid)
            # Find children in the same session
            same_session_children = [
                c for c in current.children_uuids if c in session_uuids
            ]
            if len(same_session_children) == 0:
                current = None
            elif len(same_session_children) == 1:
                current = nodes[same_session_children[0]]
            else:
                logger.warning(
                    "Session %s: node %s has %d same-session children, "
                    "linearity violated",
                    session_id,
                    current.uuid,
                    len(same_session_children),
                )
                linear = False
                current = None

        if not linear or len(chain) < len(snodes):
            if len(chain) < len(snodes):
                logger.warning(
                    "Session %s: chain covers %d of %d nodes, "
                    "falling back to timestamp sort",
                    session_id,
                    len(chain),
                    len(snodes),
                )
            sorted_nodes = sorted(snodes, key=lambda n: n.timestamp)
            chain = [n.uuid for n in sorted_nodes]

        first_ts = nodes[chain[0]].timestamp
        sessions[session_id] = SessionDAGLine(
            session_id=session_id,
            uuids=chain,
            first_timestamp=first_ts,
        )

    return sessions


# =============================================================================
# Step 4: Build Session Tree
# =============================================================================


def build_session_tree(
    nodes: dict[str, MessageNode],
    sessions: dict[str, SessionDAGLine],
) -> SessionTree:
    """Build the session hierarchy and identify junction points.

    For each session's DAG-line, the first message's parent_uuid determines
    the parent session:
    - null → root session
    - points to node in different session → child of that session
    """
    roots: list[str] = []
    junction_points: dict[str, JunctionPoint] = {}

    for session_id, dag_line in sessions.items():
        if not dag_line.uuids:
            roots.append(session_id)
            continue

        first_uuid = dag_line.uuids[0]
        first_node = nodes[first_uuid]
        parent_uuid = first_node.parent_uuid

        if parent_uuid is None or parent_uuid not in nodes:
            # Root session (or orphan parent)
            roots.append(session_id)
            dag_line.parent_session_id = None
            dag_line.attachment_uuid = None
        else:
            parent_node = nodes[parent_uuid]
            if parent_node.session_id == session_id:
                # Parent is in same session - this is a root
                roots.append(session_id)
                dag_line.parent_session_id = None
                dag_line.attachment_uuid = None
            else:
                # Child session: attaches to parent session at parent_uuid
                dag_line.parent_session_id = parent_node.session_id
                dag_line.attachment_uuid = parent_uuid

                # Record junction point
                if parent_uuid not in junction_points:
                    junction_points[parent_uuid] = JunctionPoint(
                        uuid=parent_uuid,
                        session_id=parent_node.session_id,
                    )
                junction_points[parent_uuid].target_sessions.append(session_id)

    # Order roots chronologically
    roots.sort(key=lambda sid: sessions[sid].first_timestamp)

    # Order junction point target_sessions chronologically
    for jp in junction_points.values():
        jp.target_sessions.sort(key=lambda sid: sessions[sid].first_timestamp)

    return SessionTree(
        nodes=nodes,
        sessions=sessions,
        roots=roots,
        junction_points=junction_points,
    )


# =============================================================================
# Step 5: Ordered Traversal
# =============================================================================


def traverse_session_tree(tree: SessionTree) -> list[TranscriptEntry]:
    """Depth-first traversal of session tree producing rendering order.

    For each session: yields its DAG-line's entries in chain order.
    Children are visited in chronological order (by first_timestamp).
    """
    result: list[TranscriptEntry] = []
    visited_sessions: set[str] = set()

    def _visit_session(session_id: str) -> None:
        if session_id in visited_sessions:
            return
        visited_sessions.add(session_id)

        dag_line = tree.sessions.get(session_id)
        if dag_line is None:
            return

        # Build map: attachment_uuid → [child session IDs] for this session
        children_at: dict[str, list[str]] = {}
        for sid, sline in tree.sessions.items():
            if sline.parent_session_id == session_id and sline.attachment_uuid:
                children_at.setdefault(sline.attachment_uuid, []).append(sid)

        # Emit entries, visiting child sessions at junction points
        for uuid in dag_line.uuids:
            node = tree.nodes[uuid]
            result.append(node.entry)
            # After emitting this message, visit any child sessions
            # that attach here (in chronological order)
            if uuid in children_at:
                for child_sid in children_at[uuid]:
                    _visit_session(child_sid)

    # Visit root sessions in chronological order
    for root_sid in tree.roots:
        _visit_session(root_sid)

    return result


# =============================================================================
# Convenience: Full Pipeline
# =============================================================================


def build_dag_from_entries(
    entries: list[TranscriptEntry],
) -> SessionTree:
    """Build a complete SessionTree from raw transcript entries.

    Convenience function that runs Steps 1-4 in sequence.
    """
    nodes = build_message_index(entries)
    build_dag(nodes)
    sessions = extract_session_dag_lines(nodes)
    return build_session_tree(nodes, sessions)
