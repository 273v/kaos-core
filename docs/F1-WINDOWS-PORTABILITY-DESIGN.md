# F1 — kaos-core Windows portability design

> Research + implementation design for the 11 Windows-specific test
> failures surfaced when the cross-OS CI legs landed in commit
> `1b0958f`. The CI legs are gated `experimental: true` so failures
> don't block PRs, but the bugs are real — they would silently break
> kaos-core on Windows for downstream users.
>
> This is a design doc, not an implementation. After review, the work
> splits into 3 self-contained PRs, one per root-cause category.

## 1. Failure inventory

11 tests fail on `windows-latest` / Python 3.13. macOS-arm64 and all
Linux-x64 legs pass. Categorized by root cause:

| Category | Failure count | Symptom |
|---|---|---|
| **A — DiskBackend.list() emits Windows backslash paths** | 5 | `assert [] == ['logs/output.txt']`; downstream `iterdir`, `walk`, `cleanup_context`, VFS list-tool all return empty |
| **B — POSIX file-mode assertions on NTFS** | 5 | `assert 0o600 == 0o666` in `CredentialStore` tests; NTFS ignores POSIX mode bits |
| **C — file:// URI → Path conversion on Windows** | 1 | `Regex pattern did not match` — roots-policy comparison silently lets the access through |

Full failure list:

```
A) tests/unit/test_agent_and_vfs_edges.py::test_disk_vfs_and_file_wrapper
A) tests/unit/test_context_runtime_and_vfs_primitives.py::test_vfs_backends_paths_and_file_operations
A) tests/unit/test_context_runtime_and_vfs_primitives.py::test_context_runtime_resource_and_progress_behaviors  (cascades from A — context.cleanup() relies on list)
A) tests/unit/test_context_runtime_and_vfs_primitives.py::test_vfs_stat_ranges_pages_and_artifacts
A) tests/unit/test_tools.py::TestVFSListTool::test_list_with_files
A) tests/unit/test_vfs_session_isolation.py::test_list_tool_only_lists_caller_session_files

B) tests/unit/test_credentials.py::test_set_writes_file_with_mode_0600
B) tests/unit/test_credentials.py::test_set_overwrite_preserves_mode_0600
B) tests/unit/test_credentials.py::test_set_creates_parent_directory
B) tests/unit/test_credentials.py::test_round_trip_set_get_delete
B) tests/unit/test_credentials.py::test_directory_is_writable_only_by_owner

C) tests/unit/test_context_runtime_and_vfs_primitives.py::test_artifact_roots_and_inline_limits_are_enforced
```

## 2. Category A — DiskBackend.list() emits backslash paths

### 2.1 Root cause

`kaos_core/vfs/backends.py:193-208`:

```python
async def list(self, prefix: str) -> builtins.list[str]:
    normalized = _normalize_relative_path(prefix)

    def _list_files() -> builtins.list[str]:
        return sorted(
            str(child.relative_to(self.base_path))
            for child in self.base_path.rglob("*")
            if child.is_file()
            and (
                not normalized
                or str(child.relative_to(self.base_path)) == normalized
                or str(child.relative_to(self.base_path)).startswith(f"{normalized}/")
            )
        )
```

`child.relative_to(self.base_path)` returns a `pathlib.Path`. `str(Path)`
uses the **native separator**: `\` on Windows, `/` on POSIX.

- On Windows the iteration produces `"logs\\output.txt"`.
- The prefix string the caller built is `"logs/output.txt"` (or
  `"logs/"`), forward-slash by contract — `_normalize_relative_path`
  uses `PurePosixPath` and always emits `/`.
- The string comparisons on line 203–204 (`== normalized`,
  `.startswith(f"{normalized}/")`) never match.
- Result: `list("logs")` returns `[]` on Windows even when files exist.

Every consumer of `list()` is downstream — `walk`, `list_page`,
`cleanup_context`, `VFSPath.iterdir`, `VFSPath.is_dir`,
`VFSPath.rmdir`, `VFSListTool` — so a single fix repairs the whole
chain.

### 2.2 Same hazard, smaller blast radius

The hazard recurs in `VFSMetadata.path` returned by `DiskBackend.stat`
(line 178: `path=normalized`), which is intentionally
forward-slash because `_normalize_relative_path` is used; that's
correct. But returned `entries` from `list()` are not normalized via
that helper — they go straight from `child.relative_to(self.base_path)`
into the result. **Fix point: line 198.**

A second occurrence: the `walk()` machinery in `core.py:166`
(`relative.split("/")`) assumes forward slashes. After fix #2.1, the
input is normalized; this works. No edit needed there.

### 2.3 Proposed fix

Centralize path normalization in `kaos_core/vfs/backends.py`. Replace
the three string-stringifications in `_list_files` with a helper that
forces POSIX form:

```python
def _to_posix(path_obj: Path) -> str:
    """Stringify a Path with forward-slash separators on every OS.

    pathlib.PurePosixPath / PosixPath.as_posix() round-trip — Path on
    Windows preserves backslashes by default; .as_posix() returns the
    canonical POSIX form. Used everywhere the VFS produces an external
    path string so the contract ('paths are POSIX-style') holds across
    platforms.
    """
    return path_obj.as_posix()


