"""Plugin discovery and dispatch for claude-code-log.

Implements the unified message-transformer plugin system described in
``work/tool-renderer-plugins.md``.

Plugins are discovered via the ``claude_code_log.plugins`` setuptools
entry-point group. Each entry yields a class implementing the
:class:`MessageTransformer` Protocol. The loader sorts transformers by
``(priority, __module__, __qualname__)`` and exposes them to factories
through :func:`apply_transformers`.

v1 scope: transformers run as a *post-classification* pass — each
factory builds its candidate ``MessageContent``, then the loader walks
the priority-ordered transformer list and lets the first matching
transformer (via ``applies_to`` MRO filter) rewrite the candidate.
This deviates slightly from the RFC's "interleaved with built-in
detectors" framing for implementation simplicity; the effect is the
same for every use case the RFC names (clmail hook-demotion, MCP tool
rendering) because plugin transformers always operate on a candidate
that the built-in chain has already classified (typically as
:class:`UserTextMessage` or generic :class:`ToolUseContent`).
"""

from __future__ import annotations

import logging
from importlib.metadata import EntryPoint, entry_points
from typing import (
    Any,
    ClassVar,
    Optional,
    Protocol,
    cast,
    runtime_checkable,
)

from .models import MessageContent, MessageMeta

logger = logging.getLogger(__name__)


# Entry-point group plugins register under.
ENTRY_POINT_GROUP = "claude_code_log.plugins"


@runtime_checkable
class MessageTransformer(Protocol):
    """A plugin contribution that rewrites a parsed ``MessageContent``.

    A transformer matches a candidate by its ``applies_to`` tuple (an
    MRO/subclass check) and, when matched, may return a replacement
    ``MessageContent`` (typically a plugin-defined subclass of one of
    the ``applies_to`` types) or ``None`` to pass through.

    Class attributes ``name``, ``priority``, ``applies_to`` are
    required metadata; the loader validates their presence explicitly
    because ``runtime_checkable`` only verifies method presence.

    See ``work/tool-renderer-plugins.md`` for the design rationale,
    priority table, and worked clmail example.
    """

    name: ClassVar[str]
    priority: ClassVar[int]
    applies_to: ClassVar[tuple[type[MessageContent], ...]]

    def transform(
        self,
        content: MessageContent,
        meta: MessageMeta,
    ) -> Optional[MessageContent]: ...


# ----------------------------------------------------------------------
# Loader (cached at module level so discovery happens once per process)
# ----------------------------------------------------------------------


_cached_transformers: Optional[list[MessageTransformer]] = None


def _validate_transformer_class(cls: type, ep_name: str) -> bool:
    """Return True iff ``cls`` looks like a valid MessageTransformer.

    Required class attributes:

    - ``name``: non-empty str
    - ``priority``: int
    - ``applies_to``: non-empty tuple of MessageContent subclasses

    ``transform`` is verified by the runtime_checkable Protocol on the
    instance; this function checks only the ClassVar metadata.
    """
    # We intentionally introspect arbitrary classes here; pyright can't
    # know their attribute types, so cast to Any for the metadata reads.
    cls_any = cast(Any, cls)
    missing: list[str] = [
        attr for attr in ("name", "priority", "applies_to") if not hasattr(cls, attr)
    ]
    if missing:
        logger.warning(
            "plugin %r (%r) missing required class attribute(s): %s",
            ep_name,
            cls,
            ", ".join(missing),
        )
        return False

    name: Any = cls_any.name
    if not isinstance(name, str) or not name:
        logger.warning("plugin %r: name must be non-empty str (got %r)", ep_name, name)
        return False
    priority: Any = cls_any.priority
    if not isinstance(priority, int):
        logger.warning("plugin %r: priority must be int (got %r)", ep_name, priority)
        return False
    applies_to: Any = cls_any.applies_to
    # All `repr(...)` calls here turn unknown-typed introspection values
    # into plain strings up front, so pyright sees only ``str`` flowing
    # into the logger args (avoids ``reportUnknownArgumentType``).
    if not isinstance(applies_to, tuple) or not applies_to:
        logger.warning(
            "plugin %r: applies_to must be a non-empty tuple (got %s)",
            ep_name,
            repr(cast(object, applies_to)),
        )
        return False
    for t in applies_to:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(t, type) or not issubclass(t, MessageContent):
            logger.warning(
                "plugin %r: applies_to entry %s is not a MessageContent subclass",
                ep_name,
                repr(cast(object, t)),
            )
            return False
    return True


