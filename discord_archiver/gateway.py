"""A live Discord gateway session, standard library only.

Every real Discord client - desktop, phone, browser tab - keeps one of
these websocket sessions open for as long as it runs. A token that only
makes REST calls, with no gateway session behind it, does not look like
any client Discord ships. This module opens that session, identifies as
a Chrome tab, and answers heartbeats while the archive runs. It sends
nothing beyond the handshake and heartbeats; everything else flows in.
"""

from __future__ import annotations

import base64
import json
import os
import random
import socket
import ssl
import struct
import threading
import time
import urllib.parse
import urllib.request

from .client import clean_token
from .media import _opener
from .util import BROWSER_UA

OP_CONTINUE = 0x0
OP_TEXT = 0x1
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class FrameBuffer:
    """Reassembles websocket frames out of streamed bytes."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> None:
        self._buf.extend(chunk)

    def pop(self) -> tuple[int, bool, bytes] | None:
        """Return (opcode, fin, payload), or None until a full frame is buffered."""
        buf = self._buf
        if len(buf) < 2:
            return None
        first, second = buf[0], buf[1]
        opcode = first & 0x0F
        fin = bool(first & 0x80)
        masked = bool(second & 0x80)
        length = second & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < offset + 2:
                return None
            length = struct.unpack("!H", bytes(buf[offset : offset + 2]))[0]
            offset += 2
        elif length == 127:
            if len(buf) < offset + 8:
                return None
            length = struct.unpack("!Q", bytes(buf[offset : offset + 8]))[0]
            offset += 8
        mask = None
        if masked:
            if len(buf) < offset + 4:
                return None
            mask = bytes(buf[offset : offset + 4])
            offset += 4
        if len(buf) < offset + length:
            return None
        payload = bytes(buf[offset : offset + length])
        del buf[: offset + length]
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, fin, payload


def encode_frame(opcode: int, payload: bytes = b"") -> bytes:
    """A client-to-server frame: always masked, never fragmented here."""
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", length)
    header += mask
    return bytes(header) + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


class GatewayClient:
    """Runs one gateway session in the background while the archive works."""

    def __init__(self, token: str, *, log=None):
        self.token = clean_token(token)
        self._log = log
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | ssl.SSLSocket | None = None
        self._url: str | None = None
        self._failures = 0
        self.sessions = 0
        self._session_id: str | None = None
        self._last_seq: int | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="discord-gateway", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _say(self, text: str) -> None:
        if self._log is not None:
            self._log(text)

    def _run(self) -> None:
        while not self._stop.is_set() and self._failures < 6:
            try:
                held = self._session()
            except Exception as exc:
                self._failures += 1
                if not self._stop.is_set():
                    self._say(f"Live session dropped ({exc}). Reconnecting, like a browser tab would.")
                self._stop.wait(random.uniform(2.0, 8.0))
            else:
                if held >= 300:
                    self._failures = 0
        if self._failures >= 6 and not self._stop.is_set():
            self._say("Continuing without the live session; the download itself is unaffected.")

    # -- session ---------------------------------------------------------

    def _session(self) -> float:
        began = time.monotonic()
        url = self._gateway_url()
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "gateway.discord.gg"
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        raw = socket.create_connection((host, 443), timeout=20)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        self._sock = sock
        try:
            sock.settimeout(20)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                f"User-Agent: {BROWSER_UA}\r\n"
                "Accept-Language: en-US,en;q=0.9\r\n"
                "\r\n"
            )
            sock.sendall(handshake.encode("ascii"))
            buf = FrameBuffer()
            header = bytearray()
            deadline = time.monotonic() + 20
            while b"\r\n\r\n" not in header:
                if time.monotonic() > deadline:
                    raise ConnectionError("handshake timed out")
                chunk = self._recv(1.0)
                if chunk:
                    header += chunk
            status_line = bytes(header).split(b"\r\n", 1)[0]
            if b" 101 " not in status_line:
                raise ConnectionError(f"handshake refused: {status_line.decode('utf-8', 'replace')}")
            leftover = bytes(header)[header.index(b"\r\n\r\n") + 4 :]
            buf.feed(leftover)

            hello = self._read_message(buf, timeout=20)
            if hello is None or hello.get("op") != 10:
                raise ConnectionError("gateway sent no hello")
            interval = float((hello.get("d") or {}).get("heartbeat_interval") or 41250) / 1000.0
            if self._session_id is not None and self._last_seq is not None:
                # Real clients try to RESUME the previous session before
                # identifying a new one. Discord expects exactly this.
                self._send_json(
                    {
                        "op": 6,
                        "d": {"token": self.token, "session_id": self._session_id, "seq": self._last_seq},
                    }
                )
            else:
                self._send_json({"op": 2, "d": self._identify()})
            self.sessions += 1
            self._failures = 0
            self._say("Live Discord session open. The download now looks like an open browser tab.")

            seq = hello.get("s")
            next_hb = time.monotonic() + interval * random.uniform(0.6, 0.9)
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= next_hb:
                    self._send_json({"op": 1, "d": seq})
                    next_hb = now + interval * random.uniform(0.95, 1.05)
                message = self._read_message(buf, timeout=min(2.0, max(0.2, next_hb - now)))
                if message is None:
                    continue
                if message.get("s") is not None:
                    seq = message["s"]
                    self._last_seq = seq
                op = message.get("op")
                if op == 9:
                    # Invalid session: Discord wants a fresh identify after a pause.
                    self._session_id = None
                    self._last_seq = None
                    self._stop.wait(random.uniform(1.0, 5.0))
                    raise ConnectionError("session was invalid; identifying fresh")
                if op == 1:
                    self._send_json({"op": 1, "d": seq})
                    next_hb = time.monotonic() + interval * random.uniform(0.95, 1.05)
                if op == 0:
                    event = message.get("t")
                    if event == "READY":
                        self._session_id = (message.get("d") or {}).get("session_id")
                        self._last_seq = seq
            return time.monotonic() - began
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None

    # -- socket helpers ---------------------------------------------------

    def _recv(self, timeout: float) -> bytes:
        sock = self._sock
        if sock is None:
            raise ConnectionError("socket closed")
        try:
            sock.settimeout(max(0.05, timeout))
            return sock.recv(65536)
        except TimeoutError:
            return b""

    def _send_frame(self, opcode: int, payload: bytes = b"") -> None:
        sock = self._sock
        if sock is None:
            return
        sock.sendall(encode_frame(opcode, payload))

    def _send_json(self, payload: dict) -> None:
        self._send_frame(OP_TEXT, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def _read_message(self, buf: FrameBuffer, *, timeout: float) -> dict | None:
        """Read one JSON message, reassembling fragments. None on timeout."""
        deadline = time.monotonic() + timeout
        payload = bytearray()
        while time.monotonic() < deadline:
            if self._stop.is_set():
                return None
            frame = buf.pop()
            if frame is None:
                chunk = self._recv(1.0)
                if chunk:
                    buf.feed(chunk)
                continue
            opcode, fin, data = frame
            if opcode == OP_CLOSE:
                raise ConnectionError("server closed the session")
            if opcode == OP_PING:
                self._send_frame(OP_PONG, data)
                continue
            if opcode == OP_PONG:
                continue
            if opcode in (OP_CONTINUE, OP_TEXT, 0x2):
                payload += data
                if fin:
                    try:
                        return json.loads(payload.decode("utf-8", "replace"))
                    except json.JSONDecodeError:
                        return None
        return None

    # -- rest helpers ------------------------------------------------------

    def _rest(self, path: str) -> dict | None:
        request = urllib.request.Request(
            f"https://discord.com/api/v10{path}",
            headers={
                "Authorization": self.token,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": BROWSER_UA,
            },
        )
        try:
            with _opener(external=False).open(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _gateway_url(self) -> str:
        if self._url is None:
            self._url = (self._rest("/gateway") or {}).get("url") or "wss://gateway.discord.gg"
        return self._url

    def _identify(self) -> dict:
        version = BROWSER_UA.rsplit("Chrome/", 1)[-1].split(" ", 1)[0]
        status = (self._rest("/users/@me/settings") or {}).get("status")
        if status not in {"online", "idle", "dnd", "invisible", "offline"}:
            status = "online"
        return {
            "token": self.token,
            "properties": {
                "os": "Windows",
                "browser": "Chrome",
                "device": "",
                "system_locale": "en-US",
                "browser_user_agent": BROWSER_UA,
                "browser_version": version,
                "os_version": "10",
                "referrer": "",
                "referring_domain": "",
                "referrer_current": "",
                "referring_domain_current": "",
                "release_channel": "stable",
                "client_build_number": 367002,
                "client_event_source": None,
            },
            "presence": {"status": status, "since": 0, "activities": [], "afk": False},
            "compress": False,
        }