# In DiskBackend.list:
async def list(self, prefix: str) -> builtins.list[str]:
    normalized = _normalize_relative_path(prefix)

    def _list_files() -> builtins.list[str]:
        return sorted(
            _to_posix(child.relative_to(self.base_path))
            for child in self.base_path.rglob("*")
            if child.is_file()
            and (
                not normalized
                or _to_posix(child.relative_to(self.base_path)) == normalized
                or _to_posix(child.relative_to(self.base_path)).startswith(f"{normalized}/")
            )
        )
    return await asyncio.to_thread(_list_files)
```

The helper is one line and lives at module scope so it's reusable.
Three call-sites in `_list_files`; all take the helper.

### 2.4 Equally-valid alternative

Use `PurePosixPath`:

```python
str(PurePosixPath(*child.relative_to(self.base_path).parts))
```

This is verbose. `.as_posix()` is the canonical Python idiom and is
single-line per call. Going with `.as_posix()`.

### 2.5 Test additions for category A

Add a regression test that pins the contract directly:

```python
# tests/unit/test_vfs_paths_are_posix.py
async def test_disk_backend_list_returns_posix_separators(tmp_path):
    backend = DiskBackend(tmp_path)
    await backend.write("a/b/c.txt", b"x")
    items = await backend.list("a")
    assert items == ["a/b/c.txt"], items  # NOT a\b\c.txt on Windows
    assert all("\\" not in p for p in items), items
```

This would have caught the bug before the cross-OS legs landed and
runs cheaply on every platform.

## 3. Category B — POSIX file-mode tests on NTFS

### 3.1 Root cause

`os.chmod(path, 0o600)` on Windows is **mostly a no-op**. CPython's
implementation (`Modules/posixmodule.c::os_chmod_impl` for Windows)
only respects the read-only bit (`stat.S_IWRITE`). Group/other
permission bits don't exist on NTFS in any Python-accessible form;
NTFS uses ACLs (Discretionary Access Control Lists) instead.

The result `os.stat(path).st_mode & 0o777` returns:
- `0o666` for a normal writable file on Windows.
- `0o444` for a read-only file (`os.chmod(path, 0o400)` makes the
  file read-only and stat reports `0o444`).

`CredentialStore._save` calls `tmp_path.chmod(0o600)` (`credentials.py:63`).
On Linux/macOS the file ends up `0o600`; on Windows the call is
silently downgraded to "writable" and stat reports `0o666`. Every
test that asserts `mode == 0o600` fails by **438 == 384** (decimal
of 0o666 / 0o600).

### 3.2 Two real fix paths

The 0o600 contract has a real security purpose — keep the credentials
file owner-only. Two ways to honor that on Windows:

**Path B-1 — Windows ACLs via `pywin32`/`win32security`:**

```python
def _harden_credentials_file_windows(path: Path) -> None:
    """Restrict the file's NTFS ACL to the current user only.

    Maps the POSIX 0o600 contract onto Windows: only the owning
    account gets read+write; Authenticated Users / Everyone are
    explicitly denied.
    """
    import win32security  # type: ignore[import-not-found]
    import ntsecuritycon  # type: ignore[import-not-found]

    user, _, _ = win32security.LookupAccountName("", win32security.GetUserName())
    sd = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_WRITE,
        user,
    )
    sd.SetSecurityDescriptorDacl(1, dacl, 0)
    win32security.SetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION, sd)
