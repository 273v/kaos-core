"""Agent-safe path resolution for MCP tools that take file inputs.

Every kaos-* MCP tool that accepts a ``path``/``file``/``source``
parameter from agent input MUST route through :func:`resolve_input_path`
instead of calling raw ``Path(p).exists()``. Without this, files
uploaded into ``KaosRuntime.vfs`` by a UI host (e.g. ``kaos-ui``'s
single-user-chat SPA) are invisible to tools — the agent then sees an
unbroken sequence of "File not found" errors and is at risk of
hallucinating answers from zero successful reads (see the
``vfs-blind-tools-audit-and-fix-plan`` in ``kaos-modules/docs/plans``
for the production post-mortem).

The helper resolves these input shapes that an agent might pass:

1. ``kaos://artifacts/<uuid>``        — artifact-store lookup.
2. ``kaos://<vfs-scheme>/<path>``     — VFS read scoped to ``context.session_id``.
3. ``vfs://<path>``                   — explicit VFS read with no default namespace.
4. ``file:///abs/path``               — direct disk read (CLI / tests / trusted-source flow).
5. bare relative name                 — VFS read inside ``context.default_vfs_namespace``.

Raw absolute filesystem paths without the ``file://`` scheme are rejected.

Returns a :class:`ResolvedInput` async-context-manager. When the input
was a VFS or artifact reference, the bytes are streamed to a temporary
file so third-party readers that only accept ``pathlib.Path``
(pypdfium2, python-docx, python-pptx, openpyxl, calamine, polars,
pdfplumber, etc.) need no rewriting:

.. code-block:: python

    async with resolve_input_path(
        inputs["path"],
        context=context,
        allowed_mime_types=("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    ) as resolved:
        doc = parse_docx(resolved.path)  # resolved.path is a real pathlib.Path

When the input was an explicit ``file://`` absolute filesystem URI the temp-file
copy is skipped and ``resolved.path`` points at the original file.
Cleanup runs unconditionally on context exit (including on
exceptions); the original filesystem file is never deleted.

The resolver enforces session isolation: artifact and VFS reads are
scoped through ``context.session_id``, so a tool can never read an
artifact owned by a different session even if the agent supplies its
URI.
"""

from __future__ import annotations

import os
import re
import tempfile
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.request import url2pathname

from kaos_core.exceptions import KaosCoreError
from kaos_core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from kaos_core.artifacts.models import ArtifactManifest
    from kaos_core.base.context import KaosContext

logger = get_logger(__name__)

# Recognised UUID shape for ``kaos://artifacts/<uuid>``. We accept both
# canonical 8-4-4-4-12 hex (the ArtifactStore default) and a relaxed
# token form for legacy / test artifact ids so we don't reject things
# the artifact store would otherwise resolve.
_ARTIFACT_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
_ARTIFACT_URI_PREFIX = "kaos://artifacts/"
_KAOS_URI_SCHEME = "kaos://"
_VFS_URI_SCHEME = "vfs://"
_FILE_URI_SCHEME = "file://"


class ResolvedOrigin(StrEnum):
    """How the resolver located the bytes for this input."""

    ARTIFACT = "artifact"  # kaos://artifacts/<uuid>
    VFS = "vfs"  # kaos://<other>/... or relative path found in VFS
    FILESYSTEM = "filesystem"  # absolute path / trusted local file


@dataclass(frozen=True, slots=True)
class ResolvedInput:
    """A file the tool can read with any third-party library.

    ``path`` is always a real on-disk ``pathlib.Path``. For artifact /
    VFS inputs the resolver writes the bytes to a private temp file
    (cleaned up on context exit); for filesystem inputs ``path`` is the
    original location and the cleanup hook is a no-op.

    Tools that need more than a filesystem path can read the optional
    metadata: ``artifact_id`` / ``body_uri`` are populated when the
    input originated in the artifact store and can be threaded back
    into the response's ``structuredContent`` so the SPA's
    ``ArtifactCard`` renders the same identifier the user uploaded.
    """

    path: Path
    origin: ResolvedOrigin
    artifact_id: str | None = None
    body_uri: str | None = None
    source_uri: str | None = None
    mime_type: str | None = None
    size: int | None = None
    # Original input the agent supplied (post-strip), useful for echo in errors.
    requested: str = ""
    # Implementation detail — the temp file (if any) the context manager owns.
    _cleanup_path: Path | None = field(default=None, repr=False)


