from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from .client import ApiError, DiscordApi
from .gateway import GatewayClient
from .media import avatar_url, download_refs, download_url, extract_media, index_saved_media
from .render import (
    archive_channel_ids,
    rebuild_index,
    write_channel_views,
)
from .util import (
    Log,
    append_jsonl,
    channel_dir,
    channel_id_from_folder,
    display_name,
    format_timestamp,
    is_snowflake,
    normalize_id,
    public_user,
    read_json,
    read_jsonl,
    utc_now,
    write_json,
)

DM_TYPES = {1, 3}


def oldest_id(page: list[dict]) -> str | None:
    ids = [int(str(message["id"])) for message in page if is_snowflake(str(message.get("id") or ""))]
    if not ids:
        return None
    return str(min(ids))


def newest_id(page: list[dict]) -> str | None:
    ids = [int(str(message["id"])) for message in page if is_snowflake(str(message.get("id") or ""))]
    if not ids:
        return None
    return str(max(ids))


def _message_digest(message: dict) -> bytes:
    content = {key: value for key, value in message.items() if key != "package_only"}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")).digest()


def pagination_advanced(previous: str | None, oldest: str | None) -> bool:
    if oldest is None:
        return False
    if previous is None:
        return True
    return int(oldest) < int(previous)


def channel_labels(channel: dict, self_id: str) -> list[str]:
    labels: list[str] = []
    title = channel_title(channel, self_id)
    if title and title not in {"Direct Message", "Group DM"}:
        labels.append(title)
    name = channel.get("name")
    if isinstance(name, str) and name.strip() and name.strip() not in labels:
        labels.append(name.strip())
    for user in channel.get("recipients") or []:
        if str(user.get("id") or "") == self_id:
            continue
        for key in ("username", "global_name"):
            value = user.get(key)
            if isinstance(value, str) and value.strip() and value.strip() not in labels:
                labels.append(value.strip())
    return labels


def pick_channel(query: str, channels: list[dict], self_id: str) -> tuple[dict | None, str | None]:
    needle = query.casefold().strip()
    if not needle:
        return None, "empty name"
    exact: list[dict] = []
    partial: list[dict] = []
    for channel in channels:
        labels = [label.casefold() for label in channel_labels(channel, self_id)]
        if needle in labels:
            exact.append(channel)
        elif any(needle in label for label in labels):
            partial.append(channel)
    pool = exact or partial
    if len(pool) == 1:
        return pool[0], None
    if not pool:
        return None, f"no open chat matches {query!r}"
    shown = ", ".join(channel_title(channel, self_id) for channel in pool[:8])
    return None, f"{query!r} matches more than one chat: {shown}"


def pick_friend(
    query: str, friends: list[tuple[str, dict, list[str]]]
) -> tuple[tuple[str, dict] | None, str | None]:
    needle = query.casefold().strip()
    exact: list[tuple[str, dict, list[str]]] = []
    partial: list[tuple[str, dict, list[str]]] = []
    for row in friends:
        labels = [label.casefold() for label in row[2]]
        if needle in labels:
            exact.append(row)
        elif any(needle in label for label in labels):
            partial.append(row)
    pool = exact or partial
    if len(pool) == 1:
        return (pool[0][0], pool[0][1]), None
    if not pool:
        return None, f"no friend or open chat matches {query!r}"
    shown = ", ".join(row[2][0] for row in pool[:8] if row[2])
    return None, f"{query!r} matches more than one person: {shown}"


def channel_title(channel: dict, self_id: str) -> str:
    if channel.get("type") == 3:
        name = channel.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        names = [
            display_name(user)
            for user in channel.get("recipients") or []
            if str(user.get("id") or "") != self_id
        ]
        return ", ".join(names) or "Group DM"
    for user in channel.get("recipients") or []:
        if str(user.get("id") or "") != self_id:
            return display_name(user)
    return "Direct Message"


def sidebar_row(channel: dict, self_id: str) -> dict:
    cid = normalize_id(channel.get("id")) or ""
    kind = "group" if channel.get("type") == 3 else "dm"
    username = ""
    user_id = ""
    members: list[str] = []
    for user in channel.get("recipients") or []:
        uid = normalize_id(user.get("id"))
        if not uid or uid == self_id:
            continue
        handle = str(user.get("username") or "")
        if handle:
            members.append(handle)
        if kind == "dm" and not user_id:
            username = handle
            user_id = uid
    return {
        "id": cid,
        "kind": kind,
        "title": channel_title(channel, self_id),
        "username": username,
        "user_id": user_id,
        "members": ", ".join(members),
    }