```

Pros: real security parity with POSIX 0o600.

Cons: adds `pywin32` as a Windows-only runtime dep. `pywin32`
ships pre-compiled wheels for Windows, but the dep tree grows for
`kaos-core` (currently zero non-stdlib runtime deps for the
credentials module). Also requires platform-conditional install:
`pywin32 ; sys_platform == "win32"` in pyproject.toml.

**Path B-2 — Document Windows behavior, skip POSIX assertions:**

`tests/unit/test_credentials.py` skips the mode-bit assertions on
Windows and verifies the *behavior* (file written, atomic replace,
no orphan temp files) instead. The CredentialStore docstring is
updated to call out the platform difference explicitly.

```python
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits not enforced on NTFS")
def test_set_writes_file_with_mode_0600(tmp_path: Path) -> None:
    ...
```

Pros: no new dependencies. Honest about what we actually enforce.

Cons: doesn't actually harden the file on Windows. A determined
local attacker can read the credentials file the same as before
(it's owner-readable, but not exclusively).

### 3.3 Recommended path

**Path B-2** for kaos-core 0.1.0a* (this is the current alpha series).
The current security posture on Windows hasn't actually regressed —
the file was always readable by anyone who can access the user's
profile directory; we just stopped pretending otherwise. Test skip +
docstring update lands in one PR with no new deps.

**Schedule Path B-1 for kaos-core 0.2.0** as a separate hardening
release. The Windows-only `pywin32` dep + ACL implementation is a
focused PR by itself; not entangled with the test-skip work.

The reasoning for the order: the test skip is required either way
(B-1 also wouldn't make the tests pass — it would change the file's
ACL but the POSIX `mode == 0o600` assertion would still fail because
NTFS doesn't expose POSIX modes). So fixing the tests is the
critical path; ACL hardening is the security work we sequence after.

### 3.4 Test changes for category B

For each of the 5 tests that asserts `mode == 0o600`, add:

```python
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX mode bits aren't enforced on NTFS; see B-1 for ACL-based hardening (0.2.0)",
)
```

`test_atomic_write_leaves_no_temp_files` (line 38) doesn't check
mode bits — it checks the temp file got cleaned up. That one **must
stay enabled on Windows** since it pins atomicity, which Windows
preserves (atomic rename works fine on NTFS within a directory).

Add a Windows-specific test that pins the WRITE BEHAVIOR (file
exists, content correct, atomic replace works) without asserting
mode:

```python
def test_set_writes_file_on_windows(tmp_path: Path) -> None:
    """Mode bits aren't checkable on Windows; verify behavior instead."""
    if sys.platform != "win32":
        pytest.skip("Linux/macOS use mode-based tests")
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("kaos-llm", "openai", "default", "sk-test")
    assert target.exists()
    assert json.loads(target.read_text())["kaos-llm"]["openai"]["default"] == "sk-test"
```

## 4. Category C — file:// URI → Path on Windows

### 4.1 Root cause

`kaos_core/artifacts/store.py:161-165`:

```python
def _root_path(self, root: Root) -> Path | None:
    parsed = urlparse(root.uri)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path or "/")).resolve()
```

For a Windows file URI `file:///C:/Users/runner/AppData/Local/Temp/.../vfs/rooted-session`,
`urlparse` gives `parsed.path == "/C:/Users/runner/AppData/Local/Temp/.../vfs/rooted-session"`.

`Path("/C:/Users/...")` on Windows is **not** what you want. pathlib
parses the leading `/` as a root anchor and treats `C:/Users/...` as
a path *under that root*, producing
`WindowsPath("\\C:\\Users\\runner\\AppData\\Local\\Temp\\...\\vfs\\rooted-session")`.
After `.resolve()` Windows tries to anchor that to the current drive,
which silently produces a path that's *plausible* but **doesn't equal**
the path the test will compare against (the path returned from
`vfs.resolve_disk_path`, which goes through pathlib's normal path
join).

