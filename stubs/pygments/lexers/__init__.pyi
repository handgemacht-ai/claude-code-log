"""Type stubs for pygments.lexers - minimal stubs for functions used in this project."""

from typing import Any, Iterator

from ..lexer import Lexer

class TextLexer(Lexer):
    """Plain text lexer."""
    def __init__(self, **options: Any) -> None: ...

def get_lexer_by_name(name: str, **options: Any) -> Lexer: ...
def get_all_lexers() -> Iterator[
    tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]
]:
    """Get all registered lexers.

    Returns:
        Iterator of (name, aliases, patterns, mimetypes) tuples
    """
    ...
