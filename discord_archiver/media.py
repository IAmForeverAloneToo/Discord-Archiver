from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .util import BROWSER_UA, SEC_CH_UA, human_bytes, read_jsonl, safe_filename

EMOJI_RE = re.compile(r"<(a?):([a-zA-Z0-9_]+):(\d+)>")
STICKER_EXT = {1: "png", 2: "png", 3: "json", 4: "gif"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
AUDIO_EXT = {".ogg", ".mp3", ".wav", ".m4a", ".flac", ".opus"}


@dataclass
class MediaRef:
    message_id: str
    kind: str
    url: str
    filename: str
    key: str
    spoiler: bool = False


def host_allowed(host: str, *, external: bool) -> bool:
    host = (host or "").lower().rstrip(".")
    if any(host == domain or host.endswith("." + domain) for domain in ("discordapp.com", "discordapp.net", "discord.com")):
        return True
    return external


def discord_host(host: str) -> bool:
    return host_allowed(host, external=False)


def sniff_extension(head: bytes) -> str | None:
    """The real format from magic bytes. Discord and embed hosts mislabel files.

    Tenor thumbnails arrive named 'raw' but hold PNG, and some attachment
    thumbnails are named .jpg while containing PNG. Only extensions we are
    sure about are returned; None means leave the name alone.
    """
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"GIF8"):
        return ".gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return ".webp"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    if head[4:8] == b"ftyp":
        return ".mp4"
    if head.startswith(b"OggS"):
        return ".ogg"
    if head.startswith(b"ID3") or head.startswith(b"\xff\xfb"):
        return ".mp3"
    return None


def fix_saved_extension(dest: Path) -> Path:
    """Rename a just-saved file if its bytes contradict its extension, or it has none."""
    try:
        with dest.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return dest
    actual = sniff_extension(head)
    if actual is None or dest.suffix.lower() == actual:
        return dest
    fixed = dest.with_name(dest.stem + actual)
    try:
        # Other workers may be correcting a file to the same basename.
        with _dest_lock(fixed):
            candidate = fixed
            number = 2
            while candidate.exists():
                if candidate.is_file() and candidate.stat().st_size == dest.stat().st_size and _sha256(candidate) == _sha256(dest):
                    dest.unlink()
                    return candidate
                candidate = fixed.with_name(f"{fixed.stem}_{number}{fixed.suffix}")
                number += 1
            dest.replace(candidate)
            fixed = candidate
    except OSError:
        return dest
    return fixed


def filename_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
    return safe_filename(name or "file")