def _load_single(ep: EntryPoint) -> Optional[MessageTransformer]:
    """Load and validate a single entry point. Returns instance or None."""
    try:
        cls = ep.load()
    except Exception as e:  # noqa: BLE001 — surface any load failure as a warning
        logger.warning("failed to load plugin entry point %r: %s", ep.name, e)
        return None
    if not isinstance(cls, type):
        logger.warning(
            "plugin %r: entry point must yield a class (got %r)", ep.name, cls
        )
        return None
    if not _validate_transformer_class(cls, ep.name):
        return None
    try:
        instance = cls()
    except Exception as e:  # noqa: BLE001
        logger.warning("plugin %r: failed to instantiate %r: %s", ep.name, cls, e)
        return None
    if not isinstance(instance, MessageTransformer):
        # Protocol check catches missing transform() method.
        logger.warning(
            "plugin %r: instance does not implement MessageTransformer "
            "(missing transform() method?)",
            ep.name,
        )
        return None
    return instance


def _sort_and_warn(transformers: list[MessageTransformer]) -> list[MessageTransformer]:
    """Sort by (priority, __module__, __qualname__) and warn on collisions.

    Tie-break key uses fully-qualified class identifier so two plugins
    shipping classes with the same short name don't get OS-dependent
    ordering. Collisions on (priority, applies_to) emit a warning.
    """
    transformers = sorted(
        transformers,
        key=lambda t: (t.priority, type(t).__module__, type(t).__qualname__),
    )
    for a, b in zip(transformers, transformers[1:]):
        if a.priority == b.priority and a.applies_to == b.applies_to:
            logger.warning(
                "priority tie for applies_to=%r at priority=%d: "
                "using %s.%s before %s.%s",
                a.applies_to,
                a.priority,
                type(a).__module__,
                type(a).__qualname__,
                type(b).__module__,
                type(b).__qualname__,
            )
    return transformers


def load_transformers(*, force_reload: bool = False) -> list[MessageTransformer]:
    """Discover and return the priority-sorted transformer list.

    Cached at module scope; pass ``force_reload=True`` to re-scan
    (primarily for tests that install/uninstall plugins mid-run).
    """
    global _cached_transformers
    if _cached_transformers is not None and not force_reload:
        return _cached_transformers

    discovered: list[MessageTransformer] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if transformer := _load_single(ep):
            discovered.append(transformer)

    _cached_transformers = _sort_and_warn(discovered)
    return _cached_transformers


def reset_cache() -> None:
    """Clear the loader cache. Used by tests."""
    global _cached_transformers
    _cached_transformers = None


# ----------------------------------------------------------------------
# Dispatch helper for factories
# ----------------------------------------------------------------------


def apply_transformers(
    candidate: MessageContent,
    meta: MessageMeta,
) -> MessageContent:
    """Run transformers against ``candidate``; return the rewrite (or candidate).

    Walks the priority-ordered transformer list, calling ``transform()``
    on the first transformer whose ``applies_to`` matches the
    candidate's class (subclass check). First non-None return wins;
    candidate passes through unchanged if no transformer matches.

    Transformer exceptions are caught and logged at WARNING so a buggy
    plugin doesn't crash the whole conversion; the candidate falls
    through to the next transformer (or out unchanged).
    """
    for transformer in load_transformers():
        if not isinstance(candidate, transformer.applies_to):
            continue
        try:
            replacement = transformer.transform(candidate, meta)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "plugin %r: transform() raised %s on %r; skipping",
                transformer.name,
                type(e).__name__,
                type(candidate).__name__,
            )
            continue
        if replacement is not None:
            return replacement
    return candidate


__all__ = [
    "ENTRY_POINT_GROUP",
    "MessageTransformer",
    "apply_transformers",
    "load_transformers",
    "reset_cache",
]
