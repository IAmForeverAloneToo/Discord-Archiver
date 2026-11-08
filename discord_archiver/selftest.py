from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from .export import chat_label, oldest_id, pagination_advanced, pick_channel, sidebar_row
from .gateway import FrameBuffer, encode_frame, OP_TEXT
from .media import asset_key, dedupe_media, extract_media, host_allowed, local_name
from .render import load_deduped, render_preview
from .util import channel_dir, channel_id_from_folder, is_snowflake, program_path, safe_filename, snowflake_datetime, tool_root


def run_selftest() -> int:
    checks = (
        _test_names,
        _test_ids,
        _test_pagination,
        _test_media,
        _test_preview_escapes,
        _test_dedupe,
        _test_hosts,
        _test_pick,
        _test_gateway_frames,
        _test_asset_once,
        _test_chat_label,
        _test_program_path,
        _test_channel_folder_name,
        _test_byte_dedupe,
    )
    failed = 0
    for check in checks:
        try:
            check()
        except Exception as exc:
            failed += 1
            print(f"FAIL {check.__name__}: {exc}")
        else:
            print(f"ok   {check.__name__}")
    if failed:
        print(f"{failed} check(s) failed")
        return 1
    print("all offline checks passed")
    return 0


def _test_names() -> None:
    assert safe_filename('bad<>:"/\\|?*name') == "bad_________name"
    assert safe_filename("CON").startswith("_")
    assert ".." not in safe_filename("..")
    try:
        channel_dir(Path("."), "../token")
    except ValueError:
        return
    raise AssertionError("channel id was not rejected")


def _test_ids() -> None:
    assert is_snowflake("175928847299117063")
    assert not is_snowflake("not-an-id")
    assert not is_snowflake("../../etc/passwd")
    stamp = snowflake_datetime("175928847299117063")
    assert stamp is not None
    assert stamp.year >= 2015


def _test_pagination() -> None:
    page = [{"id": "175928847299117099"}, {"id": "175928847299117063"}]
    assert oldest_id(page) == "175928847299117063"
    assert pagination_advanced(None, "175928847299117063")
    assert pagination_advanced("175928847299117099", "175928847299117063")
    assert not pagination_advanced("175928847299117063", "175928847299117063")
    assert oldest_id([{"id": "nope"}]) is None


def _test_media() -> None:
    message = {
        "id": "175928847299117063",
        "content": "hi <:wave:175928847299117064> https://example.com/skip",
        "attachments": [
            {
                "id": "175928847299117065",
                "filename": "photo.png",
                "url": "https://cdn.discordapp.com/attachments/1/2/photo.png",
                "size": 10,
            }
        ],
        "sticker_items": [{"id": "175928847299117066", "name": "Hello", "format_type": 1}],
        "embeds": [{"image": {"url": "https://cdn.discordapp.com/embed/1.png"}}],
    }
    refs = extract_media(message)
    kinds = {ref.kind for ref in refs}
    assert "attachment" in kinds
    assert "sticker" in kinds
    assert "emoji" in kinds
    assert any(ref.kind == "embed-image" for ref in refs)
    assert all("example.com" not in ref.url for ref in refs)
    external = extract_media(
        {"id": "175928847299117063", "embeds": [{"image": {"url": "https://example.com/a.png"}}]},
        include_external=True,
    )
    assert any("example.com" in ref.url for ref in external)