def asset_key(url: str, kind: str = "", key: str = "") -> str:
    """Identity of the file itself, not of the message that mentioned it.

    A reply quotes the original attachment with the same Discord attachment ID.
    The same custom emoji, sticker, or link-preview image can appear on many
    messages. Those are one file, saved once.
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    parts = [part for part in path.split("/") if part]
    trusted = discord_host(parsed.hostname or "")
    if trusted and len(parts) >= 3 and parts[0] == "attachments" and parts[2].isdigit():
        return "attachment:" + parts[2]
    if trusted and len(parts) >= 2 and parts[0] in {"stickers", "emojis"}:
        stem = parts[1].split(".", 1)[0]
        if stem.isdigit():
            kind_name = "sticker" if parts[0] == "stickers" else "emoji"
            return f"{kind_name}:{stem}"
    if not url and key.startswith(("sticker:", "emoji:")):
        tail = key.split(":")[-1]
        if tail.isdigit():
            return f"{key.split(':', 1)[0]}:{tail}"
    if url.startswith("https://"):
        # Query parameters and ports can select completely different files.
        # Only the known Discord IDs above may ignore expiring signatures.
        return "url:" + urllib.parse.urlunparse(parsed._replace(netloc=parsed.netloc.lower(), fragment=""))
    return key or kind or "unknown"


def ref_asset(ref: MediaRef) -> str:
    return asset_key(ref.url, ref.kind, ref.key)


def sticker_url(sticker_id: str, format_type: object) -> str:
    try:
        ext = STICKER_EXT.get(int(format_type), "png")
    except (TypeError, ValueError):
        ext = "png"
    return f"https://cdn.discordapp.com/stickers/{sticker_id}.{ext}"


def emoji_url(emoji_id: str, animated: bool) -> str:
    ext = "gif" if animated else "png"
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=128&quality=lossless"


def avatar_url(user_id: str, avatar_hash: str) -> str:
    ext = "gif" if str(avatar_hash).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=256"


def channel_icon_url(channel_id: str, icon_hash: str) -> str:
    ext = "gif" if str(icon_hash).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/channel-icons/{channel_id}/{icon_hash}.{ext}?size=256"


def _add(refs: list[MediaRef], seen: set[str], ref: MediaRef | None) -> None:
    if ref is None or not ref.url.startswith("https://"):
        return
    if ref.key in seen:
        return
    seen.add(ref.key)
    refs.append(ref)


def _attachment_ref(message_id: str, attachment: dict, kind: str) -> MediaRef | None:
    url = attachment.get("url") or attachment.get("proxy_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    attachment_id = str(attachment.get("id") or filename_from_url(url))
    filename = safe_filename(str(attachment.get("filename") or filename_from_url(url)))
    flags = attachment.get("flags") or 0
    spoiler = bool(isinstance(flags, int) and flags & 8) or filename.upper().startswith("SPOILER_")
    return MediaRef(
        message_id=message_id,
        kind=kind,
        url=url,
        filename=filename,
        key=f"{kind}:{message_id}:{attachment_id}",
        spoiler=spoiler,
    )


def _embed_refs(message_id: str, embed: dict, index: int, *, include_external: bool, seen: set[str], refs: list[MediaRef]) -> None:
    slots = (
        ("image", embed.get("image")),
        ("thumbnail", embed.get("thumbnail")),
        ("video", embed.get("video")),
        ("author", {"url": (embed.get("author") or {}).get("icon_url")} if isinstance(embed.get("author"), dict) else None),
        ("footer", {"url": (embed.get("footer") or {}).get("icon_url")} if isinstance(embed.get("footer"), dict) else None),
    )
    for slot, media in slots:
        if not isinstance(media, dict):
            continue
        url = media.get("url") or media.get("proxy_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        if slot == "video" and "/embed/" in url:
            # A link preview player (YouTube and friends), not a file. The chat
            # keeps the link; there is nothing to download.
            continue
        host = urllib.parse.urlparse(url).hostname or ""
        if not host_allowed(host, external=include_external):
            continue
        _add(
            refs,
            seen,
            MediaRef(
                message_id=message_id,
                kind=f"embed-{slot}",
                url=url,
                filename=filename_from_url(url),
                key=f"embed:{message_id}:{index}:{slot}",
            ),
        )


def _component_refs(message_id: str, components: object, *, include_external: bool, seen: set[str], refs: list[MediaRef]) -> None:
    if not isinstance(components, list):
        return
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            continue
        for field in ("media", "file"):
            media = component.get(field)
            if isinstance(media, dict):
                url = media.get("url") or media.get("proxy_url")
                if isinstance(url, str) and url.startswith("https://"):
                    host = urllib.parse.urlparse(url).hostname or ""
                    if host_allowed(host, external=include_external):
                        _add(
                            refs,
                            seen,
                            MediaRef(
                                message_id=message_id,
                                kind="component",
                                url=url,
                                filename=filename_from_url(url),
                                key=f"component:{message_id}:{index}:{field}",
                            ),
                        )
        items = component.get("items")
        if isinstance(items, list):
            _component_refs(message_id, items, include_external=include_external, seen=seen, refs=refs)
        nested = component.get("components")
        if isinstance(nested, list):
            _component_refs(message_id, nested, include_external=include_external, seen=seen, refs=refs)
        accessory = component.get("accessory")
        if isinstance(accessory, dict):
            _component_refs(message_id, [accessory], include_external=include_external, seen=seen, refs=refs)


def _from_message(
    message: dict,
    message_id: str,
    refs: list[MediaRef],
    seen: set[str],
    *,
    include_external: bool,
    kind_prefix: str = "",
) -> None:
    prefix = f"{kind_prefix}:" if kind_prefix else ""
    for attachment in message.get("attachments") or []:
        if isinstance(attachment, dict):
            ref = _attachment_ref(message_id, attachment, f"{prefix}attachment" if prefix else "attachment")
            if ref is not None and prefix:
                ref.key = prefix + ref.key
            _add(refs, seen, ref)
    for index, embed in enumerate(message.get("embeds") or []):
        if isinstance(embed, dict):
            _embed_refs(message_id, embed, index, include_external=include_external, seen=seen, refs=refs)
    for sticker in message.get("sticker_items") or message.get("stickers") or []:
        if not isinstance(sticker, dict):
            continue
        sticker_id = str(sticker.get("id") or "")
        if not sticker_id.isdigit():
            continue
        url = sticker_url(sticker_id, sticker.get("format_type"))
        name = safe_filename(str(sticker.get("name") or sticker_id))
        ext = url.rsplit(".", 1)[-1]
        _add(
            refs,
            seen,
            MediaRef(
                message_id=message_id,
                kind="sticker",
                url=url,
                filename=f"{name}.{ext}",
                key=f"sticker:{sticker_id}",
            ),
        )
    blobs = [message.get("content") or ""]
    for reaction in message.get("reactions") or []:
        emoji = reaction.get("emoji") if isinstance(reaction, dict) else None
        if isinstance(emoji, dict) and emoji.get("id"):
            animated = "a" if emoji.get("animated") else ""
            blobs.append(f"<{animated}:{emoji.get('name') or 'emoji'}:{emoji['id']}>")
    poll = message.get("poll") if isinstance(message.get("poll"), dict) else None
    if poll:
        for answer in poll.get("answers") or []:
            media = answer.get("poll_media") if isinstance(answer, dict) else None
            emoji = media.get("emoji") if isinstance(media, dict) else None
            if isinstance(emoji, dict) and emoji.get("id"):
                animated = "a" if emoji.get("animated") else ""
                blobs.append(f"<{animated}:{emoji.get('name') or 'emoji'}:{emoji['id']}>")
    for blob in blobs:
        for match in EMOJI_RE.finditer(blob):
            animated, name, emoji_id = match.group(1), match.group(2), match.group(3)
            ext = "gif" if animated else "png"
            _add(
                refs,
                seen,
                MediaRef(
                    message_id=message_id,
                    kind="emoji",
                    url=emoji_url(emoji_id, bool(animated)),
                    filename=f"{safe_filename(name)}.{ext}",
                    key=f"emoji:{emoji_id}",
                ),
            )
    _component_refs(
        message_id,
        message.get("components"),
        include_external=include_external,
        seen=seen,
        refs=refs,
    )


def extract_media(message: dict, *, include_external: bool = False) -> list[MediaRef]:
    message_id = str(message.get("id") or "unknown")
    refs: list[MediaRef] = []
    seen: set[str] = set()
    _from_message(message, message_id, refs, seen, include_external=include_external)
    referenced = message.get("referenced_message")
    if isinstance(referenced, dict):
        _from_message(
            referenced,
            message_id,
            refs,
            seen,
            include_external=include_external,
            kind_prefix="reply",
        )
    for snapshot in message.get("message_snapshots") or []:
        inner = snapshot.get("message") if isinstance(snapshot, dict) else None
        if isinstance(inner, dict):
            _from_message(
                inner,
                message_id,
                refs,
                seen,
                include_external=include_external,
                kind_prefix="forward",
            )
    return refs


def media_kind(filename: str, content_type: str | None = None) -> str:
    ext = Path(filename).suffix.lower()
    content = (content_type or "").split(";", 1)[0].lower()
    if content.startswith("image/") or ext in IMAGE_EXT:
        return "image"
    if content.startswith("video/") or ext in VIDEO_EXT:
        return "video"
    if content.startswith("audio/") or ext in AUDIO_EXT:
        return "audio"
    return "file"


class _GuardRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, external: bool):
        super().__init__()
        self.external = external

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host or not host_allowed(host, external=self.external):
            raise urllib.error.HTTPError(req.full_url, code, f"refusing redirect to {parsed.scheme}://{host}", headers, fp)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        original = urllib.parse.urlparse(req.full_url)
        if redirected is not None and (original.scheme, original.hostname, original.port or 443) != (parsed.scheme, parsed.hostname, parsed.port or 443):
            for name, _value in list(redirected.header_items()):
                if name.lower() in {"authorization", "cookie", "proxy-authorization"}:
                    redirected.remove_header(name)
        return redirected


def _opener(external: bool) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_GuardRedirect(external))


def fetch_dest_for(dest: Path) -> str:
    ext = dest.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return "empty"


def accept_header_for(dest: Path) -> str:
    ext = dest.suffix.lower()
    if ext in IMAGE_EXT:
        return "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    if ext in VIDEO_EXT:
        return "video/webm,video/ogg,video/*;q=0.9,*/*;q=0.5"
    if ext in AUDIO_EXT:
        return "audio/webm,audio/ogg,audio/*;q=0.9,*/*;q=0.5"
    return "*/*"


def _quiet_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _replace_file(partial: Path, dest: Path) -> None:
    last: OSError | None = None
    for _ in range(6):
        try:
            partial.replace(dest)
            return
        except OSError as exc:
            last = exc
            try:
                if dest.exists() and dest.stat().st_size > 0:
                    _quiet_unlink(partial)
                    return
            except OSError:
                pass
            time.sleep(0.25)
    if last is not None:
        raise last


_DEST_LOCKS: dict[str, threading.Lock] = {}
_DEST_GUARD = threading.Lock()


def _dest_lock(dest: Path) -> threading.Lock:
    key = str(dest.resolve()).casefold()
    with _DEST_GUARD:
        lock = _DEST_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _DEST_LOCKS[key] = lock
        return lock


def repair_media_names(archive: Path) -> int:
    """Rename saved files whose extension lies about their content.

    Also rewrites media.jsonl, the readable copies, and the index. Safe to
    run again; use after a download made by an older version, or any time.
    """
    from .render import rebuild_index, write_channel_views
    from .util import read_json

    renamed = 0
    root = archive / "channels"
    if not root.exists():
        return 0
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        media_dir = folder / "media"
        log_path = folder / "media.jsonl"
        rows = list(read_jsonl(log_path))
        mapping: dict[str, str] = {}
        if media_dir.is_dir():
            for path in sorted(media_dir.iterdir()):
                if not path.is_file() or path.name.endswith(".part"):
                    continue
                try:
                    with path.open("rb") as handle:
                        head = handle.read(16)
                except OSError:
                    continue
                actual = sniff_extension(head)
                if actual is None or path.suffix.lower() == actual:
                    continue
                fixed = fix_saved_extension(path)
                if fixed != path:
                    mapping[path.name] = fixed.name
                    renamed += 1
        if not mapping:
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("path") or "").split("/", 1)[-1]
            if name in mapping:
                row["path"] = f"media/{mapping[name]}"
        with log_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        state = read_json(folder / "channel.json", {})
        if isinstance(state, dict):
            write_channel_views(folder, state)
    rebuild_index(archive)
    return renamed


def index_saved_media(path: Path, folder: Path) -> tuple[set[str], dict[str, str]]:
    """Keys and asset paths for files that are actually on disk."""
    keys: set[str] = set()
    assets: dict[str, str] = {}
    if not path.exists():
        return keys, assets
    for row in read_jsonl(path):
        if not isinstance(row, dict) or row.get("status") not in {"saved", "exists"}:
            continue
        rel = str(row.get("path") or "")
        if not rel or not (folder / rel).is_file():
            continue
        if row.get("key"):
            keys.add(str(row["key"]))
        asset = asset_key(
            str(row.get("url") or ""),
            str(row.get("kind") or ""),
            str(row.get("key") or ""),
        )
        if asset and asset not in assets:
            assets[asset] = rel
    return keys, assets


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collapse_byte_copies(folder: Path, rows: list) -> int:
    """Point every record at one copy of a byte-identical file, then delete the rest.

    A file is removed only when its bytes match another file in the same chat.
    """
    media_dir = folder / "media"
    if not media_dir.is_dir():
        return 0
    by_hash: dict[str, list[Path]] = {}
    for path in media_dir.iterdir():
        if not path.is_file() or path.name.endswith(".part") or path.stat().st_size <= 0:
            continue
        by_hash.setdefault(_sha256(path), []).append(path)
    removed = 0
    remap: dict[str, str] = {}
    for paths in by_hash.values():
        unique = {path.resolve(): path for path in paths}
        if len(unique) < 2:
            continue
        keeper = min(unique.values(), key=lambda path: (len(path.name), path.name))
        for path in unique.values():
            if path.resolve() == keeper.resolve():
                continue
            remap[f"media/{path.name}"] = f"media/{keeper.name}"
            try:
                path.unlink()
            except OSError:
                remap.pop(f"media/{path.name}", None)
                continue
            removed += 1
    if not remap:
        return 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        target = remap.get(str(row.get("path") or ""))
        if not target:
            continue
        row["path"] = target
        row["status"] = "exists"
        row["error"] = None
    return removed


def dedupe_media(archive: Path) -> int:
    """Delete extra copies of the same file. Offline. Returns files removed.

    Only byte-identical files are collapsed, regardless of recorded asset IDs.
    Each message still points at the picture; only the spare copies go.
    """
    from .render import rebuild_index, write_channel_views
    from .util import read_json

    removed = 0
    changed_any = False
    root = archive / "channels"
    if not root.exists():
        return 0
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        log_path = folder / "media.jsonl"
        if not log_path.exists():
            continue
        rows = list(read_jsonl(log_path))
        changed = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset = asset_key(
                str(row.get("url") or ""),
                str(row.get("kind") or ""),
                str(row.get("key") or ""),
            )
            if row.get("asset") != asset:
                row["asset"] = asset
                changed = True
        deleted_here = collapse_byte_copies(folder, rows)
        if not changed and not deleted_here:
            continue
        changed_any = True
        removed += deleted_here
        with log_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        state = read_json(folder / "channel.json", {})
        if isinstance(state, dict):
            write_channel_views(folder, state)
    if changed_any:
        rebuild_index(archive)
    return removed


def download_url(
    url: str,
    dest: Path,
    *,
    max_bytes: int | None,
    token: str | None = None,
    external: bool = False,
    timeout: int = 120,
) -> tuple[str, int, str | None, str | None]:
    """Return status, size, error, content_type.

    status is saved, exists, failed, or skipped.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return "skipped", 0, "not an https URL", None
    if not host_allowed(parsed.hostname, external=external):
        return "skipped", 0, "external URL skipped", None
    lock = _dest_lock(dest)
    with lock:
        try:
            if dest.exists() and dest.stat().st_size > 0:
                return "exists", dest.stat().st_size, None, None
        except OSError as exc:
            return "failed", 0, str(exc), None

        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(f"{dest.name}.{threading.get_ident()}.part")
        last_error = "download failed"
        try:
            return _download_attempts(
                url,
                dest,
                partial,
                max_bytes=max_bytes,
                external=external,
                timeout=timeout,
                last_error=last_error,
            )
        except Exception as exc:
            return "failed", 0, str(exc), None
        finally:
            _quiet_unlink(partial)


