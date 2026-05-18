"""Command-line interface for kaos-core.

Runtime inspection and debugging tools for the KAOS platform.

Every command supports --json for structured output (pipe-friendly).
Without --json, output is human-readable.

Usage:
    kaos-core tools list [--json]
    kaos-core tools search QUERY [--category ...] [--capability ...] [--json]
    kaos-core artifacts list [--session SESSION] [--json]
    kaos-core config show [--json]
    kaos-core vfs ls [PATH] [--cursor CURSOR] [--json]
    kaos-core creds list [--module M] [--json]
    kaos-core creds set MODULE SERVICE [KEY]   # value read from stdin
    kaos-core creds delete MODULE SERVICE [KEY]
    kaos-core creds migrate [--dry-run] [--json]
    kaos-core creds tiers [--json]
    kaos-core auth status [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any


def _error(msg: str) -> None:
    """Print error to stderr and exit with non-zero status."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _json_out(data: dict[str, Any]) -> None:
    """Write JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def _cmd_tools_list(args: argparse.Namespace) -> None:
    """List all registered tools."""
    from kaos_core.registry import KaosRuntime

    runtime = KaosRuntime.default()
    metadata_list = runtime.tools.search_tools()

    if args.json:
        tools = [
            {
                "name": m.name,
                "description": m.description,
                "category": str(m.category),
                "capability": str(m.capability),
                "module": m.module_name,
                "version": m.version,
            }
            for m in metadata_list
        ]
        _json_out({"command": "tools list", "total": len(tools), "tools": tools})
        return

    if not metadata_list:
        print("No tools registered.")
        return

    # Human-readable table
    name_width = max(len(m.name) for m in metadata_list)
    cat_width = max(len(str(m.category)) for m in metadata_list)
    cap_width = max(len(str(m.capability)) for m in metadata_list)
    header = (
        f"{'Name':<{name_width}}  {'Category':<{cat_width}}  "
        f"{'Capability':<{cap_width}}  Description"
    )
    print(header)
    print("-" * len(header))
    for m in metadata_list:
        print(
            f"{m.name:<{name_width}}  {m.category!s:<{cat_width}}  "
            f"{m.capability!s:<{cap_width}}  {m.description}"
        )


def _cmd_tools_search(args: argparse.Namespace) -> None:
    """Search registered tools by query, category, and capability."""
    from kaos_core.registry import KaosRuntime
    from kaos_core.types.enums import ToolCapability, ToolCategory

    runtime = KaosRuntime.default()

    category: ToolCategory | None = None
    capability: ToolCapability | None = None
    if args.category:
        try:
            category = ToolCategory(args.category)
        except ValueError:
            valid = ", ".join(v.value for v in ToolCategory)
            _error(f"Invalid category '{args.category}'. Valid: {valid}")
    if args.capability:
        try:
            capability = ToolCapability(args.capability)
        except ValueError:
            valid = ", ".join(v.value for v in ToolCapability)
            _error(f"Invalid capability '{args.capability}'. Valid: {valid}")

    metadata_list = runtime.tools.search_tools(
        query=args.query,
        category=category,
        capability=capability,
    )

    if args.json:
        tools = [
            {
                "name": m.name,
                "description": m.description,
                "category": str(m.category),
                "capability": str(m.capability),
                "module": m.module_name,
                "version": m.version,
            }
            for m in metadata_list
        ]
        _json_out(
            {
                "command": "tools search",
                "query": args.query,
                "total": len(tools),
                "tools": tools,
            }
        )
        return

    if not metadata_list:
        print(f"No tools matching '{args.query}'.")
        return

    name_width = max(len(m.name) for m in metadata_list)
    cat_width = max(len(str(m.category)) for m in metadata_list)
    cap_width = max(len(str(m.capability)) for m in metadata_list)
    header = (
        f"{'Name':<{name_width}}  {'Category':<{cat_width}}  "
        f"{'Capability':<{cap_width}}  Description"
    )
    print(header)
    print("-" * len(header))
    for m in metadata_list:
        print(
            f"{m.name:<{name_width}}  {m.category!s:<{cat_width}}  "
            f"{m.capability!s:<{cap_width}}  {m.description}"
        )


def _cmd_artifacts_list(args: argparse.Namespace) -> None:
    """List artifacts in the store."""
    from kaos_core.registry import KaosRuntime

    runtime = KaosRuntime.default()
    artifacts = runtime.artifacts.list_artifacts(session_id=args.session)

    if args.json:
        items = [
            {
                "artifact_id": a.artifact_id,
                "name": a.name,
                "size": a.size,
                "mime_type": a.mime_type,
                "role": str(a.role),
                "session_id": a.session_id,
                "created_at": a.created_at,
            }
            for a in artifacts
        ]
        _json_out({"command": "artifacts list", "total": len(items), "artifacts": items})
        return

    if not artifacts:
        print("No artifacts found.")
        return

    id_width = max(len(a.artifact_id[:12]) for a in artifacts)
    name_width = max(len(a.name) for a in artifacts)
    header = f"{'ID':<{id_width}}  {'Name':<{name_width}}  {'Size':>10}  {'MIME Type':<30}  Role"
    print(header)
    print("-" * len(header))
    for a in artifacts:
        short_id = a.artifact_id[:12]
        size_str = _format_size(a.size)
        mime = a.mime_type or "(unknown)"
        print(
            f"{short_id:<{id_width}}  {a.name:<{name_width}}  {size_str:>10}  {mime:<30}  {a.role}"
        )


def _format_size(size: int) -> str:
    """Format byte size in human-readable form."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _cmd_config_show(args: argparse.Namespace) -> None:
    """Show current runtime configuration."""
    from kaos_core.registry import KaosRuntime

    runtime = KaosRuntime.default()
    settings = runtime.settings
    settings_dict = settings.model_dump(mode="json")

    if args.json:
        _json_out({"command": "config show", **settings_dict})
        return

    # Human-readable key-value pairs
    key_width = max(len(k) for k in settings_dict)
    for key, value in sorted(settings_dict.items()):
        print(f"{key:<{key_width}}  {value}")