def chat_label(row: dict) -> str:
    """Name plus the ID that tells two same-name chats apart."""
    title = str(row.get("title") or "Chat")
    if row.get("kind") == "group":
        return f"{title}    channel {row.get('id')}    (group)"
    username = str(row.get("username") or "")
    user_id = str(row.get("user_id") or "")
    handle = f"@{username}    " if username else ""
    ident = f"user {user_id}" if user_id else f"channel {row.get('id')}"
    return f"{title}    {handle}{ident}    (DM)"


def public_channel(channel: dict) -> dict:
    recipients = []
    for user in channel.get("recipients") or []:
        kept = public_user(user)
        if kept:
            recipients.append(kept)
    return {
        "id": normalize_id(channel.get("id")),
        "type": channel.get("type"),
        "name": channel.get("name"),
        "icon": channel.get("icon"),
        "owner_id": normalize_id(channel.get("owner_id")),
        "recipients": recipients,
        "last_message_id": normalize_id(channel.get("last_message_id")),
    }


def _load_ids(path: Path) -> set[str]:
    data = read_json(path, [])
    if not isinstance(data, list):
        return set()
    return {cid for item in data if (cid := normalize_id(item))}


def _save_ids(path: Path, ids: set[str]) -> None:
    write_json(path, sorted(ids))


def _check_stop(stop: threading.Event | None) -> None:
    if stop is not None and stop.is_set():
        raise KeyboardInterrupt


def _remember(users: dict[str, dict], user: dict | None) -> None:
    kept = public_user(user)
    if not kept:
        return
    current = users.get(kept["id"], {})
    current.update(kept)
    users[kept["id"]] = current


def _save_avatar(user: dict, avatar_dir: Path, token: str) -> None:
    kept = public_user(user)
    if not kept or not kept.get("avatar"):
        return
    ext = "gif" if str(kept["avatar"]).startswith("a_") else "png"
    dest = avatar_dir / f"{kept['id']}.{ext}"
    try:
        download_url(avatar_url(kept["id"], str(kept["avatar"])), dest, max_bytes=5_000_000, token=token)
    except Exception:
        return


def _account_public(me: dict) -> dict:
    return {
        "id": normalize_id(me.get("id")),
        "username": me.get("username"),
        "global_name": me.get("global_name"),
        "discriminator": me.get("discriminator"),
        "avatar": me.get("avatar"),
    }


