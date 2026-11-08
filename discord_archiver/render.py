from __future__ import annotations

import html
import json
import re
from pathlib import Path

import urllib.parse

from .util import (
    channel_dir,
    channel_id_from_folder,
    display_name,
    format_timestamp,
    human_bytes,
    is_snowflake,
    read_json,
    read_jsonl,
    write_json,
)

MENTION_RE = re.compile(r"<@!?(\d+)>")
EMOJI_RE = re.compile(r"<(a?):([a-zA-Z0-9_]+):(\d+)>")
LINK_RE = re.compile(r"https?://[^\s<>]+")
TOKEN_RE = re.compile(r"(https?://[^\s<>]+)|(<a?:[a-zA-Z0-9_]+:\d+>)|(<@!?\d+>)")

TYPE_LABELS = {
    1: "added someone to the group",
    2: "removed someone from the group",
    3: "started a call",
    4: "changed the group name",
    5: "changed the group icon",
    6: "pinned a message",
    7: "joined",
    18: "started a thread",
    21: "thread starter",
    46: "poll result",
}

AUTHOR_COLORS = (
    "#c73d5e",
    "#d97706",
    "#ca8a04",
    "#16a34a",
    "#0f766e",
    "#2563eb",
    "#7c3aed",
    "#db2777",
    "#0891b2",
    "#ea580c",
)

CHAT_CSS = """
article { display: grid; grid-template-columns: 42px 1fr; gap: 12px; padding: 2px 16px 8px; }
article:hover { background: #2e3035; }
.avatar, .avatar-gap { width: 42px; height: 42px; border-radius: 50%; background: #3f4248; object-fit: cover; }
.avatar-gap { background: transparent; }
.meta { display: flex; gap: 8px; align-items: baseline; }
.author { font-weight: 600; }
time, .edited { color: #949ba4; font-size: 12px; }
.content { overflow-wrap: anywhere; margin-top: 2px; white-space: pre-wrap; }
.content pre { white-space: pre-wrap; background: #2b2d31; border-radius: 4px; padding: 8px; margin: 6px 0; }
.content code { background: #2b2d31; border-radius: 3px; padding: 0 4px; }
.mention { background: #3c4270; color: #c9cdfb; border-radius: 3px; padding: 0 2px; }
.system { color: #949ba4; font-style: italic; }
a { color: #00a8fc; }
.day { display: flex; align-items: center; gap: 12px; color: #949ba4; font-size: 12px; margin: 16px 0 8px; }
.day:before, .day:after { content: ""; flex: 1; height: 1px; background: #3f4147; }
.replybar { display: flex; align-items: center; gap: 6px; color: #b5bac1; font-size: 13px; margin-bottom: 2px; min-width: 0; }
.replyline { width: 2px; align-self: stretch; background: #4e5058; border-radius: 1px; }
.replysnip { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.replythumb { width: 32px; height: 32px; object-fit: cover; border-radius: 4px; }
.files { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.shot { max-width: min(400px, 100%); max-height: 300px; border-radius: 8px; background: #111; display: block; }
video.shot { max-width: min(400px, 100%); }
.files audio { width: min(400px, 100%); }
.filecard { display: flex; gap: 10px; align-items: center; min-width: 220px; max-width: 420px; padding: 10px 12px; background: #2b2d31; border: 1px solid #1e1f22; border-radius: 8px; text-decoration: none; color: inherit; }
.fileicon { width: 30px; height: 36px; border-radius: 3px; background: #5865f2; }
.filename { display: block; color: #00a8fc; font-weight: 600; }
.filesize, .missing { display: block; color: #949ba4; font-size: 12px; }
.embed { display: grid; grid-template-columns: 4px 1fr auto; gap: 8px 12px; max-width: 520px; margin-top: 8px; padding: 8px 12px 10px 0; background: #2b2d31; border-radius: 4px; }
.embed .bar { grid-row: 1 / span 5; border-radius: 4px 0 0 4px; }
.embed .body { min-width: 0; }
.embed .provider, .embed .footer { color: #b5bac1; font-size: 12px; }
.embed .title { font-weight: 650; }
.embed .thumb, .embed .hero { max-width: 160px; max-height: 120px; border-radius: 4px; }
.embed .hero { max-width: 400px; max-height: 300px; margin-top: 8px; }
.fields { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.field { min-width: 140px; }
.field b { display: block; font-size: 13px; }
.reactions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.reaction { background: #2b2d31; border: 1px solid #3f4147; border-radius: 8px; padding: 2px 8px; font-size: 13px; }
.spoiler { filter: blur(12px); cursor: pointer; }
.spoiler.shown, .spoiler:focus { filter: none; }
.emoji { width: 1.45em; height: 1.45em; vertical-align: text-bottom; }
blockquote { margin: 4px 0; padding-left: 10px; border-left: 3px solid #4e5058; color: #dbdee1; }
"""

