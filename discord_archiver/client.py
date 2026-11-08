from __future__ import annotations

import base64
import http.client
import json
import random
import threading
import time
import urllib.parse
from typing import Any

from .util import BROWSER_UA, SEC_CH_UA, redact


class ApiError(Exception):
    def __init__(self, status: int, message: str, *, fatal: bool = False):
        super().__init__(message)
        self.status = status
        self.fatal = fatal


class Headers:
    def __init__(self, pairs: list[tuple[str, str]]):
        self._items = {key.lower(): value for key, value in pairs}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._items.get(key.lower(), default)


def clean_token(token: str) -> str:
    token = token.strip().strip('"').strip("'")
    lowered = token.lower()
    if lowered.startswith("bot "):
        raise SystemExit(
            "That is a bot token. Bots cannot read your personal DMs. "
            "Copy the Authorization value from your own logged-in Discord client."
        )
    if lowered.startswith("bearer "):
        token = token.split(None, 1)[1].strip()
    if token.lower().startswith("http"):
        raise SystemExit("That looks like a URL, not a token. Copy only the Authorization header value.")
    if len(token) < 20:
        raise SystemExit("Token looks too short. Paste the full Authorization value into token.txt.")
    return token


class DiscordApi:
    """Read-only Discord API client for the account that owns the token.

    Pacing follows the rate-limit headers Discord returns, with random jitter
    and occasional longer pauses so the traffic pattern is not metronomic.
    """

    def __init__(self, token: str, *, message_interval: float = 1.15):
        self.token = clean_token(token)
        self.message_interval = max(0.2, message_interval)
        self.min_interval = min(0.25, self.message_interval)
        self.invalid = False
        self._user_agent = BROWSER_UA
        self._super_properties = self._build_super_properties()
        self._lock = threading.Lock()
        self._next_at = 0.0
        self._global_until = 0.0
        self._bucket_until: dict[str, float] = {}
        self._remaining: dict[str, int | None] = {}
        self._conn: http.client.HTTPSConnection | None = None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _build_super_properties(self) -> str:
        """The browser fingerprint header the web client sends with each request."""
        browser_version = self._user_agent.rsplit("Chrome/", 1)[-1].split(" ", 1)[0]
        props = {
            "os": "Windows",
            "browser": "Chrome",
            "device": "",
            "system_locale": "en-US",
            "browser_version": browser_version,
            "os_version": "10",
            "referrer": "",
            "referring_domain": "",
            "referrer_current": "",
            "referring_domain_current": "",
            "release_channel": "stable",
            "client_build_number": 367002,
            "client_event_source": None,
        }
        encoded = json.dumps(props, separators=(",", ":")).encode("utf-8")
        return base64.b64encode(encoded).decode("ascii")

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": self.token,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": self._user_agent,
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
            "Sec-Ch-Ua": SEC_CH_UA,
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Discord-Locale": "en-US",
            "X-Super-Properties": self._super_properties,
            "Connection": "keep-alive",
        }
        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    def _resource(path: str) -> str:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "channels":
            return "channel:" + parts[1]
        return path

    def _human_pace(self, requested: float) -> float:
        """Vary the interval like a person reading, not a fixed timer."""
        pace = requested * random.uniform(0.8, 1.6)
        roll = random.random()
        if roll < 0.02:
            pace += random.uniform(30.0, 180.0)
        elif roll < 0.10:
            pace += random.uniform(2.0, 9.0)
        return pace

    def _pace_for(self, key: str, requested: float) -> float:
        with self._lock:
            if time.monotonic() >= self._bucket_until.get(key, 0.0) and self._remaining.get(key) == 0:
                self._remaining[key] = None
        return requested

    def _wait(self, key: str, pace: float) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                until = max(self._next_at, self._global_until, self._bucket_until.get(key, 0.0))
                if now >= until:
                    self._next_at = now + pace
                    return
                delay = until - now
            time.sleep(min(delay, 1.0))

    def _note(self, key: str, headers: Headers, status: int) -> None:
        remaining = _header_float(headers, "X-RateLimit-Remaining")
        reset_after = _header_float(headers, "X-RateLimit-Reset-After") or 0.0
        with self._lock:
            if remaining is not None:
                self._remaining[key] = int(remaining)
            if remaining is not None and remaining <= 1 and reset_after > 0:
                until = time.monotonic() + reset_after + 0.2
                self._bucket_until[key] = max(self._bucket_until.get(key, 0.0), until)
                self._remaining[key] = 0
            if status == 429 and headers.get("X-RateLimit-Global"):
                self._global_until = max(self._global_until, time.monotonic() + max(reset_after, 1.0))

    def request(
        self,
        method: str,
        path: str,
        query: dict | None = None,
        body: dict | None = None,
        *,
        version: str = "v10",
        pace: float | None = None,
        retries: int = 6,
    ) -> Any:
        if self.invalid:
            raise ApiError(401, "Token was rejected. Stopping.", fatal=True)
        target = f"/api/{version}{path}"
        if query:
            cleaned = {key: value for key, value in query.items() if value is not None}
            if cleaned:
                target += "?" + urllib.parse.urlencode(cleaned)
        payload = None
        headers = self._headers()
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        key = self._resource(path)
        requested = self.min_interval if pace is None else pace
        last_error = "request failed"
        for attempt in range(retries):
            self._wait(key, self._pace_for(key, self._human_pace(requested)))
            try:
                status, response_headers, raw = self._once(method, target, payload, headers)
            except (http.client.HTTPException, OSError, TimeoutError) as exc:
                self.close()
                last_error = redact(str(exc), self.token)
                time.sleep(min(2**attempt, 20) + random.uniform(0, 0.3))
                continue
            self._note(key, response_headers, status)
            if status == 429:
                wait = min(max(_retry_after(response_headers, raw), 0.5), 3600)
                wait += random.uniform(0.05, 0.25)
                print(f"Rate limited on {path}. Waiting {wait:.1f}s.", flush=True)
                with self._lock:
                    self._bucket_until[key] = time.monotonic() + wait
                    if response_headers.get("X-RateLimit-Global"):
                        self._global_until = time.monotonic() + wait
                continue
            if status in (500, 502, 503, 504):
                time.sleep(min(2**attempt, 20) + random.uniform(0, 0.3))
                last_error = f"HTTP {status}"
                continue
            if status in (301, 302, 303, 307, 308):
                raise ApiError(status, f"Unexpected redirect on {method} {path}. Not following it.")
            if status == 401:
                self.invalid = True
                raise ApiError(
                    401,
                    "Discord rejected the token (401). Copy a fresh Authorization value. "
                    "Changing your password revokes the old one.",
                    fatal=True,
                )
            if status == 204 or not raw:
                if status >= 400:
                    raise ApiError(status, f"HTTP {status} on {method} {path}")
                return None
            text = raw.decode("utf-8", "replace")
            if status >= 400:
                message = text[:300]
                try:
                    info = json.loads(text)
                    if isinstance(info, dict) and info.get("message"):
                        message = str(info["message"])
                except json.JSONDecodeError:
                    pass
                raise ApiError(status, f"HTTP {status} on {method} {path}: {redact(message, self.token)}")
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ApiError(status, f"Discord returned non-JSON for {method} {path}") from exc
        raise ApiError(0, f"Gave up on {method} {path}: {last_error}")

    def _once(
        self,
        method: str,
        path: str,
        payload: bytes | None,
        headers: dict[str, str],
    ) -> tuple[int, Headers, bytes]:
        connection = self._connection()
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        if response.will_close:
            self.close()
        return response.status, Headers(response.getheaders()), raw

    def _connection(self) -> http.client.HTTPSConnection:
        if self._conn is None:
            self._conn = http.client.HTTPSConnection("discord.com", timeout=60)
        return self._conn

    def get_me(self) -> dict:
        data = self.request("GET", "/users/@me")
        if not isinstance(data, dict) or not normalize_user_id(data):
            raise ApiError(0, "Discord did not return an account for this token.")
        return data

    def get_private_channels(self) -> list[dict]:
        last: ApiError | None = None
        for version in ("v10", "v9"):
            try:
                data = self.request("GET", "/users/@me/channels", version=version)
            except ApiError as exc:
                last = exc
                if exc.fatal or exc.status not in (403, 404, 405):
                    raise
                continue
            if isinstance(data, dict):
                for key in ("private_channels", "channels"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            raise ApiError(0, "Unexpected DM list response.")
        if last is not None:
            raise last
        return []

    def get_channel(self, channel_id: str) -> dict:
        data = self.request("GET", f"/channels/{channel_id}")
        if not isinstance(data, dict):
            raise ApiError(0, f"Unexpected channel response for {channel_id}")
        return data

    def get_messages(
        self,
        channel_id: str,
        *,
        before: str | None = None,
        around: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        data = self.request(
            "GET",
            f"/channels/{channel_id}/messages",
            {"limit": str(limit), "before": before, "around": around},
            pace=self.message_interval,
        )
        if data is None:
            return []
        if not isinstance(data, list):
            raise ApiError(0, f"Unexpected message list for {channel_id}")
        return [item for item in data if isinstance(item, dict)]

    def get_relationships(self) -> list[dict]:
        data = self.request("GET", "/users/@me/relationships", pace=self.message_interval)
        if isinstance(data, dict):
            for key in ("relationships", "items", "users"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ApiError(0, "Unexpected friend-list response.")
        return [item for item in data if isinstance(item, dict)]

    def create_dm(self, recipient_id: str) -> dict:
        data = self.request(
            "POST",
            "/users/@me/channels",
            body={"recipient_id": recipient_id},
            pace=max(self.message_interval, 1.5),
        )
        if not isinstance(data, dict):
            raise ApiError(0, f"Unexpected DM response for {recipient_id}")
        return data

    def close_dm(self, channel_id: str) -> None:
        """Hide a DM from the sidebar. Discord keeps the history; this does not delete messages."""
        self.request("DELETE", f"/channels/{channel_id}", pace=self.message_interval)


def normalize_user_id(user: dict) -> str | None:
    from .util import normalize_id

    return normalize_id(user.get("id"))


def _header_float(headers: Headers, name: str) -> float | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _retry_after(headers: Headers, raw: bytes) -> float:
    parsed = _header_float(headers, "Retry-After")
    if parsed is not None:
        return parsed
    try:
        info = json.loads(raw.decode("utf-8", "replace"))
        if isinstance(info, dict) and info.get("retry_after") is not None:
            return float(info["retry_after"])
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    reset = _header_float(headers, "X-RateLimit-Reset-After")
    if reset is not None:
        return reset
    return 1.0