def export_archive(
    archive: Path,
    token: str,
    *,
    delay: float = 1.15,
    with_friends: bool = True,
    leave_reopened: bool = False,
    download_media: bool = True,
    include_external: bool = False,
    max_bytes: int | None = None,
    workers: int = 4,
    channel_ids: list[str] | None = None,
    user_ids: list[str] | None = None,
    names: list[str] | None = None,
    only: bool = False,
    force: bool = False,
    log: Log | None = None,
    stop: threading.Event | None = None,
) -> int:
    archive.mkdir(parents=True, exist_ok=True)
    own_log = log is None
    if log is None:
        log = Log(archive / "export.log")
    api = DiscordApi(token, message_interval=delay)
    gateway = GatewayClient(token, log=log)
    gateway.start()
    summary = {
        "channels": 0,
        "messages_new": 0,
        "messages_updated": 0,
        "media_saved": 0,
        "media_failed": 0,
        "skipped": 0,
        "reclosed": 0,
        "incomplete": 0,
    }
    try:
        if only and not (channel_ids or user_ids or names):
            log("Pick at least one chat. Use a name, a user ID, or the chat list.")
            return 1
        log("Copying your own direct messages and files. This does not send any messages.")
        log("Discord's terms prohibit automating a user account. Your account could be disabled.")
        log("Stop is safe. Run the same command again to resume.")
        me = api.get_me()
        if me.get("bot"):
            log("This token belongs to a bot. Bots cannot read your personal DMs.")
            return 1
        self_id = str(me.get("id"))
        write_json(archive / "account.json", _account_public(me))
        users: dict[str, dict] = {}
        existing_users = read_json(archive / "users.json", {})
        if isinstance(existing_users, dict):
            users.update({key: value for key, value in existing_users.items() if isinstance(value, dict)})
        _remember(users, me)
        _save_avatar(me, archive / "avatars", token)

        targets, tool_opened = _discover(
            api,
            archive,
            self_id,
            users,
            with_friends=with_friends,
            channel_ids=channel_ids or [],
            user_ids=user_ids or [],
            names=names or [],
            only=only,
            force=force,
            log=log,
            stop=stop,
        )
        if not targets:
            if only:
                log("None of the selected chats could be opened. Check the name or user ID.")
            else:
                log("No direct messages were found for this account.")
                log("If a closed chat is with someone who is not a friend, paste their user ID and run again.")
            return 1

        if only:
            chosen = ", ".join(channel_title(item["channel"], self_id) for item in targets)
            log(f"Copying only: {chosen}")
        else:
            log(f"Archiving {len(targets)} direct chats.")
        for index, item in enumerate(targets, 1):
            _check_stop(stop)
            channel = item["channel"]
            cid = str(channel["id"])
            title = channel_title(channel, self_id)
            log(f"[{index}/{len(targets)}] {title}")
            try:
                counts = _archive_channel(
                    api,
                    archive,
                    channel,
                    self_id,
                    users,
                    download_media=download_media,
                    include_external=include_external,
                    max_bytes=max_bytes,
                    workers=workers,
                    force=force,
                    log=log,
                    stop=stop,
                )
            except ApiError as exc:
                if exc.fatal:
                    raise
                summary["skipped"] += 1
                folder = channel_dir(archive, cid, title)
                state = read_json(folder / "channel.json", {})
                if not isinstance(state, dict):
                    state = {}
                state.update(
                    {
                        "id": cid,
                        "title": title,
                        "kind": "group" if channel.get("type") == 3 else "dm",
                        "last_error": str(exc),
                        "updated_at": utc_now(),
                    }
                )
                if exc.status in (403, 404):
                    state["inaccessible"] = True
                write_json(folder / "channel.json", state)
                log(f"  skipped: {exc}")
                continue
            summary["channels"] += 1
            summary["messages_new"] += counts["new"]
            summary["messages_updated"] += counts["updated"]
            summary["media_saved"] += counts["saved"]
            summary["media_failed"] += counts["failed"]
            if not counts["complete"]:
                summary["incomplete"] += 1
                log("  history is incomplete; run again to resume from the last saved page")
            if item["reopened"] and not leave_reopened and channel.get("type") == 1 and counts["complete"]:
                if _hide_again(api, cid, title, log):
                    tool_opened.discard(cid)
                    _save_ids(archive / "opened_by_tool.json", tool_opened)
                    summary["reclosed"] += 1
            write_json(archive / "users.json", users)

        write_json(archive / "users.json", users)
        log(
            "Finished. "
            f"Chats: {summary['channels']}. "
            f"New messages: {summary['messages_new']}. "
            f"Updated messages: {summary['messages_updated']}. "
            f"Files saved: {summary['media_saved']}. "
            f"Files missing: {summary['media_failed']}."
        )
        if summary["reclosed"]:
            log(f"Hid {summary['reclosed']} reopened chats again. No messages were sent.")
        log(f"Archive: {archive.resolve()}")
        log("Open index.html in the archive folder, or use Browse in the window.")
        if summary["incomplete"]:
            log(f"{summary['incomplete']} chat(s) still have incomplete history.")
            return 1
        return 0
    except KeyboardInterrupt:
        log("Stopped. Run the same command again to resume.")
        return 130
    except ApiError as exc:
        log(str(exc))
        return 1
    except Exception as exc:
        log(f"Stopped on an error: {exc}")
        log("Run the same download again. Finished pages are kept.")
        return 1
    finally:
        gateway.stop()
        api.close()
        try:
            rebuild_index(archive)
        except Exception as exc:
            log(f"Could not refresh the index: {exc}")
        if own_log:
            log.close()


def _friend_rows(api: DiscordApi, self_id: str, log: Log) -> list[tuple[str, dict, list[str]]]:
    try:
        relationships = api.get_relationships()
    except ApiError as exc:
        if exc.fatal:
            raise
        log(f"Could not read the friend list: {exc}")
        return []
    rows: list[tuple[str, dict, list[str]]] = []
    for rel in relationships:
        if rel.get("type") != 1:
            continue
        user = rel.get("user") if isinstance(rel.get("user"), dict) else {}
        uid = normalize_id(rel.get("id")) or normalize_id(user.get("id"))
        if not uid or uid == self_id:
            continue
        labels: list[str] = []
        for key in ("username", "global_name"):
            value = user.get(key)
            if isinstance(value, str) and value.strip() and value.strip() not in labels:
                labels.append(value.strip())
        nickname = rel.get("nickname")
        if isinstance(nickname, str) and nickname.strip() and nickname.strip() not in labels:
            labels.append(nickname.strip())
        if not labels:
            labels.append(uid)
        rows.append((uid, user, labels))
    return rows


