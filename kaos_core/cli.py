"""Command-line interface for kaos-core.

Runtime inspection and debugging tools for the KAOS platform.

Every command supports --json for structured output (pipe-friendly).
Without --json, output is human-readable.

Usage:
    kaos-core tools list [--json]
    kaos-core tools search QUERY [--category ...] [--capability ...] [--json]
    kaos-core artifacts list [--session SESSION] [--json]
    kaos-core config show [--json]
    kaos-core vfs ls [PATH] [--json]
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
    page = await runtime.vfs.list_page(prefix, limit=100)

    if args.json:
        _json_out(
            {
                "command": "vfs ls",
                "path": prefix or "/",
                "total": len(page.items),
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
    p_vfs_ls.add_argument("--json", action="store_true", help="Structured JSON output")

    args = parser.parse_args(argv)

    handlers: dict[tuple[str, str], Any] = {
        ("tools", "list"): _cmd_tools_list,
        ("tools", "search"): _cmd_tools_search,
        ("artifacts", "list"): _cmd_artifacts_list,
        ("config", "show"): _cmd_config_show,
        ("vfs", "ls"): _cmd_vfs_ls,
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