class InputPathResolutionError(KaosCoreError):
    """Tool-input file could not be resolved.

    The exception carries an agent-friendly triple — what went wrong,
    how to fix it, the alternative tool to try — so a tool catch site
    can compose a clean :meth:`ToolResult.create_error` payload without
    leaking pydantic / pathlib / filesystem internals to the LLM.
    """

    def __init__(
        self,
        *,
        what: str,
        how_to_fix: str,
        alternative_tool: str | None = None,
        requested: str = "",
        cause: BaseException | None = None,
    ) -> None:
        self.what = what
        self.how_to_fix = how_to_fix
        self.alternative_tool = alternative_tool
        self.requested = requested
        super().__init__(
            self.to_agent_message(),
            requested=requested,
            cause=str(cause) if cause else None,
        )

    def to_agent_message(self) -> str:
        """Compose the three parts into one chip-friendly string.

        Use this directly as the ``error`` argument to
        ``ToolResult.create_error(...)``. The SPA's ``ToolCallBlock``
        already parses ``{"error": true, "message": ...}`` envelopes
        and surfaces the message verbatim; keep it short and concrete.
        """
        parts = [self.what.rstrip(".")]
        parts.append(f"How to fix: {self.how_to_fix.rstrip('.')}")
        if self.alternative_tool:
            parts.append(f"Alternative: {self.alternative_tool.rstrip('.')}")
        return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@asynccontextmanager
async def resolve_input_path(
    path_or_uri: str,
    *,
    context: KaosContext,
    allowed_mime_types: tuple[str, ...] | None = None,
    max_bytes: int | None = None,
) -> AsyncIterator[ResolvedInput]:
    """Resolve an agent-supplied file/path input to a real on-disk path.

    Resolution order (each step short-circuits on success):

    1. ``kaos://artifacts/<uuid>`` — artifact-store read, scoped to
       ``context.session_id`` so cross-session reads cannot succeed.
       The bytes are streamed to a temp file.
    2. ``kaos://<other>/...`` — treated as a VFS path; same temp-file
       extraction. Used by tools that the agent invokes with a
       VFS-routed reference.
    3. Other relative path — first checked against the VFS scoped to
       the current session. If found, extracted to temp. If not, falls
       through to (4).
    4. ``file:///abs/path`` — checked with ``Path(p).exists()`` and
       returned as-is (no copy). This is the CLI / test / trusted-
       fixture path.
    5. Raw absolute filesystem path without a scheme — rejected with an
       actionable hint to use ``file://`` for trusted local files or a VFS
       relative name for session files.
    6. Bare relative name — resolved through the VFS after prepending
       ``context.default_vfs_namespace`` when one is set.

    Parameters
    ----------
    path_or_uri
        The path / URI / artifact reference the agent supplied. Empty
        string raises immediately with an agent-friendly error.
    context
        ``KaosContext`` for the current turn. Provides ``session_id``
        for VFS / artifact-store scoping and ``runtime`` for the actual
        I/O. Tools that have no context cannot resolve agent inputs
        safely and should raise ``InputPathResolutionError`` with
        ``alternative_tool="kaos-core"`` themselves.
    allowed_mime_types
        Optional tuple of acceptable mime types for the resolved
        artifact. When the resolver knows the mime type (always for
        artifact-store inputs, sometimes for VFS) and the type is not
        in the allowed list, the helper raises with a clear "wrong
        type — try X instead" hint so the agent doesn't see a downstream
        pydantic validation tantrum.
    max_bytes
        Cap on artifact size. Defaults to ``None`` (no cap). When
        provided the helper refuses to materialise files larger than
        the cap and returns a hint to use range reads or the artifact's
        body URI directly.

    Yields
    ------
    ResolvedInput
        Frozen value type carrying the real path + metadata. Tools
        should read ``resolved.path`` (always a real ``pathlib.Path``)
        and may also use ``resolved.artifact_id`` / ``resolved.body_uri``
        when threading provenance into their response's
        ``structuredContent``.

    Raises
    ------
    InputPathResolutionError
        On empty input, unsupported scheme, missing artifact / VFS
        path, mime-type mismatch, or size cap.
    """
    cleanup_path: Path | None = None
    try:
        resolved = await _resolve(
            path_or_uri,
            context=context,
            allowed_mime_types=allowed_mime_types,
            max_bytes=max_bytes,
        )
        cleanup_path = resolved._cleanup_path
        yield resolved
    finally:
        if cleanup_path is not None:
            try:
                cleanup_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "path_resolver: failed to clean up temp file",
                    extra={"path": str(cleanup_path)},
                )