def _open_user_dm(
    api: DiscordApi,
    archive: Path,
    uid: str,
    user: dict | None,
    self_id: str,
    sidebar_ids: set[str],
    open_recipients: set[str],
    tool_opened: set[str],
    add,
    log: Log,
) -> None:
    if uid == self_id:
        return
    if uid in open_recipients:
        return
    try:
        channel = api.create_dm(uid)
    except ApiError as exc:
        if exc.fatal:
            raise
        log(f"Could not open a chat with {display_name(user) if user else uid}: {exc}")
        return
    cid = normalize_id(channel.get("id"))
    if cid is None or channel.get("type") not in DM_TYPES:
        return
    opened_now = cid not in sidebar_ids
    if opened_now and not _keep_reopened(api, archive, channel, user, uid, tool_opened, log):
        log(f"No messages with {display_name(user) if user else uid}. Closed it again.")
        return
    add(channel, opened_now=opened_now)
    log(f"Selected {channel_title(channel, self_id)}")


def list_sidebar(token: str, *, delay: float = 1.15) -> list[dict]:
    api = DiscordApi(token, message_interval=delay)
    try:
        me = api.get_me()
        if me.get("bot"):
            raise SystemExit("This token belongs to a bot. Bots cannot read your personal DMs.")
        self_id = str(me["id"])
        rows = []
        for channel in api.get_private_channels():
            if channel.get("type") not in DM_TYPES:
                continue
            cid = normalize_id(channel.get("id"))
            if cid is None:
                continue
            rows.append(sidebar_row(channel, self_id))
        rows.sort(key=lambda row: row["title"].casefold())
        return rows
    finally:
        api.close()