def _test_asset_once() -> None:
    original = {
        "id": "175928847299117063",
        "attachments": [
            {
                "id": "175928847299117065",
                "filename": "image.png",
                "url": "https://cdn.discordapp.com/attachments/9/175928847299117065/image.png?ex=1",
            }
        ],
    }
    reply = {
        "id": "175928847299117070",
        "referenced_message": original,
    }
    first = extract_media(original)[0]
    quoted = next(ref for ref in extract_media(reply) if ref.kind == "reply:attachment")
    assert first.key != quoted.key
    assert asset_key(first.url, first.kind, first.key) == asset_key(quoted.url, quoted.kind, quoted.key)
    assert local_name(first) == local_name(quoted)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "channels" / "9"
        media = folder / "media"
        media.mkdir(parents=True)
        keep = media / "keep_image.png"
        extra = media / "reply_image.png"
        keep.write_bytes(b"same-bytes")
        extra.write_bytes(b"same-bytes")
        url = "https://cdn.discordapp.com/attachments/9/175928847299117065/image.png"
        rows = [
            {"key": "attachment:1:175928847299117065", "message_id": "1", "kind": "attachment", "status": "saved", "path": "media/keep_image.png", "url": url, "filename": "image.png"},
            {"key": "reply:attachment:2:175928847299117065", "message_id": "2", "kind": "reply:attachment", "status": "saved", "path": "media/reply_image.png", "url": url, "filename": "image.png"},
        ]
        (folder / "media.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        (folder / "channel.json").write_text('{"id": "9", "title": "Test", "kind": "dm"}', encoding="utf-8")
        (folder / "messages.jsonl").write_text("", encoding="utf-8")
        assert dedupe_media(root) == 1
        assert keep.exists()
        assert not extra.exists()
        saved = [json.loads(line) for line in (folder / "media.jsonl").open(encoding="utf-8") if line.strip()]
        assert {row["path"] for row in saved} == {"media/keep_image.png"}


def _test_chat_label() -> None:
    ada = sidebar_row(
        {
            "id": "111111111111111111",
            "type": 1,
            "recipients": [{"id": "222222222222222222", "username": "ada", "global_name": "Ada"}],
        },
        "999999999999999999",
    )
    label = chat_label(ada)
    assert "Ada" in label
    assert "@ada" in label
    assert "222222222222222222" in label
    group = sidebar_row(
        {
            "id": "333333333333333333",
            "type": 3,
            "name": "Friday",
            "recipients": [{"id": "222222222222222222", "username": "ada"}],
        },
        "999999999999999999",
    )
    assert "333333333333333333" in chat_label(group)
    assert "(group)" in chat_label(group)


def _test_program_path() -> None:
    root = tool_root()
    if not getattr(sys, "frozen", False):
        assert (root / "discord_archiver").is_dir()
    assert program_path(None, "archive") == (root / "archive").resolve()
    assert program_path("archive", "archive") == (root / "archive").resolve()
    absolute = (Path.home() / "example-archive").resolve()
    assert program_path(str(absolute), "archive") == absolute


def _test_byte_dedupe() -> None:
    from .media import collapse_byte_copies

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        media = folder / "media"
        media.mkdir()
        (media / "one.jpg").write_bytes(b"same-picture")
        (media / "two.jpg").write_bytes(b"same-picture")
        (media / "other.jpg").write_bytes(b"different")
        rows = [
            {"path": "media/one.jpg", "status": "saved"},
            {"path": "media/two.jpg", "status": "saved"},
            {"path": "media/other.jpg", "status": "saved"},
        ]
        assert collapse_byte_copies(folder, rows) == 1
        assert rows[0]["path"] == rows[1]["path"]
        assert (media / "other.jpg").is_file()
        assert len(list(media.iterdir())) == 2


def _test_channel_folder_name() -> None:
    assert channel_id_from_folder("111111111111111111") == "111111111111111111"
    assert channel_id_from_folder("Example - 111111111111111111") == "111111111111111111"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "channels" / "111111111111111111"
        folder.mkdir(parents=True)
        renamed = channel_dir(root, "111111111111111111", "Example")
        assert renamed.name == "Example - 111111111111111111"
        assert channel_dir(root, "111111111111111111") == renamed


def _test_preview_escapes() -> None:
    html = render_preview(
        "Chat",
        "175928847299117063",
        [
            {
                "id": "175928847299117063",
                "content": "<script>alert(1)</script>",
                "author": {"id": "175928847299117064", "username": "Ada"},
                "timestamp": "2024-01-02T15:04:01+00:00",
                "type": 0,
            }
        ],
        {},
        total=1,
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    formatted = render_preview(
        "Chat",
        "175928847299117063",
        [
            {
                "id": "175928847299117063",
                "content": "here is *some* text",
                "author": {"id": "175928847299117064", "username": "Ada"},
                "timestamp": "2017-07-13T01:30:00+00:00",
                "type": 0,
            },
            {
                "id": "175928847299117070",
                "content": "reply",
                "author": {"id": "175928847299117065", "username": "Bea"},
                "timestamp": "2017-07-13T07:32:00+00:00",
                "type": 19,
                "referenced_message": {
                    "id": "175928847299117063",
                    "content": "here is some text",
                    "author": {"id": "175928847299117064", "username": "Ada"},
                },
            },
        ],
        {
            "175928847299117063": [
                {
                    "kind": "attachment",
                    "status": "saved",
                    "path": "media/photo.png",
                    "filename": "photo.png",
                    "display": "image",
                    "bytes": 120,
                }
            ],
            "175928847299117070": [
                {
                    "kind": "reply:attachment",
                    "status": "exists",
                    "path": "media/photo.png",
                    "filename": "photo.png",
                    "display": "image",
                    "bytes": 120,
                }
            ],
        },
        total=2,
    )
    assert "<em>some</em>" in formatted
    assert formatted.count('class="shot"') == 1
    assert "replythumb" in formatted
    assert "media/photo.png" in formatted


def _test_dedupe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "messages.jsonl"
        rows = [
            {"id": "175928847299117063", "content": "stub", "package_only": True},
            {"id": "175928847299117063", "content": "full", "author": {"username": "Ada"}},
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        loaded = load_deduped(path)
        assert len(loaded) == 1
        assert loaded[0]["content"] == "full"


def _test_pick() -> None:
    channels = [
        {
            "id": "111111111111111111",
            "type": 1,
            "recipients": [{"id": "222222222222222222", "username": "ada", "global_name": "Ada Lovelace"}],
        },
        {
            "id": "333333333333333333",
            "type": 1,
            "recipients": [{"id": "444444444444444444", "username": "al", "global_name": "Alan"}],
        },
    ]
    chosen, error = pick_channel("ada", channels, "999999999999999999")
    assert error is None and chosen is not None and chosen["id"].startswith("1")
    chosen, error = pick_channel("Ada Lovelace", channels, "999999999999999999")
    assert error is None and chosen is not None
    chosen, error = pick_channel("a", channels, "999999999999999999")
    assert chosen is None and error and "more than one" in error


def _test_gateway_frames() -> None:
    payload = json.dumps({"op": 1, "d": None}, separators=(",", ":")).encode("utf-8")
    frame = encode_frame(OP_TEXT, payload)
    assert frame[0] & 0x0F == OP_TEXT
    buf = FrameBuffer()
    buf.feed(frame[:5])
    assert buf.pop() is None
    buf.feed(frame[5:])
    opcode, fin, data = buf.pop()
    assert opcode == OP_TEXT and fin and data == payload
    big = b"x" * 70000
    buf.feed(encode_frame(OP_TEXT, big))
    opcode, _, data = buf.pop()
    assert data == big


def _test_hosts() -> None:
    assert host_allowed("cdn.discordapp.com", external=False)
    assert host_allowed("media.discordapp.net", external=False)
    assert not host_allowed("example.com", external=False)
    assert host_allowed("example.com", external=True)
    assert not host_allowed("evil.discord.com.example", external=False)


if __name__ == "__main__":
    raise SystemExit(run_selftest())
