from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .client import clean_token
from .export import export_archive, list_open_dms, retry_media
from .gui import run_gui
from .render import rebuild_index, search_archive
from .util import configure_stdio, program_path, read_json, write_json
from .viewer import serve_forever


def load_token(token: str | None, token_file: str, *, prompt: bool) -> str:
    if token:
        print("Warning: a token on the command line is saved in shell history. Prefer token.txt.")
        return clean_token(token)
    env = os.environ.get("DISCORD_TOKEN", "").strip()
    if env:
        return clean_token(env)
    path = Path(token_file)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return clean_token(line)
    if prompt and sys.stdin.isatty():
        import getpass

        entered = getpass.getpass("Paste your account token (input hidden): ").strip()
        if entered:
            return clean_token(entered)
    raise SystemExit(
        "No token found. Paste it into token.txt, set DISCORD_TOKEN, or start the window with run.bat.\n"
        "Copy the Authorization value from a discord.com/api request in your browser's Network tab."
    )


def _read_id_file(path: str | None) -> list[str]:
    if not path:
        return []
    file = Path(path)
    if not file.exists():
        raise SystemExit(f"File not found: {file}")
    found = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            found.append(line)
    return found


def _max_bytes(value: float) -> int | None:
    if value <= 0:
        return None
    return int(value * 1024 * 1024)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discord_archiver",
        description="Download your own Discord direct messages and files onto this computer.",
    )
    parser.add_argument("--version", action="version", version=f"discord_archiver {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default="archive", help="Folder to write. Default is the archive folder next to this program.")
    common.add_argument("--token", help="Account token. Prefer token.txt so it is not stored in shell history.")
    common.add_argument("--token-file", default="token.txt", help="Token file. Default is token.txt next to this program.")
    common.add_argument("--delay", type=float, default=1.15, help="Seconds between history requests (default: 1.15)")

    gui = sub.add_parser("gui", help="Open the window")
    gui.add_argument("--out", default="archive")

    export = sub.add_parser("export", parents=[common], help="Download direct messages and files")
    export.add_argument("--open-only", action="store_true", help="Skip closed chats with friends")
    export.add_argument("--leave-reopened", action="store_true", help="Do not hide chats that had to be reopened")
    export.add_argument("--no-media", action="store_true", help="Save message text only")
    export.add_argument("--include-external", action="store_true", help="Also download files hosted outside Discord")
    export.add_argument("--max-file-mb", type=float, default=0, help="Skip files larger than this. 0 means no limit.")
    export.add_argument("--media-workers", type=int, default=4)
    export.add_argument("--only", action="store_true", help="Download only the chats given with --name, --user, or --channel")
    export.add_argument("--name", action="append", default=[], help="Chat name, username, or display name. Repeatable. Implies --only.")
    export.add_argument("--channel", action="append", default=[], help="Channel ID to include. Repeatable. Limits the run when used with --only.")
    export.add_argument("--user", action="append", default=[], help="User ID to include. Repeatable. Limits the run when used with --only.")
    export.add_argument("--channel-file", help="Text file with one channel ID per line")
    export.add_argument("--user-file", help="Text file with one user ID per line")
    export.add_argument("--force", action="store_true", help="Walk history again even if a chat was already finished")

    retry = sub.add_parser("retry-media", parents=[common], help="Download files that failed last time")
    retry.add_argument("--include-external", action="store_true")
    retry.add_argument("--max-file-mb", type=float, default=0)
    retry.add_argument("--media-workers", type=int, default=4)

    listing = sub.add_parser("list", parents=[common], help="Show open direct chats. Does not download them.")
    render = sub.add_parser("render", help="Rebuild index.html and the readable copies")
    render.add_argument("--out", default="archive")
    search = sub.add_parser("search", help="Search saved messages")
    search.add_argument("query")
    search.add_argument("--out", default="archive")
    search.add_argument("--limit", type=int, default=100)
    serve = sub.add_parser("serve", help="Browse the archive in a browser on this computer")
    serve.add_argument("--out", default="archive")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-open", action="store_true")
    fix = sub.add_parser("fix-media", help="Rename mislabeled files and delete extra copies of the same file")
    fix.add_argument("--out", default="archive")
    sub.add_parser("selftest", help="Run offline checks")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.")
        return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "out", None):
        args.out = str(program_path(args.out, "archive"))
    if getattr(args, "token_file", None):
        args.token_file = str(program_path(args.token_file, "token.txt"))
    if args.command == "gui":
        return run_gui(Path(args.out))
    if args.command == "selftest":
        from .selftest import run_selftest

        return run_selftest()
    if args.command == "render":
        from .render import write_channel_views

        archive = Path(args.out)
        root = archive / "channels"
        if root.exists():
            for folder in sorted(path for path in root.iterdir() if path.is_dir()):
                state = read_json(folder / "channel.json", {})
                if isinstance(state, dict):
                    write_channel_views(folder, state)
                    write_json(folder / "channel.json", state)
        rows = rebuild_index(archive)
        print(f"Wrote {archive.resolve() / 'index.html'} ({len(rows)} chats)")
        return 0
    if args.command == "search":
        hits = search_archive(Path(args.out), args.query, args.limit)
        if not hits:
            print("No matches.")
            return 0
        for hit in hits:
            print(f"{hit['timestamp']}  {hit['title']}  {hit['author']}: {hit['text'][:180]}")
        return 0
    if args.command == "serve":
        return serve_forever(Path(args.out), port=args.port, open_browser=not args.no_open)
    if args.command == "fix-media":
        from .media import dedupe_media, repair_media_names

        archive = Path(args.out)
        renamed = repair_media_names(archive)
        removed = dedupe_media(archive)
        print(f"Renamed {renamed} files whose extension did not match their content.")
        print(f"Removed {removed} extra copies of a file already saved.")
        return 0

    token = load_token(getattr(args, "token", None), args.token_file, prompt=sys.stdin.isatty())
    if args.command == "list":
        return list_open_dms(token, delay=args.delay)
    if args.command == "retry-media":
        return retry_media(
            Path(args.out),
            token,
            delay=args.delay,
            include_external=args.include_external,
            max_bytes=_max_bytes(args.max_file_mb),
            workers=max(1, args.media_workers),
        )
    if args.command == "export":
        return export_archive(
            Path(args.out),
            token,
            delay=args.delay,
            with_friends=not args.open_only,
            leave_reopened=args.leave_reopened,
            download_media=not args.no_media,
            include_external=args.include_external,
            max_bytes=_max_bytes(args.max_file_mb),
            workers=max(1, args.media_workers),
            channel_ids=[*args.channel, *_read_id_file(args.channel_file)],
            user_ids=[*args.user, *_read_id_file(args.user_file)],
            names=args.name,
            only=args.only or bool(args.name),
            force=args.force,
        )
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