def _discover(
    api: DiscordApi,
    archive: Path,
    self_id: str,
    users: dict[str, dict],
    *,
    with_friends: bool,
    channel_ids: list[str],
    user_ids: list[str],
    names: list[str],
    only: bool,
    force: bool,
    log: Log,
    stop: threading.Event | None,
) -> tuple[list[dict], set[str]]:
    tool_opened = _load_ids(archive / "opened_by_tool.json")
    targets: dict[str, dict] = {}

    def add(channel: dict, *, opened_now: bool = False) -> None:
        cid = normalize_id(channel.get("id"))
        if cid is None or channel.get("type") not in DM_TYPES:
            return
        for user in channel.get("recipients") or []:
            _remember(users, user)
        reopened = opened_now or (cid in tool_opened and not (only and cid in sidebar_ids))
        current = targets.get(cid)
        if current:
            current["channel"] = channel
            current["reopened"] = current["reopened"] or reopened
            return
        targets[cid] = {"channel": channel, "reopened": reopened}

    try:
        sidebar = [channel for channel in api.get_private_channels() if channel.get("type") in DM_TYPES]
    except ApiError as exc:
        if exc.fatal:
            raise
        log(f"Could not list open DMs: {exc}")
        sidebar = []
    sidebar_ids = {normalize_id(channel.get("id")) for channel in sidebar}
    sidebar_ids.discard(None)
    open_recipients: set[str] = set()
    for channel in sidebar:
        if not only:
            add(channel)
        if channel.get("type") != 1:
            continue
        for user in channel.get("recipients") or []:
            uid = normalize_id(user.get("id"))
            if uid and uid != self_id:
                open_recipients.add(uid)
    log(f"Open sidebar chats: {len(sidebar)}.")

    if with_friends and not only:
        _check_stop(stop)
        try:
            relationships = api.get_relationships()
        except ApiError as exc:
            if exc.fatal:
                raise
            log(f"Could not read the friend list, so closed friend chats were not checked: {exc}")
            relationships = []
        friends = []
        for rel in relationships:
            if rel.get("type") != 1:
                continue
            uid = normalize_id(rel.get("id")) or normalize_id((rel.get("user") or {}).get("id"))
            if uid and uid != self_id and uid not in open_recipients:
                friends.append((uid, rel.get("user") if isinstance(rel.get("user"), dict) else None))
        if friends:
            log(
                f"Checking {len(friends)} friends who are not in the sidebar. "
                "No messages will be sent. Empty chats are closed again."
            )
        for index, (uid, user) in enumerate(friends, 1):
            _check_stop(stop)
            if user:
                _remember(users, user)
            try:
                channel = api.create_dm(uid)
            except ApiError as exc:
                if exc.fatal:
                    raise
                log(f"  could not open a chat with {uid}: {exc}")
                continue
            cid = normalize_id(channel.get("id"))
            if cid is None or channel.get("type") not in DM_TYPES:
                continue
            opened_now = cid not in sidebar_ids
            if opened_now and not _keep_reopened(api, archive, channel, user, uid, tool_opened, log):
                if index % 25 == 0:
                    log(f"  checked {index}/{len(friends)} friends")
                continue
            add(channel, opened_now=opened_now)
            if index % 25 == 0:
                log(f"  checked {index}/{len(friends)} friends")

    if names:
        friend_rows: list[tuple[str, dict, list[str]]] | None = None
        for query in names:
            _check_stop(stop)
            channel, error = pick_channel(query, sidebar, self_id)
            if channel is not None:
                add(channel)
                log(f"Selected {channel_title(channel, self_id)}")
                continue
            if friend_rows is None:
                friend_rows = _friend_rows(api, self_id, log)
            match, match_error = pick_friend(query, friend_rows)
            if match is None:
                log(match_error or error or f"No chat matches {query!r}")
                continue
            uid, user = match
            _open_user_dm(
                api,
                archive,
                uid,
                user,
                self_id,
                sidebar_ids,
                open_recipients,
                tool_opened,
                add,
                log,
            )

    for uid in user_ids:
        _check_stop(stop)
        normalized = normalize_id(uid)
        if normalized is None:
            log(f"Ignoring invalid user ID: {uid}")
            continue
        if normalized == self_id:
            continue
        if normalized in open_recipients:
            for channel in sidebar:
                recipient_ids = {
                    normalize_id(user.get("id"))
                    for user in channel.get("recipients") or []
                    if isinstance(user, dict)
                }
                if normalized in recipient_ids:
                    add(channel)
                    if only:
                        log(f"Selected {channel_title(channel, self_id)}")
                    break
            continue
        try:
            channel = api.create_dm(normalized)
        except ApiError as exc:
            if exc.fatal:
                raise
            log(f"Could not open a chat with user {normalized}: {exc}")
            continue
        cid = normalize_id(channel.get("id"))
        if cid is None:
            continue
        opened_now = cid not in sidebar_ids
        if opened_now and not _keep_reopened(api, archive, channel, None, normalized, tool_opened, log):
            continue
        add(channel, opened_now=opened_now)

    requested = []
    for raw in channel_ids:
        normalized = normalize_id(raw)
        if normalized is None:
            log(f"Ignoring invalid channel ID: {raw}")
            continue
        requested.append(normalized)
    if not only:
        for cid in archive_channel_ids(archive):
            if cid not in targets:
                requested.append(cid)

    seen_requested: set[str] = set()
    for cid in requested:
        if cid in targets or cid in seen_requested:
            continue
        seen_requested.add(cid)
        folder = channel_dir(archive, cid)
        state = read_json(folder / "channel.json", {})
        if isinstance(state, dict) and state.get("inaccessible") and not force:
            continue
        _check_stop(stop)
        try:
            channel = api.get_channel(cid)
        except ApiError as exc:
            if exc.fatal:
                raise
            if exc.status in (403, 404):
                _mark_inaccessible(archive, cid, str(exc))
            log(f"Could not open channel {cid}: {exc}")
            continue
        if channel.get("type") not in DM_TYPES:
            log(f"Skipping {cid}: not a direct message.")
            continue
        add(channel)

    ordered = sorted(targets.values(), key=lambda item: channel_title(item["channel"], self_id).casefold())
    return ordered, tool_opened


def _mark_inaccessible(archive: Path, channel_id: str, error: str) -> None:
    folder = channel_dir(archive, channel_id)
    state = read_json(folder / "channel.json", {})
    if not isinstance(state, dict):
        state = {}
    state.update(
        {
            "id": channel_id,
            "inaccessible": True,
            "last_error": error,
            "updated_at": utc_now(),
        }
    )
    write_json(folder / "channel.json", state)