def _cmd_vfs_ls(args: argparse.Namespace) -> None:
    """List VFS contents (async wrapper)."""
    asyncio.run(_cmd_vfs_ls_async(args))


async def _cmd_vfs_ls_async(args: argparse.Namespace) -> None:
    """List VFS contents."""
    from kaos_core.registry import KaosRuntime

    runtime = KaosRuntime.default()
    prefix = args.path or ""
    page = await runtime.vfs.list_page(prefix, limit=100, cursor=args.cursor)

    if args.json:
        _json_out(
            {
                "command": "vfs ls",
                "path": prefix or "/",
                "total": len(page.items),
                "cursor": args.cursor,
                "next_cursor": page.next_cursor,
                "items": page.items,
            }
        )
        return

    if not page.items:
        print(f"No items at '{prefix or '/'}'.")
        return

    for item in page.items:
        print(item)
    if page.next_cursor is not None:
        print(f"\n... more items available (cursor: {page.next_cursor})", file=sys.stderr)


def _build_default_credential_store() -> Any:
    """Construct a :class:`HardenedCredentialStore` with all available tiers.

    Tier wiring: every tier whose extra is installed is included;
    missing extras silently report ``is_available()`` False so they
    don't disrupt CLI operation. ``KAOS_*_DIR`` env overrides are
    respected via the underlying XDG resolver.
    """
    from kaos_core.config.storage import (
        HardenedCredentialStore,
        KeyringStorage,
        PlaintextStorage,
        kaos_state_dir,
    )

    state_dir = kaos_state_dir()
    backends: list[Any] = []

    # Tier 3 — keyring (only included if the extra is installed).
    try:
        import keyring  # noqa: F401
    except ImportError:
        pass
    else:
        backends.append(KeyringStorage())

    # Tier 4 — encrypted file (only included if cryptography is
    # installed AND a passphrase resolver is in scope).
    try:
        from kaos_core.config.storage import EncryptedFileStorage
    except ImportError:
        pass
    else:
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pass
        else:
            backends.append(EncryptedFileStorage())

    # Tier 5 — plaintext (always available).
    backends.append(PlaintextStorage(path=state_dir / "credentials.json"))
    return HardenedCredentialStore(backends=backends)


