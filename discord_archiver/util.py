from __future__ import annotations

import json
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SNOWFLAKE_RE = re.compile(r"^\d{15,22}$")
DISCORD_EPOCH_MS = 1_420_070_400_000
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)

# One browser identity per run, shared by the API client, the gateway session,
# and file downloads, so every connection tells the same story.
_BROWSER_POOL = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36", "130"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "131"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36", "129"),
]
_UA, _UA_VERSION = random.choice(_BROWSER_POOL)
BROWSER_UA = _UA
SEC_CH_UA = f'"Chromium";v="{_UA_VERSION}", "Google Chrome";v="{_UA_VERSION}", "Not?A_Brand";v="99"'


def tool_root() -> Path:
    """Folder that contains this program, wherever that folder currently is."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if sys.platform == "darwin" and executable.parent.name == "MacOS" and executable.parent.parent.name == "Contents":
            return executable.parents[3]
        return executable.parent
    return Path(__file__).resolve().parent.parent


def program_path(value: str | None, name: str) -> Path:
    """Path next to this program, unless an absolute path was given.

    A relative name follows the program folder. It does not follow the folder
    the window or the command happened to be started from.
    """
    text = (value or "").strip()
    if text in {"", name, f"./{name}", f".\\{name}"}:
        return (tool_root() / name).resolve()
    path = Path(text)
    if path.is_absolute():
        return path
    return (tool_root() / path).resolve()


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def is_snowflake(value: object) -> bool:
    return isinstance(value, str) and bool(SNOWFLAKE_RE.fullmatch(value))


def normalize_id(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        text = str(value)
    else:
        text = str(value).strip()
    if text.startswith("c") and is_snowflake(text[1:]):
        text = text[1:]
    return text if is_snowflake(text) else None


def snowflake_datetime(value: object) -> datetime | None:
    text = normalize_id(value)
    if text is None:
        return None
    millis = (int(text) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_timestamp(value: object) -> str:
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
        if parsed is None:
            for fmt in (
                "%Y-%m-%d %H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    parsed = datetime.strptime(value.strip(), fmt)
                    break
                except ValueError:
                    parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return value.strip()
    snow = snowflake_datetime(value)
    if snow is not None:
        return snow.strftime("%Y-%m-%d %H:%M:%S UTC")
    return ""


def safe_filename(name: str, max_len: int = 80) -> str:
    cleaned = INVALID_FILENAME.sub("_", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "file"
    stem = cleaned.split(".", 1)[0]
    if RESERVED_WINDOWS.fullmatch(stem):
        cleaned = "_" + cleaned
    if len(cleaned) > max_len:
        suffix = ""
        dot = cleaned.rfind(".")
        if dot > 0 and len(cleaned) - dot <= 10:
            suffix = cleaned[dot:]
        cleaned = cleaned[: max_len - len(suffix)].rstrip(" .") + suffix
    return cleaned or "file"


def display_name(user: dict | None) -> str:
    if not isinstance(user, dict):
        return "Unknown"
    for key in ("global_name", "username", "name"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    uid = user.get("id")
    return str(uid) if uid else "Unknown"


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, default: object = None) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def append_jsonl(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def channel_id_from_folder(name: str) -> str | None:
    if is_snowflake(name):
        return name
    stem, separator, tail = name.rpartition(" - ")
    if separator and stem and is_snowflake(tail):
        return tail
    return None


def channel_folder_name(title: str, channel_id: str) -> str:
    label = safe_filename(title or "Chat", max_len=60)
    return f"{label} - {channel_id}"


def channel_dir(archive: Path, channel_id: str, title: str | None = None) -> Path:
    """Folder for one chat. The name shows who it is, and still ends with the channel ID."""
    if not is_snowflake(channel_id):
        raise ValueError(f"Refusing non-numeric channel id: {channel_id!r}")
    root = archive / "channels"
    found = None
    if root.exists():
        for path in root.iterdir():
            if path.is_dir() and channel_id_from_folder(path.name) == channel_id:
                found = path
                break
    desired = channel_folder_name(title, channel_id) if title else None
    if found is None:
        return root / (desired or channel_id)
    if desired and found.name != desired:
        target = root / desired
        if not target.exists():
            try:
                found.rename(target)
                return target
            except OSError:
                return found
    return found


def human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "[token]")
    return text


def public_user(user: dict | None) -> dict | None:
    if not isinstance(user, dict):
        return None
    kept = {
        key: user.get(key)
        for key in ("id", "username", "global_name", "discriminator", "avatar")
        if user.get(key) is not None
    }
    uid = normalize_id(kept.get("id"))
    if uid is None:
        return None
    kept["id"] = uid
    return kept


class Log:
    def __init__(self, path: Path | None = None, echo=None):
        self.path = path
        self.echo = echo
        self._handle = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("a", encoding="utf-8", newline="\n")

    def __call__(self, message: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')}  {message}"
        print(line, flush=True)
        if self.echo is not None:
            try:
                self.echo(line)
            except Exception:
                pass
        if self._handle is not None:
            self._handle.write(line + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