def _keep_reopened(
    api: DiscordApi,
    archive: Path,
    channel: dict,
    user: dict | None,
    fallback_name: str,
    tool_opened: set[str],
    log: Log,
) -> bool:
    """Remember a chat this run opened. Close it immediately if it has no messages.

    Returns True when the chat should be archived.
    """
    cid = normalize_id(channel.get("id"))
    if cid is None:
        return False
    tool_opened.add(cid)
    _save_ids(archive / "opened_by_tool.json", tool_opened)
    label = display_name(user) if user else fallback_name
    try:
        probe = api.get_messages(cid, limit=1)
    except ApiError as exc:
        if exc.fatal:
            raise
        log(f"  could not read {label}: {exc}")
        return True
    if probe:
        return True
    if _hide_again(api, cid, label, log):
        tool_opened.discard(cid)
        _save_ids(archive / "opened_by_tool.json", tool_opened)
    return False


def _reopen_saved(api: DiscordApi, state: dict) -> dict | None:
    channel = state.get("channel") if isinstance(state.get("channel"), dict) else {}
    if channel.get("type") not in (1, None):
        return None
    for user in channel.get("recipients") or []:
        if not isinstance(user, dict):
            continue
        uid = normalize_id(user.get("id"))
        if uid is None:
            continue
        try:
            return api.create_dm(uid)
        except ApiError as exc:
            if exc.fatal:
                raise
            continue
    return None


def _hide_again(api: DiscordApi, channel_id: str, title: str, log: Log) -> bool:
    try:
        api.close_dm(channel_id)
    except ApiError as exc:
        if exc.fatal:
            raise
        log(f"  could not hide {title} again: {exc}")
        return False
    log(f"  hid {title} again so the sidebar stays as it was")
    return True


