"""Cross-platform pathlib helpers.

Centralizes the few pathlib idioms whose POSIX/Windows differences have
bitten the kaos-* family on cross-OS CI:

- ``to_posix_str`` — render any path-like as forward-slash string for
  external APIs whose contract is "paths are POSIX-style" (VFS list
  output, JSON schemas, log fields, cache keys).
- ``file_uri_to_path`` — parse a ``file://`` URI into a native
  :class:`pathlib.Path` correctly on Windows, where ``urlparse`` returns
  ``/C:/foo`` and naive ``Path('/C:/foo')`` mis-anchors the leading slash
  as a drive root.

Both helpers are pure functions; no I/O, no caching. Reuse across
kaos-core / kaos-content / kaos-pdf / etc. when the same hazards recur.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def to_posix_str(path: Path | str) -> str:
    """Return *path* as a POSIX-style string (forward slashes on every OS).

    ``str(Path)`` uses the native separator: ``/`` on POSIX, ``\\`` on
    Windows. Use this helper at every external API boundary whose
    contract is forward-slash paths so the contract holds across
    platforms.

    >>> to_posix_str(Path('a') / 'b' / 'c')
    'a/b/c'
    """
    return Path(path).as_posix()


def file_uri_to_path(uri: str) -> Path | None:
    """Convert a ``file://`` URI to a native :class:`Path` on every OS.

    Returns ``None`` for non-``file://`` URIs. Returns ``None`` for
    malformed file URIs rather than raising — callers that want to
    distinguish "not a file URI" from "malformed" should validate the
    scheme themselves.

    On Windows, ``urlparse('file:///C:/foo').path`` is ``/C:/foo``;
    ``Path('/C:/foo')`` would mis-anchor the leading slash as a drive
    root. This helper strips the leading slash before the drive letter
    so the resulting :class:`Path` is the natural Windows form.
    """
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path_str = unquote(parsed.path or "/")
    if sys.platform == "win32" and len(path_str) > 2 and path_str[0] == "/" and path_str[2] == ":":
        path_str = path_str[1:]
    try:
        return Path(path_str)
    except (ValueError, OSError):
        return None


__all__ = ["file_uri_to_path", "to_posix_str"]