# ---------------------------------------------------------------------------
# Internal resolver
# ---------------------------------------------------------------------------


async def _resolve(
    path_or_uri: str,
    *,
    context: KaosContext,
    allowed_mime_types: tuple[str, ...] | None,
    max_bytes: int | None,
) -> ResolvedInput:
    if not path_or_uri or not isinstance(path_or_uri, str):
        raise InputPathResolutionError(
            what="Empty or non-string path input",
            how_to_fix=(
                "Pass a bare filename (resolved inside the session VFS "
                "default namespace), a kaos://artifacts/<id> URI, a "
                "vfs://<path> or kaos://<vfs-path>, or a file:///abs/path "
                "for an absolute filesystem location"
            ),
            requested=str(path_or_uri or ""),
        )

    stripped = path_or_uri.strip()
    if not stripped:
        raise InputPathResolutionError(
            what="Empty path input after stripping whitespace",
            how_to_fix="Pass a non-empty path or artifact URI",
            requested=path_or_uri,
        )

    # 1. kaos://artifacts/<uuid>
    if stripped.startswith(_ARTIFACT_URI_PREFIX):
        artifact_id = stripped[len(_ARTIFACT_URI_PREFIX) :].strip("/").split("/", 1)[0]
        if not artifact_id or not _ARTIFACT_ID_RE.fullmatch(artifact_id):
            raise InputPathResolutionError(
                what=f"Malformed artifact URI: {stripped!r}",
                how_to_fix=(
                    "Expected kaos://artifacts/<id> where <id> is the UUID "
                    "returned by a previous extract/materialise tool"
                ),
                requested=path_or_uri,
            )
        return await _resolve_artifact(
            artifact_id=artifact_id,
            context=context,
            allowed_mime_types=allowed_mime_types,
            max_bytes=max_bytes,
            requested=path_or_uri,
        )

    # 2. Other kaos:// scheme — treat as VFS read.
    if stripped.startswith(_KAOS_URI_SCHEME):
        parsed = urlparse(stripped)
        # urlparse splits as scheme="kaos", netloc="<bucket>", path="/<rest>"
        # for kaos://content/<id>/body the artifact-id is in netloc+path[0].
        # Heuristic: if the second segment looks like an artifact UUID,
        # delegate to the artifact-store path. Otherwise treat as a VFS
        # read by stripping the scheme.
        candidate_id = parsed.path.lstrip("/").split("/", 1)[0]
        if parsed.netloc in {"artifacts", "content", "tabular"} and _ARTIFACT_ID_RE.fullmatch(
            candidate_id
        ):
            return await _resolve_artifact(
                artifact_id=candidate_id,
                context=context,
                allowed_mime_types=allowed_mime_types,
                max_bytes=max_bytes,
                requested=path_or_uri,
            )
        vfs_path = stripped[len(_KAOS_URI_SCHEME) :]
        return await _resolve_vfs(
            vfs_path,
            context=context,
            allowed_mime_types=allowed_mime_types,
            max_bytes=max_bytes,
            requested=path_or_uri,
        )

    # 3. file:///abs/path  -- explicit absolute filesystem read (CLI / trusted-source).
    if stripped.startswith(_FILE_URI_SCHEME):
        # url2pathname handles both POSIX (file:///abs) and Windows
        # (file:///C:/...) shapes correctly. urlparse alone strips the
        # drive letter on Windows; url2pathname puts it back.
        try:
            parsed = urlparse(stripped)
            # url2pathname expects the path with leading slash on POSIX and
            # /C:/... on Windows. parsed.path is exactly that.
            fs_path = url2pathname(parsed.path) if parsed.path else ""
        except Exception:
            fs_path = ""
        if not fs_path or not _looks_absolute(fs_path):
            raise InputPathResolutionError(
                what=f"Malformed file:// URI: {stripped!r}",
                how_to_fix=(
                    "file:// URIs must encode an absolute path, e.g. "
                    "file:///home/user/contract.pdf (POSIX) or "
                    "file:///C:/Users/me/contract.pdf (Windows). Hosts "
                    "running through an MCP / agent context should prefer "
                    "a VFS-relative name (resolved inside the session's "
                    "default namespace) or kaos://artifacts/<id> instead"
                ),
                requested=path_or_uri,
            )
        return _resolve_filesystem(
            fs_path,
            allowed_mime_types=allowed_mime_types,
            requested=path_or_uri,
        )

    # 4. vfs://<path>  -- explicit VFS read, NO default-namespace prepend.
    if stripped.startswith(_VFS_URI_SCHEME):
        vfs_path = stripped[len(_VFS_URI_SCHEME) :]
        return await _resolve_vfs(
            vfs_path,
            context=context,
            allowed_mime_types=allowed_mime_types,
            max_bytes=max_bytes,
            requested=path_or_uri,
        )

    # 5. Raw absolute path with no scheme -- REJECTED in 0.1.0a10. Tells the
    #    caller exactly how to disambiguate. This closes the
    #    "agent guesses /etc/passwd" foot-gun and forces hosts to opt into
    #    filesystem reads via file://.
    if _looks_absolute(stripped):
        raise InputPathResolutionError(
            what=(
                f"Absolute filesystem path without scheme: {stripped!r}. "
                "The kaos-core path resolver requires an explicit scheme "
                "for filesystem reads in 0.1.0a10+"
            ),
            how_to_fix=(
                "Use file://" + stripped + " if you genuinely need to read "
                "an absolute filesystem path (CLI / trusted-source flow), or "
                "drop the leading '/' and pass a name that resolves inside "
                "the session VFS default namespace"
            ),
            alternative_tool="kaos-core-vfs-list to see what's in the session VFS",
            requested=path_or_uri,
        )

    # 6. Bare name. Prepend the context's default VFS namespace (e.g. "files/"
    #    when the SPA backend has wired one) and resolve through the VFS.
    #    No CWD / absolute-filesystem fallback in 0.1.0a10+.
    #
    # Plan §Issue 7 / #582 idempotency: if the caller already passed an
    # already-namespaced path (e.g. "files/contract.docx" when the
    # namespace is "files/"), do NOT double-prepend it to
    # "files/files/contract.docx". The double-prefix bug was the root
    # cause of every "uploaded NDA not found" P0 in the 2026-05-17 NDA
    # verification matrix. Stripping any leading "./" and the namespace
    # itself before re-applying lets us be lenient on caller hygiene
    # without changing the resolver's contract for bare names.
    namespace = getattr(context, "default_vfs_namespace", "") or ""
    if namespace and stripped.startswith(namespace):
        vfs_lookup = stripped
    elif namespace:
        vfs_lookup = namespace + stripped
    else:
        vfs_lookup = stripped
    return await _resolve_vfs(
        vfs_lookup,
        context=context,
        allowed_mime_types=allowed_mime_types,
        max_bytes=max_bytes,
        requested=path_or_uri,
    )