def _cmd_creds_list(args: argparse.Namespace) -> None:
    """List stored credential service names per tier (no values)."""
    store = _build_default_credential_store()
    rows: list[dict[str, str]] = []
    if args.module:
        modules = [args.module]
    else:
        # Backends scope by module; we don't have a list-modules
        # primitive. Sample the well-known KAOS module namespaces.
        # Adding a new module to the family means adding the name
        # here; the cost is one CLI listing line, not a security or
        # storage decision.
        modules = ["kaos-core", "kaos-content", "kaos-llm", "kaos-source", "kaos-web"]

    for module in modules:
        for service in store.list_services(module):
            tier_for_hit = next(
                (
                    b.tier.name
                    for b in store.backends
                    if b.is_available() and service in b.list_services(module)
                ),
                "?",
            )
            rows.append({"module": module, "service": service, "tier": tier_for_hit})

    if args.json:
        _json_out(
            {"command": "creds list", "active_tier": store.active_tier.name, "credentials": rows}
        )
        return

    if not rows:
        print("(no credentials stored)")
        return
    print(f"{'Module':<20}  {'Service':<20}  Tier")
    print("-" * 60)
    for row in rows:
        print(f"{row['module']:<20}  {row['service']:<20}  {row['tier']}")


def _cmd_creds_set(args: argparse.Namespace) -> None:
    """Store a credential read from stdin so it doesn't appear in shell history."""
    if sys.stdin.isatty():
        try:
            from getpass import getpass

            value = getpass("Value: ")
        except (EOFError, KeyboardInterrupt):
            _error("aborted")
    else:
        value = sys.stdin.read().rstrip("\n")
    if not value:
        _error("empty value; refusing to store")

    store = _build_default_credential_store()
    store.set(args.module, args.service, args.key or "default", value)
    if args.json:
        _json_out(
            {
                "command": "creds set",
                "module": args.module,
                "service": args.service,
                "key": args.key or "default",
                "tier": store.active_tier.name,
            }
        )
        return
    key = args.key or "default"
    print(f"Stored {args.module}/{args.service}/{key} in tier {store.active_tier.name}")


def _cmd_creds_delete(args: argparse.Namespace) -> None:
    """Delete a credential from every tier that holds it."""
    store = _build_default_credential_store()
    store.delete(args.module, args.service, args.key or "default")
    if args.json:
        _json_out(
            {
                "command": "creds delete",
                "module": args.module,
                "service": args.service,
                "key": args.key or "default",
            }
        )
        return
    print(f"Deleted {args.module}/{args.service}/{args.key or 'default'} from every tier")


def _cmd_creds_migrate(args: argparse.Namespace) -> None:
    """Walk stored secrets and promote each to the strongest available tier."""
    store = _build_default_credential_store()
    moved: list[dict[str, str]] = []
    # Walk every backend's list_services for known modules. We
    # don't have a cross-tier enumeration primitive, so use the
    # union of services seen across modules we know about.
    candidate_modules = ["kaos-core", "kaos-llm", "kaos-source", "kaos-web", "kaos-content"]
    for module in candidate_modules:
        for service in store.list_services(module):
            target = store.migrate(module, service, dry_run=args.dry_run)
            if target is not None:
                moved.append(
                    {
                        "module": module,
                        "service": service,
                        "tier": target.name,
                    }
                )

    if args.json:
        _json_out(
            {
                "command": "creds migrate",
                "dry_run": args.dry_run,
                "moved": moved,
                "count": len(moved),
            }
        )
        return
    if not moved:
        print("(no credentials to migrate)")
        return
    verb = "would move" if args.dry_run else "moved"
    for row in moved:
        print(f"{verb} {row['module']}/{row['service']} -> {row['tier']}")