def _archive_channel(
    api: DiscordApi,
    archive: Path,
    channel: dict,
    self_id: str,
    users: dict[str, dict],
    *,
    download_media: bool,
    include_external: bool,
    max_bytes: int | None,
    workers: int,
    force: bool,
    log: Log,
    stop: threading.Event | None,
) -> dict[str, int | bool]:
    cid = str(channel["id"])
    folder = channel_dir(archive, cid, channel_title(channel, self_id))
    folder.mkdir(parents=True, exist_ok=True)
    for user in channel.get("recipients") or []:
        _remember(users, user)
        _save_avatar(user, archive / "avatars", api.token)
    state = read_json(folder / "channel.json", {})
    if not isinstance(state, dict):
        state = {}
    if state.get("last_error") == "pagination stopped early":
        state["backfill_complete"] = False
    if force:
        state["backfill_complete"] = False
        state.pop("api_before", None)
        state.pop("inaccessible", None)
    state.update(
        {
            "id": cid,
            "type": channel.get("type"),
            "kind": "group" if channel.get("type") == 3 else "dm",
            "title": channel_title(channel, self_id),
            "channel": public_channel(channel),
            "inaccessible": False,
            "updated_at": utc_now(),
        }
    )
    write_json(folder / "channel.json", state)

    jsonl = folder / "messages.jsonl"
    media_log = folder / "media.jsonl"
    api_signatures = {
        str(message["id"]): _message_digest(message)
        for message in read_jsonl(jsonl)
        if isinstance(message, dict) and is_snowflake(str(message.get("id") or "")) and not message.get("package_only")
    }
    api_ids = set(api_signatures)
    saved_keys, saved_assets = index_saved_media(media_log, folder)
    new_messages = 0
    updated_messages = 0
    saved = 0
    failed = 0

    def persist_page(page: list[dict]) -> tuple[int, int, int]:
        nonlocal new_messages, updated_messages, saved, failed
        page_new = 0
        refs = []
        for message in page:
            mid = str(message.get("id") or "")
            if not is_snowflake(mid):
                continue
            _remember(users, message.get("author") if isinstance(message.get("author"), dict) else None)
            _save_avatar(message.get("author") if isinstance(message.get("author"), dict) else {}, archive / "avatars", api.token)
            signature = _message_digest(message)
            if api_signatures.get(mid) != signature:
                is_new = mid not in api_ids
                message = dict(message)
                message.pop("package_only", None)
                append_jsonl(jsonl, message)
                api_signatures[mid] = signature
                api_ids.add(mid)
                if is_new:
                    page_new += 1
                    new_messages += 1
                else:
                    updated_messages += 1
            if download_media:
                refs.extend(extract_media(message, include_external=include_external))
        page_saved = 0
        page_failed = 0
        if refs:
            records = download_refs(
                refs,
                folder / "media",
                token=api.token,
                include_external=include_external,
                max_bytes=max_bytes,
                workers=workers,
                skip_keys=saved_keys,
                skip_assets=saved_assets,
            )
            for record in records:
                append_jsonl(media_log, record)
                if record["status"] in {"saved", "exists"}:
                    saved_keys.add(record["key"])
                    if record.get("asset") and record.get("path"):
                        saved_assets[str(record["asset"])] = str(record["path"])
                if record["status"] == "saved":
                    page_saved += 1
                    saved += 1
                elif record["status"] == "failed":
                    page_failed += 1
                    failed += 1
        return page_new, page_saved, page_failed

    def note_newest(page: list[dict]) -> None:
        newest = newest_id(page)
        if newest is None:
            return
        current = state.get("newest_id")
        if current and is_snowflake(str(current)) and int(newest) <= int(current):
            return
        state["newest_id"] = newest
        match = next((message for message in page if str(message.get("id")) == newest), None)
        stamp = match.get("timestamp") if isinstance(match, dict) else None
        state["newest_timestamp"] = format_timestamp(stamp or newest)

    pages = 0
    if not state.get("backfill_complete"):
        before = state.get("api_before")
        if before is not None and not is_snowflake(str(before)):
            before = None
        while True:
            _check_stop(stop)
            page = api.get_messages(cid, before=str(before) if before else None, limit=50)
            if not page:
                state["backfill_complete"] = True
                state["last_error"] = None
                break
            oldest = oldest_id(page)
            if not pagination_advanced(str(before) if before else None, oldest):
                state["last_error"] = "pagination stopped early"
                state["backfill_complete"] = False
                log("  pagination stopped early on this chat")
                break
            page_new, page_saved, page_failed = persist_page(page)
            note_newest(page)
            before = oldest
            state["api_before"] = before
            state["message_count"] = len(api_ids)
            state["updated_at"] = utc_now()
            write_json(folder / "channel.json", state)
            pages += 1
            log(
                f"  page {pages}: {page_new} new messages, "
                f"{page_saved} files, {page_failed} missing, {len(api_ids)} stored"
            )
            if len(page) < 50:
                state["backfill_complete"] = True
                state["last_error"] = None
                break

    if api_ids and state.get("backfill_complete"):
        before = None
        while True:
            _check_stop(stop)
            page = api.get_messages(cid, before=before, limit=50)
            if not page:
                break
            oldest = oldest_id(page)
            if not pagination_advanced(before, oldest):
                break
            overlapped = any(str(message.get("id") or "") in api_ids for message in page)
            page_new, page_saved, page_failed = persist_page(page)
            note_newest(page)
            if page_new or page_saved:
                log(f"  caught up {page_new} new messages, {page_saved} files")
            if overlapped or len(page) < 50:
                break
            before = oldest

    state["message_count"] = len(api_ids)
    state["updated_at"] = utc_now()
    write_json(folder / "channel.json", state)
    try:
        write_channel_views(folder, state)
        write_json(folder / "channel.json", state)
    except Exception as exc:
        log(f"  saved the messages, but the readable copy failed: {exc}")
    if updated_messages:
        log(f"  refreshed {updated_messages} changed messages")
    return {
        "new": new_messages,
        "updated": updated_messages,
        "saved": saved,
        "failed": failed,
        "complete": bool(state.get("backfill_complete")),
    }