# ---------------------------------------------------------------------------
# Per-origin resolvers
# ---------------------------------------------------------------------------


async def _resolve_artifact(
    *,
    artifact_id: str,
    context: KaosContext,
    allowed_mime_types: tuple[str, ...] | None,
    max_bytes: int | None,
    requested: str,
) -> ResolvedInput:
    runtime = getattr(context, "runtime", None)
    artifacts = getattr(runtime, "artifacts", None) if runtime is not None else None
    if artifacts is None:
        raise InputPathResolutionError(
            what=(
                f"Cannot resolve artifact {artifact_id!r}: no artifact store "
                "is attached to this runtime"
            ),
            how_to_fix=(
                "Run this tool through a kaos-mcp / kaos-agents server with "
                "an ArtifactStore-backed KaosRuntime"
            ),
            requested=requested,
        )

    try:
        manifest: ArtifactManifest = await artifacts._resolve_async(  # type: ignore[attr-defined]
            artifact_id,
            caller_session_id=context.session_id,
        )
    except Exception as exc:  # pragma: no cover - exact type lives in kaos_core.artifacts
        raise InputPathResolutionError(
            what=f"Artifact {artifact_id!r} not found or not readable",
            how_to_fix=(
                "Verify the artifact id was returned by a previous tool "
                "in this session. Artifacts are session-scoped: an id from "
                "a different session cannot be read"
            ),
            alternative_tool="kaos-core-list-artifacts to enumerate artifacts in this session",
            requested=requested,
            cause=exc,
        ) from exc

    mime_type = manifest.mime_type
    if allowed_mime_types and mime_type and mime_type not in allowed_mime_types:
        raise InputPathResolutionError(
            what=(
                f"Artifact {artifact_id!r} has mime type {mime_type!r}; "
                f"this tool requires one of {list(allowed_mime_types)}"
            ),
            how_to_fix=(
                "Use a tool that matches the artifact's mime type. For "
                "HTML artifacts use kaos-content-parse-html first; for "
                "binary office documents use the matching kaos-office-parse-* tool"
            ),
            requested=requested,
        )

    if max_bytes is not None and manifest.size > max_bytes:
        raise InputPathResolutionError(
            what=(f"Artifact {artifact_id!r} is {manifest.size} bytes (cap: {max_bytes})"),
            how_to_fix=(
                "Read the artifact body in chunks via kaos-core-artifact-read "
                "(start + length parameters) or operate on it directly via "
                "its kaos:// URI instead of materialising the full body"
            ),
            requested=requested,
        )

    body = await artifacts.read_body(
        artifact_id,
        max_bytes=max_bytes,
        caller_session_id=context.session_id,
    )
    suffix = _suffix_from_mime_or_path(mime_type, manifest.path)
    temp_path = _write_temp(body, suffix=suffix)
    return ResolvedInput(
        path=temp_path,
        origin=ResolvedOrigin.ARTIFACT,
        artifact_id=manifest.artifact_id,
        body_uri=getattr(manifest, "body_uri", None) or f"kaos://artifacts/{manifest.artifact_id}",
        source_uri=getattr(manifest, "source_uri", None),
        mime_type=mime_type,
        size=manifest.size,
        requested=requested,
        _cleanup_path=temp_path,
    )