When `_assert_roots_allow` then does `resolved_path.relative_to(root_path)`,
the comparison fails (paths look like they're at different locations
because of the spurious leading `\`), `_assert_roots_allow` falls
through to the raise — but here's the catch: the exception message is
the same `"Artifact access denied by roots policy"`. So the test
SHOULD pass on the regex match.

So why does it fail? **Hypothesis**: the bug is a step earlier. The
`allowed_root` URI parses correctly into a path that DOES match
`resolved_path` because both come from `tmp_path / "vfs" / session_id`
on the same Windows leg — they inherit the same backslash artifacts
and happen to align. The `blocked_root` URI parses into a path that's
*also* aligned the wrong way and HAPPENS to be a prefix of (or equal
to) `resolved_path` because of the `\C:\...` parsing artifact. The
check at line 187 (`resolved_path.relative_to(root_path)`) succeeds
when it shouldn't, and `_assert_roots_allow` returns without raising.
Then `pytest.raises(ResourceError, match="roots policy")` fails with
"Regex pattern did not match" because nothing was raised.

I cannot 100% confirm the hypothesis without re-running the test on
Windows with a `print(resolved_path, root_path)` diagnostic. The
hypothesis is consistent with the observed error message and matches
known-bad pathlib-on-Windows behavior with leading-slash URIs.

### 4.2 Proposed fix

Use Python 3.13's `Path.from_uri()` (added in 3.13.0a4) which handles
the Windows `file:///C:/...` form correctly:

```python
def _root_path(self, root: Root) -> Path | None:
    parsed = urlparse(root.uri)
    if parsed.scheme != "file":
        return None
    try:
        return Path.from_uri(root.uri).resolve()
    except ValueError:
        return None
```

`Path.from_uri("file:///C:/foo/bar")` returns `WindowsPath("C:\\foo\\bar")`
on Windows — the leading `/` is stripped before the drive letter.
Same call on POSIX returns `PosixPath("/foo/bar")` which is what the
existing code returns for non-Windows URIs.

Python ≥3.13 is the kaos-core minimum (per pyproject.toml
`requires-python = ">=3.13"`), so `Path.from_uri` is always
available. No version guards needed.

### 4.3 Equally-valid alternative

Manual platform-conditional handling:

```python
def _root_path(self, root: Root) -> Path | None:
    parsed = urlparse(root.uri)
    if parsed.scheme != "file":
        return None
    p = unquote(parsed.path or "/")
    if sys.platform == "win32" and len(p) > 2 and p[0] == "/" and p[2] == ":":
        # /C:/foo -> C:/foo
        p = p[1:]
    return Path(p).resolve()
```

`Path.from_uri()` is cleaner and stdlib-blessed. Going with that.

### 4.4 Test addition

Add a unit test that pins the URI → Path mapping:

```python
def test_root_path_handles_windows_file_uri(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows file:// URI form is platform-specific")
    store = ...  # ArtifactStore instance
    root = Root(uri="file:///C:/Users/test/workspace", name="test")
    p = store._root_path(root)
    assert p == Path("C:/Users/test/workspace").resolve(), p
```

## 5. Cross-cutting: a `kaos_core.utils.pathlib_compat` helper module

Both Category A (POSIX-style stringification) and Category C
(file:// URI → Path) belong in a shared, tested helper module. Three
reasons:

1. The same conversions will recur in `kaos-content`, `kaos-pdf`,
   `kaos-office`, etc. when their cross-OS legs surface similar bugs.
   A monorepo-wide helper avoids re-deriving the right answer.
2. Python's built-ins already do most of the work (`Path.as_posix()`,
   `Path.from_uri()`); the helper is mostly thin wrappers that
   document the contract. Future updates to pathlib (3.14+) only
   need one update site.
3. Tests get a single home for the cross-OS path-handling contract.

### 5.1 Proposed module shape

```python
# kaos_core/utils/pathlib_compat.py

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


def to_posix_str(path: Path | str) -> str:
    """Render a Path or path-like as POSIX-style (forward slashes).

    Use at every external API boundary where the contract is
    'paths are POSIX-style' — VFS list output, log fields, JSON
    schemas, cache keys. Internal cross-platform code can keep
    using Path freely; this is for the *string* form only.

    >>> to_posix_str(Path("a") / "b" / "c")
    'a/b/c'  # both Windows and POSIX
    """
    return Path(path).as_posix() if not isinstance(path, str) else Path(path).as_posix()


def file_uri_to_path(uri: str) -> Path | None:
    """Convert a ``file://`` URI to a native Path on every OS.

    Returns ``None`` for non-file:// URIs. Handles the Windows
    ``file:///C:/foo`` form correctly (Python 3.13+ via
    ``Path.from_uri``).

    >>> file_uri_to_path("file:///home/user/x")  # POSIX
    PosixPath('/home/user/x')
    >>> file_uri_to_path("file:///C:/Users/x")   # Windows
    WindowsPath('C:/Users/x')
    >>> file_uri_to_path("https://example.com/")
    None
    """
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    try:
        return Path.from_uri(uri)
    except ValueError:
        return None
```

### 5.2 Test module

```python
# tests/unit/test_pathlib_compat.py — runs on every OS in the matrix
def test_to_posix_str_handles_path_objects(): ...
def test_to_posix_str_handles_strings(): ...
def test_file_uri_to_path_posix_style(): ...
def test_file_uri_to_path_windows_drive_form(): ...
def test_file_uri_to_path_returns_none_for_non_file(): ...
```

Tests run on all three OSes via the cross-OS matrix; the
Windows-style URI test runs on every OS (Path.from_uri parses any
form regardless of host platform).

## 6. Implementation plan — three independent PRs

| # | Title | Files touched | Risk | Reviewer time |
|---|---|---|---|---|
| F1.1 | Add `kaos_core.utils.pathlib_compat` + cross-OS path tests | new module + new tests | low | 15 min |
| F1.2 | Fix DiskBackend.list backslash bug (Category A) | `vfs/backends.py` + new regression test | low | 20 min |
| F1.3 | Fix file:// URI parsing (Category C) | `artifacts/store.py` + new regression test | low | 15 min |
| F1.4 | Skip POSIX-mode credential tests on Windows; document NTFS posture (Category B) | `tests/unit/test_credentials.py` + `config/credentials.py` docstring | low | 15 min |
| F1.5 (deferred) | NTFS ACL-based credentials hardening | `config/credentials.py` + `pyproject.toml` (add `pywin32 ; sys_platform == "win32"`) | medium | 1-2 hours |

F1.1 lands first (no behavioral change). F1.2/F1.3/F1.4 can land in
any order on top of F1.1 since they're independent surfaces. F1.5
ships with kaos-core 0.2.0.

After F1.1-F1.4 land:
- All 11 currently-failing Windows tests pass (5 fixed, 5 skipped
  with documented reason, 1 fixed).
- `experimental: true` flag on the cross-OS legs can be flipped to
  gating after one clean week of green PRs.

After F1.5 lands:
- The 5 skipped credential tests get a Windows-specific equivalent
  that asserts ACL hardening.

## 7. Out of scope

- Bringing back kaos-content / other repos' Windows test failures;
  same `to_posix_str` helper applies, but those repos are owned by
  their own audits.
- Generalizing the VFS path contract beyond the existing `_normalize_relative_path`
  conventions. The current helper is correct for input handling; this
  doc is about output rendering.
- Path-like *values* in JSON schemas / MCP tool outputs. They already
  go through normalization in most cases; spot-audit during F1.2
  rollout.
- Making the disk VFS backend perform OS-native operations (eg.
  Windows long-path support, junction handling, case-insensitive
  matching). These are valid follow-ups but not required to make the
  current tests pass.

## 8. Risks + mitigations

- **Risk**: `Path.as_posix()` collapses paths like `C:/foo` → `C:/foo`
  on Windows, but if a path ever contains a literal backslash inside
  a filename component (uncommon but legal on POSIX!) the conversion
  is lossy. **Mitigation**: not applicable to VFS paths since
  `_normalize_relative_path` already rejects components with `..` and
  the disk backend uses `rglob("*")` which follows the OS's filename
  rules. No backslash filenames in scope.
- **Risk**: `Path.from_uri()` is Python 3.13.0a4+. **Mitigation**:
  kaos-core requires Python 3.13+ (pyproject.toml). Confirmed safe.
- **Risk**: Skipping mode-bit tests on Windows masks a future
  regression where `os.chmod(0o600)` somehow stops being a no-op. We
  lose the assertion. **Mitigation**: the F1.5 ACL-hardening work
  adds a real Windows-side test that pins owner-only access via
  ACL — covers the regression at a more correct layer.