STYLES = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.45 "gg sans", "Segoe UI", sans-serif; background: #313338; color: #dbdee1; }
header { padding: 16px 22px; background: #2b2d31; border-bottom: 1px solid #1e1f22; display: flex; gap: 12px; align-items: center; }
.mark { width: 40px; height: 40px; border-radius: 12px; background: #5865f2; color: white; display: grid; place-items: center; font-weight: 700; }
h1 { margin: 0; font-size: 18px; }
header p, .note { color: #b5bac1; margin: 2px 0 0; font-size: 13px; }
main { max-width: 980px; margin: 0 auto; padding: 8px 0 48px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #3f4147; }
tr:hover td { background: #2e3035; }
""" + CHAT_CSS


def load_deduped(path: Path) -> list[dict]:
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for message in read_jsonl(path):
        if not isinstance(message, dict):
            continue
        mid = str(message.get("id") or "")
        if not mid:
            continue
        previous = by_id.get(mid)
        if previous is None:
            order.append(mid)
            by_id[mid] = message
            continue
        if previous.get("package_only") and not message.get("package_only"):
            by_id[mid] = message
        elif not message.get("package_only"):
            by_id[mid] = message
    return [by_id[mid] for mid in order]


def known_ids(path: Path) -> tuple[set[str], set[str]]:
    api_ids: set[str] = set()
    any_ids: set[str] = set()
    for message in read_jsonl(path):
        if not isinstance(message, dict):
            continue
        mid = str(message.get("id") or "")
        if not mid:
            continue
        any_ids.add(mid)
        if not message.get("package_only"):
            api_ids.add(mid)
    return api_ids, any_ids


def latest_media(path: Path) -> dict[str, list[dict]]:
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
    return grouped


def plain_content(content: str, mentions: list | None) -> str:
    mentions = mentions or []

    def mention(match: re.Match) -> str:
        uid = match.group(1)
        name = next((display_name(user) for user in mentions if str(user.get("id")) == uid), uid)
        return "@" + name

    text = MENTION_RE.sub(mention, content or "")
    text = EMOJI_RE.sub(lambda match: f":{match.group(2)}:", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def author_color(user_id: str) -> str:
    if user_id.isdigit():
        return AUTHOR_COLORS[int(user_id) % len(AUTHOR_COLORS)]
    return AUTHOR_COLORS[sum(ord(char) for char in user_id) % len(AUTHOR_COLORS)]


def _hold(text: str, pattern: re.Pattern, bucket: list, mark: str) -> str:
    def repl(match: re.Match) -> str:
        bucket.append(match)
        return f"\x00{mark}{len(bucket) - 1}\x00"

    return pattern.sub(repl, text)


def _put_back(text: str, mark: str, render) -> str:
    return re.sub(
        rf"\x00{mark}(\d+)\x00",
        lambda match: render(int(match.group(1))),
        text,
    )


def _inline_format(escaped: str) -> str:
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<u>\1</u>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r"<s>\1</s>", escaped)
    escaped = re.sub(
        r"\|\|(.+?)\|\|",
        r"<span class='spoiler' tabindex='0'>\1</span>",
        escaped,
    )
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", escaped)
    return escaped


def _format_line(line: str, mentions: list, emoji_src: dict[str, str]) -> str:
    codes: list[re.Match] = []
    urls: list[re.Match] = []
    mentions_found: list[re.Match] = []
    emojis: list[re.Match] = []
    line = _hold(line, re.compile(r"`([^`\n]+)`"), codes, "C")
    line = _hold(line, LINK_RE, urls, "U")
    line = _hold(line, MENTION_RE, mentions_found, "M")
    line = _hold(line, EMOJI_RE, emojis, "E")
    text = _inline_format(html.escape(line))

    def code(index: int) -> str:
        return f"<code>{html.escape(codes[index].group(1))}</code>"

    def link(index: int) -> str:
        raw = urls[index].group(0)
        url = raw.rstrip(").,]>\"'")
        trailing = html.escape(raw[len(url) :])
        return f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>{trailing}'

    def mention(index: int) -> str:
        uid = mentions_found[index].group(1)
        name = next((display_name(user) for user in mentions if str(user.get("id")) == uid), uid)
        return f'<span class="mention">@{html.escape(name)}</span>'

    def emoji(index: int) -> str:
        match = emojis[index]
        name, emoji_id = match.group(2), match.group(3)
        src = emoji_src.get(emoji_id)
        if not src:
            return html.escape(f":{name}:")
        return f'<img class="emoji" alt=":{html.escape(name)}:" src="{html.escape(src, quote=True)}">'

    text = _put_back(text, "C", code)
    text = _put_back(text, "U", link)
    text = _put_back(text, "M", mention)
    text = _put_back(text, "E", emoji)
    return text


def discord_html(content: str, mentions: list | None, emoji_src: dict[str, str] | None = None) -> str:
    mentions = mentions or []
    emoji_src = emoji_src or {}
    pieces: list[str] = []
    fence = re.compile(r"```(?:[^\n`]*)\n?(.*?)```", re.S)
    pos = 0
    for match in fence.finditer(content or ""):
        pieces.append(_flow(content[pos : match.start()], mentions, emoji_src))
        pieces.append(f"<pre><code>{html.escape(match.group(1).strip(chr(10)))}</code></pre>")
        pos = match.end()
    pieces.append(_flow((content or "")[pos:], mentions, emoji_src))
    return "".join(part for part in pieces if part)


def _flow(text: str, mentions: list, emoji_src: dict[str, str]) -> str:
    chunks: list[str] = []
    quote: list[str] = []

    def flush() -> None:
        if not quote:
            return
        inner = "<br>\n".join(_format_line(line, mentions, emoji_src) for line in quote)
        chunks.append(f"<blockquote>{inner}</blockquote>")
        quote.clear()

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith(">"):
            quote.append(line[1:].lstrip())
            continue
        flush()
        chunks.append(_format_line(line, mentions, emoji_src))
    flush()
    rendered: list[str] = []
    for chunk in chunks:
        if not rendered:
            rendered.append(chunk)
            continue
        if rendered[-1].startswith("<blockquote") or chunk.startswith("<blockquote"):
            rendered.append(chunk)
        else:
            rendered.append("<br>\n" + chunk)
    return "".join(rendered)


def rich_html(content: str, mentions: list | None, emoji_src: dict[str, str] | None = None) -> str:
    return discord_html(content, mentions, emoji_src)


def message_text(message: dict) -> str:
    parts: list[str] = []
    content = message.get("content") or ""
    if content:
        parts.append(plain_content(content, message.get("mentions")))
    poll = message.get("poll")
    if isinstance(poll, dict):
        question = (poll.get("question") or {}).get("text") or ""
        answers = []
        for answer in poll.get("answers") or []:
            media = answer.get("poll_media") if isinstance(answer, dict) else None
            text = media.get("text") if isinstance(media, dict) else ""
            if text:
                answers.append(f"- {text}")
        if question or answers:
            parts.append("Poll: " + question + ("\n" + "\n".join(answers) if answers else ""))
    call = message.get("call")
    if isinstance(call, dict):
        ended = call.get("ended_timestamp")
        parts.append("Call ended " + format_timestamp(ended) if ended else "Call")
    for snapshot in message.get("message_snapshots") or []:
        inner = snapshot.get("message") if isinstance(snapshot, dict) else None
        if isinstance(inner, dict) and inner.get("content"):
            parts.append("Forwarded: " + plain_content(inner["content"], inner.get("mentions")))
    if not parts:
        label = TYPE_LABELS.get(message.get("type"))
        if label:
            parts.append(label[0].upper() + label[1:])
    return "\n".join(parts)


def reply_line(message: dict) -> str:
    referenced = message.get("referenced_message")
    if not isinstance(referenced, dict):
        reference = message.get("message_reference") or {}
        if message.get("type") == 19 and reference.get("message_id"):
            return "Reply to a deleted or unloaded message"
        return ""
    author = display_name(referenced.get("author"))
    snippet = plain_content(referenced.get("content") or "", referenced.get("mentions")).replace("\n", " ")
    if len(snippet) > 140:
        snippet = snippet[:137] + "..."
    if not snippet:
        snippet = "(attachment or sticker)"
    return f"Reply to {author}: {snippet}"


def write_transcript(path: Path, title: str, channel_id: str, messages: list[dict], media: dict[str, list[dict]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"# {title}\n\n")
        handle.write(f"Channel ID: `{channel_id}`  \n")
        handle.write(f"Messages: {len(messages)}\n\n")
        handle.write("This file is a readable copy. `messages.jsonl` is the complete data.\n\n")
        for message in messages:
            author = display_name(message.get("author"))
            when = format_timestamp(message.get("timestamp") or message.get("id"))
            edited = message.get("edited_timestamp")
            edit = f" (edited {format_timestamp(edited)})" if edited else ""
            handle.write(f"## {author} — {when}{edit}\n\n")
            reply = reply_line(message)
            if reply:
                handle.write(f"> {reply}\n\n")
            body = message_text(message)
            if body:
                for line in body.splitlines() or [""]:
                    handle.write(f"> {line}\n")
                handle.write("\n")
            for item in media.get(str(message.get("id")), []):
                name = item.get("filename") or "file"
                rel = item.get("path") or ""
                if item.get("status") in {"saved", "exists"} and rel:
                    handle.write(f"- file: {name} → `{rel}`\n")
                else:
                    handle.write(f"- missing: {name}\n")
            reactions = []
            for reaction in message.get("reactions") or []:
                if not isinstance(reaction, dict):
                    continue
                emoji = reaction.get("emoji") or {}
                label = emoji.get("name") or "emoji"
                reactions.append(f"{label}×{reaction.get('count', 1)}")
            if reactions:
                handle.write("- reactions: " + ", ".join(reactions) + "\n")
            handle.write("\n")


def _file_html(item: dict) -> str:
    name = html.escape(str(item.get("filename") or "file"))
    rel = str(item.get("path") or "")
    if item.get("status") not in {"saved", "exists"} or not rel:
        return f'<span class="filelink">{name} (not downloaded)</span>'
    href = html.escape(rel, quote=True)
    kind = item.get("display") or "file"
    spoiler = " spoiler" if item.get("spoiler") else ""
    if kind == "image":
        return f'<a href="{href}"><img class="{spoiler.strip()}" alt="{name}" src="{href}"></a>'
    if kind == "video":
        return f'<video class="{spoiler.strip()}" controls src="{href}"></video>'
    if kind == "audio":
        return f'<audio controls src="{href}"></audio>'
    return f'<a class="filelink" href="{href}">{name}</a>'


def emoji_sources(media: dict[str, list[dict]], prefix: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    for items in media.values():
        for item in items:
            if item.get("kind") != "emoji" or item.get("status") not in {"saved", "exists"}:
                continue
            emoji_id = str(item.get("key") or "").split(":")[-1]
            path = str(item.get("path") or "")
            if emoji_id and path and emoji_id not in found:
                found[emoji_id] = prefix + path
    return found


def _saved(item: dict) -> bool:
    return item.get("status") in {"saved", "exists"} and bool(item.get("path"))


def _own_files(items: list[dict]) -> list[dict]:
    own = []
    for item in items:
        kind = str(item.get("kind") or "")
        if kind.startswith(("reply:", "forward:", "emoji", "embed-")):
            continue
        own.append(item)
    return own


def _href(prefix: str, item: dict) -> str:
    return html.escape(prefix + str(item.get("path") or ""), quote=True)


def _file_block(item: dict, prefix: str) -> str:
    name = html.escape(str(item.get("filename") or "file"))
    if not _saved(item):
        return f'<span class="filecard"><span><span class="filename">{name}</span><span class="missing">not saved</span></span></span>'
    href = _href(prefix, item)
    kind = item.get("display") or "file"
    spoiler = " spoiler" if item.get("spoiler") else ""
    if kind == "image":
        return f'<a href="{href}"><img class="shot{spoiler}" alt="{name}" src="{href}"></a>'
    if kind == "video":
        return f'<video class="shot{spoiler}" controls src="{href}"></video>'
    if kind == "audio":
        return f'<audio controls src="{href}"></audio>'
    size = item.get("bytes") or 0
    size_html = f'<span class="filesize">{html.escape(human_bytes(int(size)))}</span>' if size else ""
    return (
        f'<a class="filecard" href="{href}"><span class="fileicon"></span>'
        f"<span><span class='filename'>{name}</span>{size_html}</span></a>"
    )


def _embed_block(message: dict, items: list[dict], prefix: str, emoji_src: dict[str, str]) -> str:
    blocks = []
    by_key = {str(item.get("key") or ""): item for item in items}
    message_id = str(message.get("id") or "")
    for index, embed in enumerate(message.get("embeds") or []):
        if not isinstance(embed, dict):
            continue
        color = embed.get("color")
        bar = f"#{int(color):06x}" if isinstance(color, int) else "#4e5058"
        title = str(embed.get("title") or "")
        url = str(embed.get("url") or "")
        title_html = ""
        if title:
            label = discord_html(title, message.get("mentions"), emoji_src)
            if url.startswith("https://"):
                title_html = f'<div class="title"><a href="{html.escape(url, quote=True)}">{label}</a></div>'
            else:
                title_html = f'<div class="title">{label}</div>'
        provider = embed.get("provider") if isinstance(embed.get("provider"), dict) else {}
        author = embed.get("author") if isinstance(embed.get("author"), dict) else {}
        provider_name = str((provider or {}).get("name") or (author or {}).get("name") or "")
        provider_html = f'<div class="provider">{html.escape(provider_name)}</div>' if provider_name else ""
        description = str(embed.get("description") or "")
        desc_html = f'<div class="content">{discord_html(description, message.get("mentions"), emoji_src)}</div>' if description else ""
        fields = []
        for field in embed.get("fields") or []:
            if not isinstance(field, dict):
                continue
            fields.append(
                "<div class='field'><b>"
                + html.escape(str(field.get("name") or ""))
                + "</b>"
                + discord_html(str(field.get("value") or ""), message.get("mentions"), emoji_src)
                + "</div>"
            )
        fields_html = f'<div class="fields">{"".join(fields)}</div>' if fields else ""
        footer = embed.get("footer") if isinstance(embed.get("footer"), dict) else {}
        footer_text = str((footer or {}).get("text") or "")
        footer_html = f'<div class="footer">{html.escape(footer_text)}</div>' if footer_text else ""
        thumb = by_key.get(f"embed:{message_id}:{index}:thumbnail") or by_key.get(f"embed:{message_id}:{index}:image")
        thumb_html = ""
        if thumb and _saved(thumb) and (thumb.get("display") == "image" or str(thumb.get("kind", "")).endswith(("thumbnail", "image"))):
            href = _href(prefix, thumb)
            thumb_html = f'<img class="thumb" alt="" src="{href}">'
        if not any((title_html, desc_html, fields_html, footer_html, thumb_html, provider_html)):
            continue
        blocks.append(
            f'<div class="embed"><div class="bar" style="background:{bar}"></div>'
            f'<div class="body">{provider_html}{title_html}{desc_html}{fields_html}{footer_html}</div>'
            f"{thumb_html}</div>"
        )
    return "".join(blocks)


def _reply_bar(message: dict, items: list[dict], prefix: str, known_ids: set[str]) -> str:
    referenced = message.get("referenced_message")
    reference = message.get("message_reference") if isinstance(message.get("message_reference"), dict) else {}
    ref_id = ""
    if isinstance(referenced, dict):
        ref_id = str(referenced.get("id") or "")
    elif reference:
        ref_id = str(reference.get("message_id") or "")
    if not ref_id and message.get("type") != 19:
        return ""
    if isinstance(referenced, dict):
        author = display_name(referenced.get("author"))
        snippet = plain_content(referenced.get("content") or "", referenced.get("mentions")).replace("\n", " ")
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        if not snippet:
            snippet = "Click to see the attachment" if ref_id in known_ids else "Attachment"
    elif message.get("type") == 19 or ref_id:
        author = "Unknown"
        snippet = "Original message was deleted"
    else:
        return ""
    link = f'<a href="#m{html.escape(ref_id)}">{html.escape(author)}</a>' if ref_id else html.escape(author)
    thumb = ""
    reply_images = [
        item for item in items
        if str(item.get("kind") or "").startswith("reply:") and item.get("display") == "image" and _saved(item)
    ]
    if reply_images and ref_id in known_ids:
        thumb = f'<img class="replythumb" alt="" src="{_href(prefix, reply_images[0])}">'
    return (
        f'<div class="replybar"><span class="replyline"></span>{link}'
        f'<span class="replysnip">{html.escape(snippet)}</span>{thumb}</div>'
    )


def render_article(
    message: dict,
    items: list[dict],
    *,
    emoji_src: dict[str, str],
    prefix: str = "",
    avatar: str | None = None,
    known_ids: set[str] | None = None,
) -> str:
    known_ids = known_ids or set()
    message_id = str(message.get("id") or "")
    author = html.escape(display_name(message.get("author")))
    author_id = str((message.get("author") or {}).get("id") or "")
    when = html.escape(format_timestamp(message.get("timestamp") or message.get("id")))
    color = author_color(author_id or author)
    body = discord_html(message.get("content") or "", message.get("mentions"), emoji_src)
    extra = message_text(message)
    plain = plain_content(message.get("content") or "", message.get("mentions"))
    if extra and extra != plain:
        body = (body + "<br>\n" + html.escape(extra).replace("\n", "<br>\n")).strip()
    if not body and message.get("type") not in (None, 0, 19):
        body = f"<span class='system'>{html.escape(message_text(message) or 'System message')}</span>"
    edited = " <span class='edited'>(edited)</span>" if message.get("edited_timestamp") else ""
    reply = _reply_bar(message, items, prefix, known_ids)
    files = "".join(_file_block(item, prefix) for item in _own_files(items))
    files_html = f'<div class="files">{files}</div>' if files else ""
    embeds = _embed_block(message, items, prefix, emoji_src)
    reactions = []
    for reaction in message.get("reactions") or []:
        if not isinstance(reaction, dict):
            continue
        emoji = reaction.get("emoji") or {}
        name = str(emoji.get("name") or "emoji")
        emoji_id = str(emoji.get("id") or "")
        src = emoji_src.get(emoji_id)
        glyph = f'<img class="emoji" alt=":{html.escape(name)}:" src="{html.escape(src, quote=True)}">' if src else html.escape(name)
        reactions.append(f'<span class="reaction">{glyph} {int(reaction.get("count") or 1)}</span>')
    reaction_html = f'<div class="reactions">{"".join(reactions)}</div>' if reactions else ""
    if avatar:
        avatar_html = f'<img class="avatar" alt="" src="{html.escape(avatar, quote=True)}">'
    else:
        avatar_html = '<div class="avatar" aria-hidden="true"></div>'
    return (
        f'<article id="m{html.escape(message_id)}">'
        f"{avatar_html}<div>"
        f'<div class="meta"><span class="author" style="color:{color}">{author}</span><time>{when}</time></div>'
        f"{reply}<div class='content'>{body}</div>{edited}{embeds}{files_html}{reaction_html}"
        "</div></article>"
    )


def render_preview(
    title: str,
    channel_id: str,
    messages: list[dict],
    media: dict[str, list[dict]],
    *,
    total: int,
    avatar_dir: Path | None = None,
) -> str:
    emoji_src = emoji_sources(media)
    known_ids = {str(message.get("id") or "") for message in messages}
    avatars: dict[str, str] = {}
    if avatar_dir is not None:
        for message in messages:
            author_id = str((message.get("author") or {}).get("id") or "")
            if author_id in avatars or not is_snowflake(author_id):
                continue
            for ext in (".gif", ".png", ".webp"):
                if (avatar_dir / f"{author_id}{ext}").exists():
                    avatars[author_id] = f"../../avatars/{author_id}{ext}"
                    break
    blocks = []
    last_day = ""
    for message in messages:
        stamp = str(message.get("timestamp") or "")
        day = stamp[:10] if len(stamp) >= 10 and stamp[4] == "-" else ""
        if day and day != last_day:
            last_day = day
            blocks.append(f'<div class="day"><span>{html.escape(day)}</span></div>')
        author_id = str((message.get("author") or {}).get("id") or "")
        blocks.append(
            render_article(
                message,
                media.get(str(message.get("id") or ""), []),
                emoji_src=emoji_src,
                avatar=avatars.get(author_id),
                known_ids=known_ids,
            )
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLES}</style>
</head>
<body>
<header>
  <div class="mark">D</div>
  <div>
    <h1>{html.escape(title)}</h1>
    <p>Direct message · {total} messages · one local copy of each file · nothing is uploaded</p>
  </div>
</header>
<main>
{''.join(blocks)}
</main>
</body>
</html>
"""


def write_channel_views(folder: Path, state: dict) -> list[dict]:
    messages = load_deduped(folder / "messages.jsonl")
    messages.sort(key=lambda message: int(message["id"]) if is_snowflake(str(message.get("id"))) else 0)
    media = latest_media(folder / "media.jsonl")
    title = str(state.get("title") or folder.name)
    channel_id = str(state.get("id") or folder.name)
    write_transcript(folder / "transcript.md", title, channel_id, messages, media)
    preview = render_preview(
        title,
        channel_id,
        messages,
        media,
        total=len(messages),
        avatar_dir=folder.parent.parent / "avatars",
    )
    (folder / "preview.html").write_text(preview, encoding="utf-8")
    state["message_count"] = len(messages)
    if messages:
        state["newest_timestamp"] = messages[-1].get("timestamp") or format_timestamp(messages[-1].get("id"))
    saved = failed = 0
    for items in media.values():
        for item in items:
            if item.get("status") in {"saved", "exists"}:
                saved += 1
            elif item.get("status") == "failed":
                failed += 1
    state["media_saved"] = saved
    state["media_failed"] = failed
    return messages


def _other_user(state: dict, self_id: str) -> dict:
    channel = state.get("channel") if isinstance(state.get("channel"), dict) else {}
    for user in channel.get("recipients") or []:
        if isinstance(user, dict) and str(user.get("id") or "") != self_id:
            return user
    return {}


def _avatar_rel(archive: Path, user_id: str) -> str:
    if not is_snowflake(user_id):
        return ""
    for ext in (".gif", ".png", ".webp"):
        if (archive / "avatars" / f"{user_id}{ext}").exists():
            return f"avatars/{user_id}{ext}"
    return ""


def rebuild_index(archive: Path) -> list[dict]:
    rows = []
    root = archive / "channels"
    account = read_json(archive / "account.json", {})
    self_id = str(account.get("id") or "") if isinstance(account, dict) else ""
    folders = [path for path in root.iterdir() if path.is_dir()] if root.exists() else []
    for folder in folders:
        channel_id = channel_id_from_folder(folder.name)
        if not channel_id:
            continue
        state = read_json(folder / "channel.json", {})
        if not isinstance(state, dict):
            continue
        title = str(state.get("title") or "").strip()
        if title:
            folder = channel_dir(archive, channel_id, title)
        other = _other_user(state, self_id)
        quoted = urllib.parse.quote(folder.name)
        rows.append(
            {
                "id": state.get("id") or channel_id,
                "kind": state.get("kind") or "dm",
                "title": title or folder.name,
                "username": str(other.get("username") or ""),
                "user_id": str(other.get("id") or ""),
                "avatar": _avatar_rel(archive, str(other.get("id") or "")),
                "message_count": state.get("message_count") or 0,
                "backfill_complete": bool(state.get("backfill_complete")),
                "newest_timestamp": state.get("newest_timestamp") or "",
                "media_saved": state.get("media_saved") or 0,
                "media_failed": state.get("media_failed") or 0,
                "last_error": state.get("last_error"),
                "preview": f"channels/{quoted}/preview.html",
                "transcript": f"channels/{quoted}/transcript.md",
            }
        )
    rows.sort(key=lambda row: (str(row.get("title") or "").casefold(), str(row.get("id"))))
    write_json(archive / "channels.json", rows)
    write_index_html(archive, rows)
    return rows


def write_index_html(archive: Path, rows: list[dict]) -> None:
    payload = json.dumps(rows, ensure_ascii=True).replace("<", "\\u003c")
    document = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Discord archiver</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body { display: grid; grid-template-columns: 280px 1fr; font: 15px/1.4 "Segoe UI", sans-serif; background: #313338; color: #dbdee1; overflow: hidden; }
aside { background: #2b2d31; display: flex; flex-direction: column; min-height: 0; border-right: 1px solid #1e1f22; }
aside header { padding: 14px 12px 8px; }
h1 { margin: 0 0 10px; font-size: 16px; }
#filter { width: 100%; background: #1e1f22; color: inherit; border: 0; border-radius: 4px; padding: 8px; }
#chats { overflow: auto; padding: 4px 8px 16px; }
.chat { display: flex; gap: 10px; align-items: center; width: 100%; text-align: left; color: inherit; background: transparent; border: 0; border-radius: 6px; padding: 7px 8px; cursor: pointer; }
.chat:hover { background: #35373c; }
.chat.active { background: #404249; }
.face, .face img { width: 32px; height: 32px; border-radius: 50%; background: #5865f2; object-fit: cover; flex: none; }
.face { display: grid; place-items: center; font-weight: 650; color: white; }
.who { min-width: 0; }
.who strong, .who span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.who span, .empty { color: #949ba4; font-size: 12px; }
main { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
iframe { flex: 1; width: 100%; border: 0; background: #313338; }
.empty { margin: auto; padding: 24px; }
</style>
</head>
<body>
<aside>
  <header>
    <h1>Direct Messages</h1>
    <input id="filter" placeholder="Search chats" autocomplete="off">
  </header>
  <nav id="chats"></nav>
</aside>
<main>
  <p class="empty" id="empty">Select a chat.</p>
  <iframe id="view" hidden title="Conversation"></iframe>
</main>
<script>
const chats = __ROWS__;
const list = document.querySelector("#chats");
const view = document.querySelector("#view");
const empty = document.querySelector("#empty");
const filter = document.querySelector("#filter");
let selected = "";

function label(row) {
  const handle = row.username ? "@" + row.username : (row.kind === "group" ? "Group" : "DM");
  const count = Number(row.message_count || 0).toLocaleString() + " messages";
  return handle + " · " + count;
}

function draw() {
  const needle = filter.value.trim().toLowerCase();
  list.replaceChildren();
  chats.filter((row) => {
    const blob = [row.title, row.username, row.user_id, row.id].join(" ").toLowerCase();
    return !needle || blob.includes(needle);
  }).forEach((row) => {
    const button = document.createElement("button");
    button.className = "chat" + (row.id === selected ? " active" : "");
    button.type = "button";
    const face = document.createElement("span");
    face.className = "face";
    if (row.avatar) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = row.avatar;
      face.append(img);
    } else {
      face.textContent = (row.title || "?").slice(0, 1).toUpperCase();
    }
    const who = document.createElement("span");
    who.className = "who";
    const strong = document.createElement("strong");
    strong.textContent = row.title || row.id;
    const sub = document.createElement("span");
    sub.textContent = label(row);
    who.append(strong, sub);
    button.append(face, who);
    button.addEventListener("click", () => openChat(row.id));
    list.append(button);
  });
}

function openChat(id) {
  const row = chats.find((item) => item.id === id) || chats[0];
  if (!row) return;
  selected = row.id;
  location.hash = row.id;
  empty.hidden = true;
  view.hidden = false;
  if (view.getAttribute("src") !== row.preview) view.src = row.preview;
  draw();
}

filter.addEventListener("input", draw);
const asked = location.hash.replace("#", "");
draw();
if (chats.length) openChat(chats.some((row) => row.id === asked) ? asked : chats[0].id);
</script>
</body>
</html>
"""
    (archive / "index.html").write_text(document.replace("__ROWS__", payload), encoding="utf-8")


def search_archive(archive: Path, query: str, limit: int = 100) -> list[dict]:
    needle = query.casefold()
    hits: list[dict] = []
    seen: set[tuple[str, str]] = set()
    root = archive / "channels"
    if not root.exists() or not needle:
        return hits
    for folder in sorted(root.iterdir(), key=lambda item: item.name):
        channel_id = channel_id_from_folder(folder.name)
        if not folder.is_dir() or not channel_id:
            continue
        state = read_json(folder / "channel.json", {})
        title = state.get("title") if isinstance(state, dict) else channel_id
        for message in load_deduped(folder / "messages.jsonl"):
            if not isinstance(message, dict):
                continue
            mid = str(message.get("id") or "")
            key = (channel_id, mid)
            if key in seen and message.get("package_only"):
                continue
            haystack = message_text(message).casefold()
            names = " ".join(
                str(item.get("filename") or "")
                for item in message.get("attachments") or []
                if isinstance(item, dict)
            )
            if needle not in haystack and needle not in names.casefold():
                continue
            seen.add(key)
            hits.append(
                {
                    "channel_id": channel_id,
                    "title": title,
                    "id": mid,
                    "author": display_name(message.get("author")),
                    "timestamp": format_timestamp(message.get("timestamp") or mid),
                    "text": message_text(message)[:400],
                }
            )
            if len(hits) >= limit:
                return hits
    return hits


def archive_channel_ids(archive: Path) -> list[str]:
    root = archive / "channels"
    if not root.exists():
        return []
    found = [channel_id_from_folder(path.name) for path in root.iterdir() if path.is_dir()]
    return sorted(channel_id for channel_id in found if channel_id)


def channel_folder(archive: Path, channel_id: str) -> Path:
    return channel_dir(archive, channel_id)