async def _resolve_vfs(
    vfs_path: str,
    *,
    context: KaosContext,
    allowed_mime_types: tuple[str, ...] | None,
    max_bytes: int | None,
    requested: str,
) -> ResolvedInput:
    vfs = getattr(context, "vfs", None)
    if vfs is None:
        raise InputPathResolutionError(
            what=f"Cannot read VFS path {vfs_path!r}: no VFS attached to this context",
            how_to_fix=(
                "Pass an absolute filesystem path instead, or run this tool "
                "through a kaos-mcp / kaos-agents server"
            ),
            requested=requested,
        )

    handle = context.get_vfs_path(vfs_path)
    try:
        exists = await handle.exists()
    except Exception as exc:  # pragma: no cover - VFS backend errors
        raise InputPathResolutionError(
            what=f"VFS lookup for {vfs_path!r} failed",
            how_to_fix=(
                "Verify the VFS path and session scoping. Use an absolute path as a fallback"
            ),
            requested=requested,
            cause=exc,
        ) from exc

    if not exists:
        namespace = getattr(context, "default_vfs_namespace", "") or ""
        ns_hint = (
            f" Note: bare filenames are resolved inside the session's "
            f"default namespace ({namespace!r}). Use vfs://{vfs_path} to "
            "bypass the namespace prefix."
            if namespace
            else ""
        )
        raise InputPathResolutionError(
            what=f"VFS path {vfs_path!r} not found in session {context.session_id!r}",
            how_to_fix=(
                "Verify the file is uploaded to this session. Listing the "
                "session VFS shows what's reachable." + ns_hint
            ),
            alternative_tool="kaos-core-vfs-list to see what's in this session",
            requested=requested,
        )

    if max_bytes is not None:
        try:
            stat = await handle.stat()
            if getattr(stat, "size", 0) > max_bytes:
                raise InputPathResolutionError(
                    what=f"VFS file {vfs_path!r} is {stat.size} bytes (cap: {max_bytes})",
                    how_to_fix="Use a tool that supports range reads, or raise the cap",
                    requested=requested,
                )
        except InputPathResolutionError:
            raise
        except Exception:  # pragma: no cover - missing stat support
            pass

    body = await handle.read_bytes()
    suffix = _suffix_from_path(vfs_path)
    temp_path = _write_temp(body, suffix=suffix)
    mime_type = _guess_mime_from_path(vfs_path)
    if allowed_mime_types and mime_type and mime_type not in allowed_mime_types:
        # Clean up the temp file before raising, since we're not yielding it.
        with suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise InputPathResolutionError(
            what=(
                f"VFS file {vfs_path!r} appears to be {mime_type!r}; "
                f"this tool requires one of {list(allowed_mime_types)}"
            ),
            how_to_fix="Use a tool that matches the file's mime type",
            requested=requested,
        )
    return ResolvedInput(
        path=temp_path,
        origin=ResolvedOrigin.VFS,
        mime_type=mime_type,
        size=len(body),
        requested=requested,
        _cleanup_path=temp_path,
    )