def _cmd_creds_tiers(args: argparse.Namespace) -> None:
    """Report which credential storage tiers are available."""
    store = _build_default_credential_store()
    tiers = [
        {
            "tier": backend.tier.name,
            "available": backend.is_available(),
            "backend": type(backend).__name__,
        }
        for backend in store.backends
    ]
    if args.json:
        _json_out(
            {
                "command": "creds tiers",
                "active_tier": store.active_tier.name,
                "tiers": tiers,
            }
        )
        return
    print(f"Active tier: {store.active_tier.name}")
    print()
    print(f"{'Tier':<20}  {'Backend':<25}  Available")
    print("-" * 60)
    for row in tiers:
        print(f"{row['tier']:<20}  {row['backend']:<25}  {row['available']}")


def _cmd_auth_status(args: argparse.Namespace) -> None:
    """Report stored OAuth tokens (metadata only — never the secret values)."""
    # Walk the credential dispatcher for entries that look like
    # OAuth-token blobs. v1 implementation is conservative: scan
    # for a known module/service pattern and pretty-print metadata.
    # When OAuth integrations land in companion packages, this
    # surface will broaden.
    store = _build_default_credential_store()
    entries: list[dict[str, Any]] = []
    for module in ("kaos-core", "kaos-llm", "kaos-web"):
        for service in store.list_services(module):
            entries.append(
                {
                    "module": module,
                    "service": service,
                    "tier": store.active_tier.name,
                }
            )
    if args.json:
        _json_out(
            {
                "command": "auth status",
                "active_tier": store.active_tier.name,
                "entries": entries,
                "count": len(entries),
            }
        )
        return
    if not entries:
        print("(no stored OAuth tokens detected)")
        return
    for entry in entries:
        print(f"{entry['module']:<20}  {entry['service']:<20}  tier={entry['tier']}")


