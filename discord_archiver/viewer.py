from __future__ import annotations

import json
import mimetypes
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .media import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT
from .render import CHAT_CSS, emoji_sources, render_article
from .util import channel_dir, channel_id_from_folder, display_name, format_timestamp, is_snowflake, read_json, read_jsonl

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("video/webm", ".webm")

VIEWER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Discord archiver</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; height: 100vh; display: grid; grid-template-columns: 280px 1fr; font: 15px/1.45 "Segoe UI", sans-serif; background: #1e1f22; color: #dbdee1; }
aside { background: #111214; border-right: 1px solid #2b2d31; display: flex; flex-direction: column; min-height: 0; }
aside header, main header { padding: 14px; border-bottom: 1px solid #2b2d31; }
h1 { margin: 0 0 8px; font-size: 16px; }
input, button { font: inherit; color: inherit; }
#filter, #search { width: 100%; background: #1e1f22; border: 1px solid #2b2d31; border-radius: 6px; padding: 8px; }
#channels { overflow: auto; padding: 6px; }
#channels button { display: block; width: 100%; text-align: left; background: transparent; border: 0; border-radius: 6px; padding: 8px; cursor: pointer; }
#channels button strong { display: block; }
#channels button span { color: #949ba4; font-size: 12px; }
#channels button.active, #channels button:hover { background: #2b2d31; }
main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
main header { display: flex; gap: 12px; align-items: center; }
main header h2 { margin: 0; font-size: 16px; flex: 1; }
#thread { overflow: auto; padding: 12px 16px 32px; }
article { display: grid; grid-template-columns: 42px 1fr; gap: 10px; padding: 8px 0; }
.avatar { width: 42px; height: 42px; border-radius: 50%; background: #3f4248; object-fit: cover; }
.author { font-weight: 650; margin-right: 8px; }
time { color: #949ba4; font-size: 12px; }
.content { white-space: pre-wrap; overflow-wrap: anywhere; }
.files { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.files img, .files video { max-width: min(480px, 100%); max-height: 360px; border-radius: 6px; background: #111; }
.files audio { width: min(480px, 100%); }
.filelink { display: inline-block; padding: 8px 10px; background: #2b2d31; border-radius: 6px; color: #00a8fc; }
a { color: #00a8fc; }
.empty { color: #949ba4; padding: 24px; }
""" + CHAT_CSS + """
</style>
</head>
<body>
<aside>
  <header>
    <h1>Direct messages</h1>
    <input id="filter" placeholder="Filter chats" autocomplete="off">
  </header>
  <div id="channels"></div>
</aside>
<main>
  <header>
    <h2 id="title">Select a chat</h2>
    <input id="search" placeholder="Search saved messages" autocomplete="off">
  </header>
  <div id="thread"><p class="empty">Nothing is uploaded. This is the copy on this computer.</p></div>
</main>
<script>
const channelsEl = document.querySelector("#channels");
const thread = document.querySelector("#thread");
const title = document.querySelector("#title");
let rows = [];
let current = null;
let oldest = null;
let loading = false;
let done = false;

function renderMessage(msg) {
  const wrap = document.createElement("div");
  wrap.innerHTML = msg.html;
  return wrap.firstElementChild;
}

async function loadChannels() {
  rows = await (await fetch("/api/channels")).json();
  drawChannels();
}

function drawChannels() {
  const q = document.querySelector("#filter").value.toLowerCase();
  channelsEl.innerHTML = "";
  for (const row of rows) {
    const label = (row.title || row.id || "").toLowerCase();
    if (q && !label.includes(q)) continue;
    const btn = document.createElement("button");
    btn.className = row.id === current ? "active" : "";
    const strong = document.createElement("strong");
    strong.textContent = row.title || row.id;
    const span = document.createElement("span");
    span.textContent = (row.message_count || 0) + " messages";
    btn.append(strong, span);
    btn.onclick = () => openChannel(row);
    channelsEl.appendChild(btn);
  }
}

async function openChannel(row) {
  current = row.id;
  oldest = null;
  done = false;
  title.textContent = row.title || row.id;
  thread.innerHTML = "";
  drawChannels();
  await more(false);
}

async function more(prepend) {
  if (!current || loading || done) return;
  loading = true;
  const url = "/api/channels/" + current + "/messages?limit=60" + (oldest ? "&before=" + oldest : "");
  const data = await (await fetch(url)).json();
  const batch = (data.messages || []).slice().reverse();
  const frag = document.createDocumentFragment();
  for (const msg of batch) {
    const node = renderMessage(msg);
    if (node) frag.appendChild(node);
  }
  if (prepend) {
    const prev = thread.scrollHeight;
    thread.insertBefore(frag, thread.firstChild);
    thread.scrollTop += thread.scrollHeight - prev;
  } else {
    thread.appendChild(frag);
    thread.scrollTop = thread.scrollHeight;
  }
  oldest = data.oldest || oldest;
  done = !data.has_more;
  if (!batch.length && !prepend) {
    thread.innerHTML = "<p class='empty'>No messages stored in this chat.</p>";
  }
  loading = false;
}

thread.addEventListener("scroll", () => {
  if (thread.scrollTop < 80) more(true);
});
document.querySelector("#filter").addEventListener("input", drawChannels);
document.querySelector("#search").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  const q = event.target.value.trim();
  if (!q) return;
  title.textContent = "Search";
  current = null;
  done = true;
  thread.innerHTML = "<p class='empty'>Searching...</p>";
  const hits = await (await fetch("/api/search?q=" + encodeURIComponent(q))).json();
  thread.innerHTML = "";
  if (!hits.length) {
    thread.innerHTML = "<p class='empty'>No matches.</p>";
    return;
  }
  for (const hit of hits) {
    const article = document.createElement("article");
    const body = document.createElement("div");
    const meta = document.createElement("div");
    const who = document.createElement("span");
    who.className = "author";
    who.textContent = (hit.title || "Chat") + " · " + (hit.author || "");
    const when = document.createElement("time");
    when.textContent = hit.timestamp || "";
    const text = document.createElement("div");
    text.className = "content";
    text.textContent = hit.text || "";
    meta.append(who, when);
    body.append(meta, text);
    article.append(document.createElement("div"), body);
    thread.appendChild(article);
  }
});
loadChannels();
</script>
</body>
</html>
"""


def _file_version(path: Path) -> tuple[str, int, int]:
    try:
        info = path.stat()
    except FileNotFoundError:
        return str(path), 0, 0
    return str(path), info.st_mtime_ns, info.st_size


class ArchiveIndex:
    def __init__(self, archive: Path):
        self.archive = archive.resolve()
        self._lock = threading.Lock()
        self._messages: dict[str, tuple[tuple[str, int, int], list[tuple[int, int]]]] = {}
        self._media: dict[str, tuple[tuple[str, int, int], dict[str, list[dict]]]] = {}

    def message_index(self, channel_id: str) -> list[tuple[int, int]]:
        path = channel_dir(self.archive, channel_id) / "messages.jsonl"
        version = _file_version(path)
        with self._lock:
            cached = self._messages.get(channel_id)
        if cached is not None and cached[0] == version:
            return cached[1]
        best: dict[int, tuple[int, bool]] = {}
        if path.exists():
            with path.open("rb") as handle:
                while True:
                    pos = handle.tell()
                    line = handle.readline()
                    if not line:
                        break
                    if not line.strip():
                        continue
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    mid = str(message.get("id") or "")
                    if not is_snowflake(mid):
                        continue
                    numeric = int(mid)
                    is_api = not message.get("package_only")
                    previous = best.get(numeric)
                    if previous is None or is_api:
                        best[numeric] = (pos, is_api)
        ordered = sorted(((mid, pos) for mid, (pos, _api) in best.items()), reverse=True)
        with self._lock:
            self._messages[channel_id] = (version, ordered)
        return ordered

    def media_for(self, channel_id: str) -> dict[str, list[dict]]:
        path = channel_dir(self.archive, channel_id) / "media.jsonl"
        version = _file_version(path)
        with self._lock:
            cached = self._media.get(channel_id)
        if cached is not None and cached[0] == version:
            return cached[1]
        latest: dict[str, dict] = {}
        order: list[str] = []
        for row in read_jsonl(path):
            if not isinstance(row, dict) or not row.get("key"):
                continue
            key = str(row["key"])
            if key not in latest:
                order.append(key)
            latest[key] = row
        grouped: dict[str, list[dict]] = {}
        for key in order:
            row = latest[key]
            grouped.setdefault(str(row.get("message_id") or ""), []).append(row)
        with self._lock:
            self._media[channel_id] = (version, grouped)
        return grouped


def _safe_file(archive: Path, url_path: str) -> Path | None:
    rel = urllib.parse.unquote(url_path).lstrip("/")
    if not (rel.startswith("channels/") or rel.startswith("avatars/")):
        return None
    parts = Path(rel).parts
    if ".." in parts:
        return None
    root = archive.resolve()
    if len(parts) >= 2 and parts[0] == "channels" and is_snowflake(parts[1]):
        candidate = (channel_dir(archive, parts[1]) / Path(*parts[2:])).resolve()
    else:
        candidate = (archive / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _article(
    channel_id: str,
    message: dict,
    media_items: list[dict],
    avatar: str | None,
    emoji_src: dict[str, str],
) -> str:
    return render_article(
        message,
        media_items,
        emoji_src=emoji_src,
        prefix=f"/channels/{channel_id}/",
        avatar=avatar,
        known_ids={str(message.get("id") or "")},
    )


def _avatar_url(archive: Path, user: dict | None) -> str | None:
    if not isinstance(user, dict) or not is_snowflake(str(user.get("id") or "")):
        return None
    uid = str(user["id"])
    for ext in (".gif", ".png", ".webp"):
        if (archive / "avatars" / f"{uid}{ext}").exists():
            return f"/avatars/{uid}{ext}"
    return None


def list_channels(archive: Path) -> list[dict]:
    rows = []
    root = archive / "channels"
    if not root.exists():
        return rows
    for folder in root.iterdir():
        channel_id = channel_id_from_folder(folder.name)
        if not folder.is_dir() or not channel_id:
            continue
        state = read_json(folder / "channel.json", {})
        if not isinstance(state, dict):
            state = {}
        rows.append(
            {
                "id": state.get("id") or channel_id,
                "title": state.get("title") or channel_id,
                "kind": state.get("kind") or "dm",
                "message_count": state.get("message_count") or 0,
                "newest_timestamp": state.get("newest_timestamp") or "",
            }
        )
    rows.sort(key=lambda row: (row.get("newest_timestamp") or "", row["id"]), reverse=True)
    return rows


def make_handler(archive: Path, index: ArchiveIndex):
    archive = archive.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object, status: int = 200) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(parsed.path)
            query = urllib.parse.parse_qs(parsed.query)
            if path in {"/", "/viewer"}:
                self._send(200, VIEWER_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/channels":
                self._json(list_channels(archive))
                return
            if path == "/api/search":
                from .render import search_archive

                text = (query.get("q") or [""])[0]
                try:
                    limit = min(200, max(1, int((query.get("limit") or ["80"])[0])))
                except ValueError:
                    limit = 80
                self._json(search_archive(archive, text, limit))
                return
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "channels" and parts[3] == "messages":
                channel_id = parts[2]
                if not is_snowflake(channel_id):
                    self._json({"error": "bad channel"}, 400)
                    return
                try:
                    limit = min(100, max(1, int((query.get("limit") or ["60"])[0])))
                except ValueError:
                    limit = 60
                before = (query.get("before") or [None])[0]
                ordered = index.message_index(channel_id)
                if before and is_snowflake(before):
                    cutoff = int(before)
                    ordered = [item for item in ordered if item[0] < cutoff]
                page = ordered[:limit]
                media = index.media_for(channel_id)
                messages = []
                path_jsonl = channel_dir(archive, channel_id) / "messages.jsonl"
                if page and path_jsonl.exists():
                    emoji_src = emoji_sources(media, prefix=f"/channels/{channel_id}/")
                    known_ids = {str(mid) for mid, _pos in index.message_index(channel_id)}
                    with path_jsonl.open("rb") as handle:
                        for mid, pos in page:
                            handle.seek(pos)
                            try:
                                message = json.loads(handle.readline())
                            except json.JSONDecodeError:
                                continue
                            messages.append(
                                {
                                    "id": str(mid),
                                    "html": render_article(
                                        message,
                                        media.get(str(mid), []),
                                        emoji_src=emoji_src,
                                        prefix=f"/channels/{channel_id}/",
                                        avatar=_avatar_url(archive, message.get("author")),
                                        known_ids=known_ids,
                                    ),
                                }
                            )
                self._json(
                    {
                        "messages": messages,
                        "oldest": str(page[-1][0]) if page else None,
                        "has_more": len(ordered) > limit,
                    }
                )
                return
            target = _safe_file(archive, parsed.path)
            if target is None:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            self._send_file(target)

        def _send_file(self, target: Path) -> None:
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            # Only generated previews and known passive media render inline.
            # SVG, HTML attachments, and unknown formats are untrusted documents.
            preview = target.name == "preview.html" and target.parent.parent == archive / "channels"
            attachment = not preview and target.suffix.lower() not in IMAGE_EXT | VIDEO_EXT | AUDIO_EXT
            if attachment:
                content_type = "application/octet-stream"
            size = target.stat().st_size
            start, end, status = 0, size - 1, 200
            range_header = self.headers.get("Range")
            if range_header and range_header.startswith("bytes=") and size:
                spec = range_header.split("=", 1)[1].split(",", 1)[0].strip()
                left, _, right = spec.partition("-")
                try:
                    if left:
                        start = int(left)
                        end = int(right) if right else size - 1
                    elif right:
                        start = max(0, size - int(right))
                        end = size - 1
                    status = 206
                except ValueError:
                    start, end, status = 0, size - 1, 200
            start = max(0, start)
            end = min(end, size - 1)
            if size and (start > end or start >= size):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            length = end - start + 1 if size else 0
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            if attachment:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(target.name, safe=""))
                self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with target.open("rb") as handle:
                    handle.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = handle.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def serve_archive(archive: Path, *, port: int = 8765, open_browser: bool = False) -> ThreadingHTTPServer:
    archive = archive.resolve()
    if not archive.exists():
        raise SystemExit(f"Archive folder does not exist yet: {archive}")
    index = ArchiveIndex(archive)
    handler = make_handler(archive, index)
    last_error: OSError | None = None
    server = None
    chosen = port
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            chosen = candidate
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise SystemExit(f"Could not start the local viewer: {last_error}")
    url = f"http://127.0.0.1:{chosen}/"
    print(f"Archive viewer: {url}", flush=True)
    print("This serves only this computer. Close the window or press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    return server


def serve_forever(archive: Path, *, port: int = 8765, open_browser: bool = True) -> int:
    server = serve_archive(archive, port=port, open_browser=open_browser)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nViewer stopped.")
    finally:
        server.server_close()
    return 0