def retry_media(
    archive: Path,
    token: str,
    *,
    delay: float = 1.15,
    include_external: bool = False,
    max_bytes: int | None = None,
    workers: int = 4,
    log: Log | None = None,
    stop: threading.Event | None = None,
) -> int:
    archive.mkdir(parents=True, exist_ok=True)
    own_log = log is None
    if log is None:
        log = Log(archive / "export.log")
    api = DiscordApi(token, message_interval=delay)
    gateway = GatewayClient(token, log=log)
    gateway.start()
    saved = 0
    failed = 0
    try:
        log("Retrying missing files. Fresh links are requested from Discord when the old ones expired.")
        root = archive / "channels"
        if not root.exists():
            log("No archive yet. Run the download first.")
            return 1
        for folder in sorted(path for path in root.iterdir() if path.is_dir() and channel_id_from_folder(path.name)):
            _check_stop(stop)
            pending: set[str] = set()
            for row in read_jsonl(folder / "media.jsonl"):
                if not isinstance(row, dict):
                    continue
                rel = str(row.get("path") or "")
                missing = row.get("status") == "failed" or (
                    rel and row.get("status") != "skipped" and not (folder / rel).exists()
                )
                mid = str(row.get("message_id") or "")
                if missing and is_snowflake(mid):
                    pending.add(mid)
            if not pending:
                continue
            state = read_json(folder / "channel.json", {})
            cid = channel_id_from_folder(folder.name) or folder.name
            title = state.get("title") if isinstance(state, dict) else cid
            log(f"{title}: {len(pending)} messages with missing files")
            saved_keys, saved_assets = index_saved_media(folder / "media.jsonl", folder)
            tried_reopen = False
            reopened_channel = False
            while pending:
                _check_stop(stop)
                mid = sorted(pending, key=int)[0]
                try:
                    page = api.get_messages(cid, around=mid, limit=50)
                except ApiError as exc:
                    if exc.fatal:
                        raise
                    if exc.status in (403, 404) and not tried_reopen:
                        tried_reopen = True
                        if _reopen_saved(api, state if isinstance(state, dict) else {}):
                            reopened_channel = True
                            opened = _load_ids(archive / "opened_by_tool.json")
                            opened.add(cid)
                            _save_ids(archive / "opened_by_tool.json", opened)
                            continue
                    log(f"  could not refresh {title}: {exc}")
                    failed += len(pending)
                    break
                seen = {str(message.get("id") or "") for message in page}
                refreshed = pending & seen
                if not refreshed:
                    pending.discard(mid)
                    failed += 1
                    continue
                refs = []
                for message in page:
                    if str(message.get("id") or "") in refreshed:
                        refs.extend(extract_media(message, include_external=include_external))
                records = download_refs(
                    refs,
                    folder / "media",
                    token=token,
                    include_external=include_external,
                    max_bytes=max_bytes,
                    workers=workers,
                    skip_keys=saved_keys,
                    skip_assets=saved_assets,
                )
                for record in records:
                    append_jsonl(folder / "media.jsonl", record)
                    if record["status"] in {"saved", "exists"}:
                        saved_keys.add(record["key"])
                        if record.get("asset") and record.get("path"):
                            saved_assets[str(record["asset"])] = str(record["path"])
                    if record["status"] == "saved":
                        saved += 1
                    elif record["status"] == "failed":
                        failed += 1
                pending -= refreshed
            channel_type = state.get("type") if isinstance(state, dict) else None
            if channel_type is None and isinstance(state, dict) and isinstance(state.get("channel"), dict):
                channel_type = state["channel"].get("type")
            if reopened_channel and channel_type == 1 and _hide_again(api, cid, str(title), log):
                opened = _load_ids(archive / "opened_by_tool.json")
                opened.discard(cid)
                _save_ids(archive / "opened_by_tool.json", opened)
            try:
                if isinstance(state, dict):
                    write_channel_views(folder, state)
                    write_json(folder / "channel.json", state)
            except Exception as exc:
                log(f"  files saved, readable copy failed: {exc}")
        log(f"Retry finished. Saved: {saved}. Still missing: {failed}.")
        return 0
    except KeyboardInterrupt:
        log("Stopped. Run the retry again to continue.")
        return 130
    except ApiError as exc:
        log(str(exc))
        return 1
    finally:
        gateway.stop()
        api.close()
        try:
            rebuild_index(archive)
        except Exception:
            pass
        if own_log:
            log.close()


def list_open_dms(token: str, *, delay: float = 1.15) -> int:
    api = DiscordApi(token, message_interval=delay)
    try:
        me = api.get_me()
        if me.get("bot"):
            print("This token belongs to a bot. Bots cannot read your personal DMs.")
            return 1
        self_id = str(me["id"])
        channels = [channel for channel in api.get_private_channels() if channel.get("type") in DM_TYPES]
        print(f"Account: {display_name(me)} ({self_id})")
        print(f"Open direct chats: {len(channels)}")
        for channel in channels:
            print(chat_label(sidebar_row(channel, self_id)))
        return 0
    finally:
        api.close()