def main(argv: list[str] | None = None) -> None:
    """Entry point for kaos-core CLI."""
    from kaos_core._version import __version__

    parser = argparse.ArgumentParser(
        prog="kaos-core",
        description="KAOS runtime inspection and debugging tools",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- tools subcommand with nested actions ---
    p_tools = sub.add_parser("tools", help="Tool registry operations")
    tools_sub = p_tools.add_subparsers(dest="action", required=True)

    p_tools_list = tools_sub.add_parser("list", help="List all registered tools")
    p_tools_list.add_argument("--json", action="store_true", help="Structured JSON output")

    p_tools_search = tools_sub.add_parser("search", help="Search tools")
    p_tools_search.add_argument("query", help="Search query")
    p_tools_search.add_argument(
        "--category",
        choices=[v.value for v in _lazy_tool_categories()],
        help="Filter by category",
    )
    p_tools_search.add_argument(
        "--capability",
        choices=[v.value for v in _lazy_tool_capabilities()],
        help="Filter by capability",
    )
    p_tools_search.add_argument("--json", action="store_true", help="Structured JSON output")

    # --- artifacts subcommand ---
    p_artifacts = sub.add_parser("artifacts", help="Artifact store operations")
    artifacts_sub = p_artifacts.add_subparsers(dest="action", required=True)

    p_artifacts_list = artifacts_sub.add_parser("list", help="List artifacts")
    p_artifacts_list.add_argument("--session", help="Filter by session ID")
    p_artifacts_list.add_argument("--json", action="store_true", help="Structured JSON output")

    # --- config subcommand ---
    p_config = sub.add_parser("config", help="Configuration operations")
    config_sub = p_config.add_subparsers(dest="action", required=True)

    p_config_show = config_sub.add_parser("show", help="Show current configuration")
    p_config_show.add_argument("--json", action="store_true", help="Structured JSON output")

    # --- vfs subcommand ---
    p_vfs = sub.add_parser("vfs", help="Virtual file system operations")
    vfs_sub = p_vfs.add_subparsers(dest="action", required=True)

    p_vfs_ls = vfs_sub.add_parser("ls", help="List VFS contents")
    p_vfs_ls.add_argument("path", nargs="?", default="", help="VFS path prefix (default: root)")
    p_vfs_ls.add_argument("--cursor", help="Pagination cursor from a previous vfs ls call")
    p_vfs_ls.add_argument("--json", action="store_true", help="Structured JSON output")

    # --- creds subcommand (F2.5) ---
    p_creds = sub.add_parser("creds", help="Credential store operations (F2 hardened storage)")
    creds_sub = p_creds.add_subparsers(dest="action", required=True)

    p_creds_list = creds_sub.add_parser("list", help="List stored credential names (no values)")
    p_creds_list.add_argument("--module", help="Filter by module name")
    p_creds_list.add_argument("--json", action="store_true", help="Structured JSON output")

    p_creds_set = creds_sub.add_parser(
        "set",
        help="Store a credential. Value is read from stdin so it doesn't appear in shell history.",
    )
    p_creds_set.add_argument("module", help="Module name (e.g. kaos-llm)")
    p_creds_set.add_argument("service", help="Service name (e.g. openai)")
    p_creds_set.add_argument("key", nargs="?", default="default", help="Key (default: 'default')")
    p_creds_set.add_argument("--json", action="store_true", help="Structured JSON output")

    p_creds_delete = creds_sub.add_parser("delete", help="Delete a credential from every tier")
    p_creds_delete.add_argument("module", help="Module name")
    p_creds_delete.add_argument("service", help="Service name")
    p_creds_delete.add_argument(
        "key", nargs="?", default="default", help="Key (default: 'default')"
    )
    p_creds_delete.add_argument("--json", action="store_true", help="Structured JSON output")

    p_creds_migrate = creds_sub.add_parser(
        "migrate", help="Promote stored credentials to the strongest available tier"
    )
    p_creds_migrate.add_argument(
        "--dry-run", action="store_true", help="Report what would move without writing"
    )
    p_creds_migrate.add_argument("--json", action="store_true", help="Structured JSON output")

    p_creds_tiers = creds_sub.add_parser(
        "tiers", help="Report which credential storage tiers are available"
    )
    p_creds_tiers.add_argument("--json", action="store_true", help="Structured JSON output")

    # --- auth subcommand (F2.5) ---
    p_auth = sub.add_parser("auth", help="OAuth credential operations")
    auth_sub = p_auth.add_subparsers(dest="action", required=True)

    p_auth_status = auth_sub.add_parser("status", help="Report stored OAuth tokens (metadata only)")
    p_auth_status.add_argument("--json", action="store_true", help="Structured JSON output")

    args = parser.parse_args(argv)

    handlers: dict[tuple[str, str], Any] = {
        ("tools", "list"): _cmd_tools_list,
        ("tools", "search"): _cmd_tools_search,
        ("artifacts", "list"): _cmd_artifacts_list,
        ("config", "show"): _cmd_config_show,
        ("vfs", "ls"): _cmd_vfs_ls,
        ("creds", "list"): _cmd_creds_list,
        ("creds", "set"): _cmd_creds_set,
        ("creds", "delete"): _cmd_creds_delete,
        ("creds", "migrate"): _cmd_creds_migrate,
        ("creds", "tiers"): _cmd_creds_tiers,
        ("auth", "status"): _cmd_auth_status,
    }

    handler = handlers.get((args.command, args.action))
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


def _lazy_tool_categories() -> list[Any]:
    """Lazily import ToolCategory enum values for argparse choices."""
    from kaos_core.types.enums import ToolCategory

    return list(ToolCategory)


def _lazy_tool_capabilities() -> list[Any]:
    """Lazily import ToolCapability enum values for argparse choices."""
    from kaos_core.types.enums import ToolCapability

    return list(ToolCapability)