def _resolve_filesystem(
    path_str: str,
    *,
    allowed_mime_types: tuple[str, ...] | None,
    requested: str,
) -> ResolvedInput:
    p = Path(path_str).expanduser()
    if not p.exists():
        raise InputPathResolutionError(
            what=f"Filesystem path {path_str!r} not found",
            how_to_fix=(
                "Pass a path that exists. For SPA-uploaded files use a bare "
                "filename (resolved inside the session VFS default namespace) "
                "or kaos://artifacts/<id>. For absolute local paths use "
                "file:///abs/path"
            ),
            alternative_tool="kaos-core-vfs-list to see what's in this session",
            requested=requested,
        )
    mime_type = _guess_mime_from_path(p)
    if allowed_mime_types and mime_type and mime_type not in allowed_mime_types:
        raise InputPathResolutionError(
            what=(
                f"File {path_str!r} appears to be {mime_type!r}; "
                f"this tool requires one of {list(allowed_mime_types)}"
            ),
            how_to_fix="Use a tool that matches the file's mime type",
            requested=requested,
        )
    try:
        size = p.stat().st_size
    except OSError:
        size = None
    return ResolvedInput(
        path=p,
        origin=ResolvedOrigin.FILESYSTEM,
        mime_type=mime_type,
        size=size,
        requested=requested,
        # _cleanup_path stays None — we never delete user-supplied files.
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _looks_absolute(p: str) -> bool:
    # POSIX: /abs/path
    # Windows drive-letter: C:\... or C:/...
    # Windows UNC / rootless backslash: \\server\share or \abs\path
    if p.startswith(("/", "\\")):
        return True
    return len(p) >= 3 and p[1] == ":" and p[2] in ("/", "\\")


def _write_temp(body: bytes, *, suffix: str = "") -> Path:
    fd, name = tempfile.mkstemp(suffix=suffix, prefix="kaos-input-")
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(body)
    except Exception:
        with suppress(OSError):
            Path(name).unlink()
        raise
    return Path(name)


_MIME_BY_SUFFIX: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".parquet": "application/vnd.apache.parquet",
    ".eml": "message/rfc822",
    ".mbox": "application/mbox",
    ".vcf": "text/vcard",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}


def _guess_mime_from_path(path: str | Path) -> str | None:
    suffix = Path(path).suffix.lower()
    return _MIME_BY_SUFFIX.get(suffix)


def _suffix_from_mime_or_path(mime_type: str | None, path: str | Path | None) -> str:
    # Prefer the path's suffix so third-party readers that key on file
    # extension (most pythonish office readers do) see a familiar one.
    if path:
        suffix = Path(path).suffix
        if suffix:
            return suffix
    if mime_type:
        for ext, mt in _MIME_BY_SUFFIX.items():
            if mt == mime_type:
                return ext
    return ""


def _suffix_from_path(path: str) -> str:
    return Path(path).suffix


__all__ = [
    "InputPathResolutionError",
    "ResolvedInput",
    "ResolvedOrigin",
    "resolve_input_path",
]
