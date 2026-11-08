"""Offline regression checks for the bug and security review fixes.

Run: python audit/reproduce_findings.py
Uses dummy credentials, mocked downloads, temporary archives and loopback HTTP.
Never reads the real archive or token.txt and never contacts Discord.
"""
from __future__ import annotations

import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from discord_archiver.export import _archive_channel, export_archive
from discord_archiver.media import (
    _GuardRedirect, MediaRef, asset_key, dedupe_media, download_refs, download_url,
    fix_saved_extension, host_allowed, index_saved_media, repair_media_names,
)
from discord_archiver.render import load_deduped, search_archive
from discord_archiver.util import append_jsonl, channel_dir, program_path, read_json, read_jsonl, tool_root, write_json
from discord_archiver.viewer import ArchiveIndex, _safe_file, make_handler

CID = "175928847299117063"
MID = "175928847299117064"
DUMMY_TOKEN = "audit-dummy-credential-not-a-real-token"


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type: str):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}


@contextmanager
def local_server(root: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, ArchiveIndex(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def get(port: int, path: str, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def seed(root: Path):
    folder = channel_dir(root, CID, "Audit chat")
    (folder / "media").mkdir(parents=True)
    write_json(folder / "channel.json", {"id": CID, "title": "Audit chat", "type": 1})
    message = {"id": MID, "content": "original", "author": {"username": "Audit"}}
    (folder / "messages.jsonl").write_text(json.dumps(message) + "\n", encoding="utf-8")
    return folder, message


class ReviewRegressions(unittest.TestCase):
    def test_01_spoofed_discord_hostname_is_blocked(self):
        seen = []

        class FakeOpener:
            def open(self, request, **kwargs):
                seen.append(dict(request.header_items()))
                if len(seen) == 1:
                    raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
                return FakeResponse(b"audit-image", "image/png")

        self.assertFalse(host_allowed("audit-discordapp.com", external=False))
        with tempfile.TemporaryDirectory() as tmp, patch(
            "discord_archiver.media._opener", return_value=FakeOpener()
        ):
            result = download_url(
                "https://audit-discordapp.com/image.png", Path(tmp) / "image.png",
                max_bytes=1024, token=DUMMY_TOKEN,
            )
        self.assertEqual(result[0], "skipped")
        self.assertEqual(seen, [])

    def test_01b_redirect_rejects_http(self):
        request = urllib.request.Request(
            "https://cdn.discordapp.com/a.png", headers={"Authorization": DUMMY_TOKEN}
        )
        with self.assertRaises(urllib.error.HTTPError):
            _GuardRedirect(True).redirect_request(
                request, None, 302, "Found", {}, "http://audit.example/image.png"
            )

    def test_02_active_svg_is_forced_to_download_with_sandbox(self):
        body = b'<svg xmlns="http://www.w3.org/2000/svg"><script>/* audit marker */</script></svg>'

        class FakeOpener:
            def open(self, request, **kwargs):
                return FakeResponse(body, "image/svg+xml")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, _ = seed(root)
            # Legacy numeric folders are supported and have working viewer links.
            numeric_folder = folder.with_name(CID)
            folder.rename(numeric_folder)
            folder = numeric_folder
            dest = folder / "media" / "audit.svg"
            with patch("discord_archiver.media._opener", return_value=FakeOpener()):
                result = download_url("https://cdn.discordapp.com/a.svg", dest, max_bytes=1024)
            self.assertEqual(result[0], "saved")
            row = {"key": "attachment:svg", "message_id": MID, "kind": "attachment",
                   "status": "saved", "path": "media/audit.svg", "display": "image"}
            (folder / "media.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            with local_server(root) as port:
                _, _, messages = get(port, f"/api/channels/{CID}/messages")
                self.assertIn(f'href="/channels/{CID}/media/audit.svg"', json.loads(messages)["messages"][0]["html"])
                path = "/channels/" + urllib.parse.quote(folder.name) + "/media/audit.svg"
                status, headers, served = get(port, path)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "application/octet-stream")
            self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
            self.assertIn("sandbox", headers["Content-Security-Policy"])
            self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(served, body)

    def test_03_named_folder_media_links_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, _ = seed(root)
            (folder / "media" / "image.png").write_bytes(b"audit-image")
            row = {"key": "attachment:audit", "message_id": MID, "kind": "attachment",
                   "status": "saved", "path": "media/image.png", "display": "image"}
            (folder / "media.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            with local_server(root) as port:
                status, _, body = get(port, f"/api/channels/{CID}/messages")
                self.assertEqual(status, 200)
                article = json.loads(body)["messages"][0]["html"]
                self.assertIn(f'/channels/{CID}/media/image.png', article)
                status, headers, body = get(port, f"/channels/{CID}/media/image.png")
                self.assertEqual(status, 200)
                self.assertEqual(body, b"audit-image")
                self.assertEqual(headers["Content-Type"], "image/png")
                self.assertNotIn("Content-Disposition", headers)

    def test_04_query_distinct_assets_preserve_different_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, _ = seed(root)
            rows = []
            for name, query, body in [("one.png", "1", b"first"), ("two.png", "2", b"second-longer")]:
                (folder / "media" / name).write_bytes(body)
                rows.append({"key": name, "message_id": MID, "kind": "embed-image",
                             "status": "saved", "path": "media/" + name,
                             "asset": "url:audit.example/image",
                             "url": "https://audit.example/image?id=" + query})
            (folder / "media.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            self.assertEqual(dedupe_media(root), 0)
            self.assertEqual((folder / "media" / "one.png").read_bytes(), b"first")
            self.assertEqual((folder / "media" / "two.png").read_bytes(), b"second-longer")
            _, assets = index_saved_media(folder / "media.jsonl", folder)
            self.assertEqual(len(assets), 2)

    def test_05_extension_collision_preserves_both_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "photo.jpg"
            existing = Path(tmp) / "photo.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\nFIRST")
            existing.write_bytes(b"\x89PNG\r\n\x1a\nSECOND")
            corrected = fix_saved_extension(source)
            self.assertNotEqual(corrected, existing)
            self.assertEqual(corrected.suffix, ".png")
            self.assertTrue(corrected.read_bytes().endswith(b"FIRST"))
            self.assertFalse(source.exists())
            self.assertTrue(existing.read_bytes().endswith(b"SECOND"))

    def test_06_force_export_saves_edits_without_duplicate_message_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, original = seed(root)

            class FakeApi:
                token = DUMMY_TOKEN
                calls = 0

                def get_messages(self, *args, **kwargs):
                    self.calls += 1
                    return [dict(original, content="edited", edited_timestamp="2026-11-08T00:00:00Z")]

            result = _archive_channel(
                FakeApi(), root, {"id": CID, "type": 1, "recipients": [], "name": "Audit chat"},
                "999999999999999999", {}, download_media=False, include_external=False,
                max_bytes=None, workers=1, force=True, log=lambda _: None, stop=None,
            )
            # channel_title names a recipient-free DM "Direct Message" and renames its folder.
            folder = channel_dir(root, CID)
            self.assertEqual(load_deduped(folder / "messages.jsonl")[0]["content"], "edited")
            self.assertEqual(result["new"], 0)
            self.assertEqual(result["updated"], 1)
            self.assertEqual(len(list(read_jsonl(folder / "messages.jsonl"))), 2)
            self.assertEqual(read_json(folder / "channel.json")["message_count"], 1)
            self.assertIn("edited", (folder / "preview.html").read_text(encoding="utf-8"))
            self.assertEqual(len(search_archive(root, "edited")), 1)
            self.assertEqual(search_archive(root, "original"), [])
            with local_server(root) as port:
                _, _, body = get(port, f"/api/channels/{CID}/messages")
            self.assertIn("edited", json.loads(body)["messages"][0]["html"])

    def test_07_nonadvancing_pagination_stays_incomplete_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = [{"id": str(int(MID) + n), "content": "audit"} for n in range(50)]

            class FakeApi:
                token = DUMMY_TOKEN

                def get_messages(self, *args, **kwargs):
                    return page

            result = _archive_channel(
                FakeApi(), root, {"id": CID, "type": 1, "recipients": []},
                "999999999999999999", {}, download_media=False, include_external=False,
                max_bytes=None, workers=1, force=False, log=lambda _: None, stop=None,
            )
            state = read_json(channel_dir(root, CID) / "channel.json")
            self.assertEqual(state["last_error"], "pagination stopped early")
            self.assertFalse(state["backfill_complete"])
            self.assertFalse(result["complete"])
            self.assertEqual(state["api_before"], MID)

            # Also repair completion flags written incorrectly by older versions.
            state["backfill_complete"] = True
            write_json(channel_dir(root, CID) / "channel.json", state)
            calls = []

            class ResumingApi:
                token = DUMMY_TOKEN

                def get_messages(self, *args, **kwargs):
                    calls.append(kwargs.get("before"))
                    if kwargs.get("before"):
                        return [{"id": str(int(MID) - 1), "content": "older"}]
                    return page

            result = _archive_channel(
                ResumingApi(), root, {"id": CID, "type": 1, "recipients": []},
                "999999999999999999", {}, download_media=False, include_external=False,
                max_bytes=None, workers=1, force=False, log=lambda _: None, stop=None,
            )
            self.assertEqual(calls[0], MID)
            self.assertTrue(result["complete"])
            self.assertEqual(len(load_deduped(channel_dir(root, CID) / "messages.jsonl")), 51)

    def test_08_sniffing_uses_bounded_reads_in_download_and_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, _ = seed(root)
            path = folder / "media" / "image.png"
            path.write_bytes(b"\x89PNG" + b"x" * 1024)
            original_open = Path.open
            reads = []

            class BoundedReader:
                def __enter__(self):
                    self.handle = original_open(path, "rb")
                    return self

                def __exit__(self, *args):
                    self.handle.close()

                def read(self, size=-1):
                    if not 0 < size <= 16:
                        raise AssertionError(f"unbounded format read: {size}")
                    reads.append(size)
                    return self.handle.read(size)

            def guarded_open(file, mode="r", *args, **kwargs):
                if file == path and mode == "rb":
                    return BoundedReader()
                return original_open(file, mode, *args, **kwargs)

            with patch.object(Path, "open", guarded_open), patch.object(
                Path, "read_bytes", side_effect=AssertionError("whole-file read")
            ):
                self.assertEqual(fix_saved_extension(path), path)
                self.assertEqual(repair_media_names(root), 0)
            self.assertEqual(reads, [16, 16])

    def test_media_never_send_credentials_even_when_external_is_enabled(self):
        for host in ("cdn.discordapp.com", "audit-discordapp.com", "audit.example"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                seen = []

                class RejectingOpener:
                    def open(self, request, **kwargs):
                        seen.append(dict(request.header_items()))
                        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

                with patch("discord_archiver.media._opener", return_value=RejectingOpener()):
                    result = download_url(
                        f"https://{host}/image.png", Path(tmp) / "image.png",
                        max_bytes=1024, token=DUMMY_TOKEN, external=True,
                    )
                self.assertEqual(result[0], "failed")
                self.assertEqual(len(seen), 1)
                self.assertNotIn("Authorization", seen[0])

    def test_domain_boundaries_and_redirect_credentials(self):
        for host in ("discordapp.com", "cdn.discordapp.com", "media.discordapp.net", "discord.com"):
            self.assertTrue(host_allowed(host, external=False))
        for host in ("evil-discordapp.com", "notdiscordapp.net", "discordapp.com.evil.example"):
            self.assertFalse(host_allowed(host, external=False))
        original = "https://discord.com/api/v10/gateway"
        request = urllib.request.Request(original, headers={
            "Authorization": DUMMY_TOKEN, "Cookie": "audit=cookie", "Proxy-Authorization": "audit"
        })
        for url in ("https://audit.example/file", "https://discord.com:444/file", "https://cdn.discordapp.com/file"):
            with self.subTest(url=url):
                redirected = _GuardRedirect(True).redirect_request(request, None, 302, "Found", {}, url)
                for header in ("Authorization", "Cookie", "Proxy-authorization"):
                    self.assertIsNone(redirected.get_header(header))
        redirected = _GuardRedirect(False).redirect_request(
            request, None, 302, "Found", {}, "https://discord.com/api/v10/gateway/"
        )
        self.assertEqual(redirected.get_header("Authorization"), DUMMY_TOKEN)
        with self.assertRaises(urllib.error.HTTPError):
            _GuardRedirect(False).redirect_request(request, None, 302, "Found", {}, "https://evil-discordapp.com/file")

    def test_active_file_policy_covers_empty_files_and_partial_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, _ = seed(root)
            for name, body in (("page.html", b"<script>/* audit */</script>"), ("image.svg", b"audit-svg"), ("empty.svg", b"")):
                (folder / "media" / name).write_bytes(body)
            (folder / "preview.html").write_text("<!doctype html><p>Generated preview</p>", encoding="utf-8")
            with local_server(root) as port:
                for name in ("page.html", "image.svg", "empty.svg"):
                    with self.subTest(name=name):
                        status, headers, _ = get(port, f"/channels/{CID}/media/{name}", {"Range": "bytes=0-3"})
                        self.assertIn(status, (200, 206))
                        self.assertEqual(headers["Content-Type"], "application/octet-stream")
                        self.assertIn("sandbox", headers["Content-Security-Policy"])
                        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
                status, headers, _ = get(port, f"/channels/{CID}/preview.html")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "text/html")
                self.assertNotIn("Content-Disposition", headers)

    def test_media_route_decodes_once_and_retains_containment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, _ = seed(root)
            name = "percent%20 and space.png"
            saved = folder / "media" / name
            saved.write_bytes(b"audit")
            encoded = urllib.parse.quote(name)
            self.assertEqual(_safe_file(root, f"/channels/{CID}/media/{encoded}"), saved.resolve())
            for path in (f"/channels/{CID}/../channel.json", "/channels/%2e%2e/account.json", f"/channels/{CID}/media/%2e%2e%5c%2e%2e%5caccount.json", "/token.txt"):
                self.assertIsNone(_safe_file(root, path))
            with local_server(root) as port:
                self.assertEqual(get(port, f"/channels/{CID}/media/{encoded}")[0], 200)

    def test_distinct_queries_ports_and_hosts_do_not_share_assets(self):
        urls = (
            "https://audit.example/image?id=1", "https://audit.example/image?id=2",
            "https://audit.example:444/image?id=1", "https://audit.example/a%2Fb", "https://audit.example/a/b",
            "https://audit.example/attachments/9/123/image.png",
            "https://cdn.discordapp.com/attachments/9/123/image.png?ex=1",
        )
        self.assertEqual(len({asset_key(url) for url in urls}), len(urls))
        self.assertEqual(asset_key(urls[-1]), asset_key(urls[-1].replace("ex=1", "ex=2")))
        self.assertEqual(asset_key(urls[0]), asset_key(urls[0] + "#fragment"))

    def test_query_selected_downloads_save_separate_contents(self):
        refs = [MediaRef(MID, "embed-image", f"https://audit.example/image?id={n}", "image.png", f"embed:{n}") for n in (1, 2)]

        def fake_download(url, dest, **kwargs):
            body = urllib.parse.urlparse(url).query.encode("ascii")
            dest.write_bytes(body)
            return "saved", len(body), None, "image/png"

        with tempfile.TemporaryDirectory() as tmp, patch(
            "discord_archiver.media.download_url", side_effect=fake_download
        ), patch("discord_archiver.media.time.sleep"):
            directory = Path(tmp) / "media"
            records = download_refs(refs, directory, token=DUMMY_TOKEN, include_external=True, max_bytes=None, workers=2)
            self.assertEqual(len({row["path"] for row in records}), 2)
            self.assertEqual({path.read_bytes() for path in directory.iterdir()}, {b"id=1", b"id=2"})

    def test_edited_embed_with_existing_slot_key_downloads_its_new_asset(self):
        old_url = "https://audit.example/image?id=1"
        new_url = "https://audit.example/image?id=2"
        ref = MediaRef(MID, "embed-image", new_url, "image.png", "embed:unchanged-slot")

        def fake_download(url, dest, **kwargs):
            dest.write_bytes(b"new-image")
            return "saved", 9, None, "image/png"

        with tempfile.TemporaryDirectory() as tmp, patch(
            "discord_archiver.media.download_url", side_effect=fake_download
        ) as download, patch("discord_archiver.media.time.sleep"):
            records = download_refs(
                [ref], Path(tmp) / "media", token=DUMMY_TOKEN, include_external=True,
                max_bytes=None, workers=1, skip_keys={ref.key},
                skip_assets={asset_key(old_url): "media/old.png"},
            )
            download.assert_called_once()
            self.assertEqual(records[0]["url"], new_url)
            self.assertEqual(records[0]["status"], "saved")

    def test_concurrent_extension_collisions_preserve_distinct_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / "photo.jpg", root / "photo.bmp"]
            contents = [b"\x89PNG-first", b"\x89PNG-second"]
            for path, body in zip(paths, contents):
                path.write_bytes(body)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(fix_saved_extension, paths))
            self.assertEqual(len(set(results)), 2)
            self.assertEqual({path.read_bytes() for path in results}, set(contents))

    def test_extension_repair_can_reuse_only_identical_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, existing = Path(tmp) / "photo.jpg", Path(tmp) / "photo.png"
            source.write_bytes(b"\x89PNG-same")
            existing.write_bytes(b"\x89PNG-same")
            self.assertEqual(fix_saved_extension(source), existing)
            self.assertFalse(source.exists())
            self.assertEqual(existing.read_bytes(), b"\x89PNG-same")

    def test_open_viewer_refreshes_latest_message_and_media_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder, message = seed(root)
            with local_server(root) as port:
                route = f"/api/channels/{CID}/messages"
                self.assertIn("original", json.loads(get(port, route)[2])["messages"][0]["html"])
                append_jsonl(folder / "messages.jsonl", dict(message, content="fresh edit"))
                append_jsonl(folder / "messages.jsonl", dict(message, content="package stub", package_only=True))
                (folder / "media" / "photo.png").write_bytes(b"audit")
                append_jsonl(folder / "media.jsonl", {
                    "key": "attachment:photo", "message_id": MID, "kind": "attachment",
                    "status": "saved", "path": "media/photo.png", "display": "image",
                })
                messages = json.loads(get(port, route)[2])["messages"]
                self.assertEqual(len(messages), 1)
                self.assertIn("fresh edit", messages[0]["html"])
                self.assertNotIn("package stub", messages[0]["html"])
                self.assertIn("/media/photo.png", messages[0]["html"])

    def test_incomplete_export_returns_failure_and_keeps_reopened_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Mock()
            api.get_me.return_value = {"id": "999999999999999999", "username": "Audit"}
            channel = {"id": CID, "type": 1, "recipients": []}
            counts = {"new": 0, "updated": 0, "saved": 0, "failed": 0, "complete": False}
            with patch("discord_archiver.export.DiscordApi", return_value=api), patch(
                "discord_archiver.export.GatewayClient"
            ), patch("discord_archiver.export._discover", return_value=([{"channel": channel, "reopened": True}], {CID})), patch(
                "discord_archiver.export._archive_channel", return_value=counts
            ), patch("discord_archiver.export._hide_again") as hide:
                code = export_archive(Path(tmp), DUMMY_TOKEN, log=lambda _: None)
            self.assertEqual(code, 1)
            hide.assert_not_called()

    def test_packaged_defaults_stay_beside_the_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch("sys.frozen", True, create=True), patch("sys.executable", str(root / "Discord-Archiver")):
                self.assertEqual(tool_root(), root)
                self.assertEqual(program_path(None, "archive"), root / "archive")
                self.assertEqual(program_path(None, "token.txt"), root / "token.txt")

    def test_mac_application_defaults_stay_outside_the_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            executable = root / "Discord-Archiver.app" / "Contents" / "MacOS" / "Discord-Archiver"
            with patch("sys.frozen", True, create=True), patch("sys.platform", "darwin"), patch("sys.executable", str(executable)):
                self.assertEqual(tool_root(), root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