def _download_attempts(
    url: str,
    dest: Path,
    partial: Path,
    *,
    max_bytes: int | None,
    external: bool,
    timeout: int,
    last_error: str,
) -> tuple[str, int, str | None, str | None]:
    for attempt in range(4):
        headers = {
            "User-Agent": BROWSER_UA,
            "Accept": accept_header_for(dest),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
            "Referer": "https://discord.com/channels/@me",
            "Sec-Ch-Ua": SEC_CH_UA,
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": fetch_dest_for(dest),
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }
        # Signed media URLs must never receive the account's API credential.
        request = urllib.request.Request(url, headers=headers)
        try:
            with _opener(external).open(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type")
                if content_type and content_type.split(";", 1)[0].lower().startswith("text/html"):
                    return "skipped", 0, "URL returned a web page, not a file", content_type
                length = response.headers.get("Content-Length")
                if max_bytes and length and length.isdigit() and int(length) > max_bytes:
                    return "skipped", int(length), f"larger than {human_bytes(max_bytes)}", content_type
                total = 0
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if max_bytes and total > max_bytes:
                            handle.close()
                            _quiet_unlink(partial)
                            return "skipped", total, f"larger than {human_bytes(max_bytes)}", content_type
                        handle.write(chunk)
                if total == 0:
                    _quiet_unlink(partial)
                    return "failed", 0, "empty file", content_type
                _replace_file(partial, dest)
                return "saved", total, None, content_type
        except urllib.error.HTTPError as exc:
            _quiet_unlink(partial)
            if exc.code == 404:
                return "failed", 0, "Discord no longer has this file (deleted or the link expired)", None
            if exc.code == 429 or exc.code >= 500:
                last_error = f"HTTP {exc.code}"
                continue
            return "failed", 0, f"HTTP {exc.code}", None
        except Exception as exc:
            _quiet_unlink(partial)
            last_error = str(exc)
            if attempt == 3:
                break
            time.sleep(0.4 + random.uniform(0, 0.4))
    _quiet_unlink(partial)
    return "failed", 0, last_error, None


def local_name(ref: MediaRef) -> str:
    asset = ref_asset(ref)
    ext = Path(ref.filename).suffix or ".png"
    if asset.startswith("sticker:"):
        return safe_filename(f"sticker_{asset.split(':')[-1]}{ext}")
    if asset.startswith("emoji:"):
        return safe_filename(f"emoji_{asset.split(':')[-1]}{ext}")
    if asset.startswith("attachment:"):
        return safe_filename(f"{asset.split(':')[-1]}_{ref.filename}", max_len=120)
    digest = hashlib.sha256(asset.encode("utf-8")).hexdigest()[:16]
    return safe_filename(f"{digest}_{ref.filename}", max_len=120)


def _media_record(
    ref: MediaRef,
    *,
    asset: str,
    status: str,
    path: str,
    size: int,
    error: str | None,
    content_type: str | None,
) -> dict:
    return {
        "key": ref.key,
        "asset": asset,
        "message_id": ref.message_id,
        "kind": ref.kind,
        "filename": ref.filename,
        "path": path,
        "url": ref.url,
        "bytes": size,
        "status": status,
        "error": error,
        "content_type": content_type,
        "spoiler": ref.spoiler,
        "display": media_kind(ref.filename, content_type),
    }


def download_refs(
    refs: list[MediaRef],
    dest_dir: Path,
    *,
    token: str | None,
    include_external: bool,
    max_bytes: int | None,
    workers: int,
    skip_keys: set[str] | None = None,
    skip_assets: dict[str, str] | None = None,
) -> list[dict]:
    """Download each distinct file once. Extra mentions point at that copy."""
    known = dict(skip_assets or {})
    reused: list[dict] = []
    groups: dict[str, list[MediaRef]] = {}
    order: list[str] = []
    for ref in refs:
        asset = ref_asset(ref)
        # An edited embed can keep its message/slot key but change the file URL.
        if skip_keys is not None and ref.key in skip_keys and asset in known:
            continue
        existing = known.get(asset)
        if existing:
            reused.append(
                _media_record(
                    ref,
                    asset=asset,
                    status="exists",
                    path=existing,
                    size=0,
                    error=None,
                    content_type=None,
                )
            )
            continue
        if asset not in groups:
            groups[asset] = []
            order.append(asset)
        groups[asset].append(ref)
    if not order:
        return reused
    dest_dir.mkdir(parents=True, exist_ok=True)

    def one(asset: str) -> list[dict]:
        group = groups[asset]
        leader = group[0]
        time.sleep(random.uniform(0.0, 0.6))
        dest = dest_dir / local_name(leader)
        try:
            status, size, error, content_type = download_url(
                leader.url,
                dest,
                max_bytes=max_bytes,
                token=token,
                external=include_external,
            )
        except Exception as exc:
            status, size, error, content_type = "failed", 0, str(exc), None
        if status == "saved":
            dest = fix_saved_extension(dest)
        path = f"media/{dest.name}"
        rows = []
        for index, ref in enumerate(group):
            ref_status = status
            if index and status in {"saved", "exists"}:
                ref_status = "exists"
            rows.append(
                _media_record(
                    ref,
                    asset=asset,
                    status=ref_status,
                    path=path if ref_status != "failed" else "",
                    size=size if ref_status != "failed" else 0,
                    error=error if ref_status == "failed" else None,
                    content_type=content_type,
                )
            )
        return rows

    records = list(reused)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(one, asset) for asset in order]
        try:
            for future in as_completed(futures):
                records.extend(future.result())
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    return records
