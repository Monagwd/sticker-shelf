# -*- coding: utf-8 -*-
"""表情包小抽屉的核心：存表情包，和把聊天里的 [sticker:编号] 在「人看的」「AI 看的」之间来回翻译。

只用 Python 标准库。数据放在 data/ 下：
    data/stickers.json      名字、开关、时间
    data/images/<编号>.<扩展名>  原图（GIF 原样保存，会动）

AI 只靠「名字」认识表情包：它发 [sticker:u-xxxxxxxxxx]，你的前端把它换成图片；
你发的表情包在交给 AI 之前换成【表情包：名字】，AI 才知道你在表达什么。
"""
from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
IMAGE_DIR = DATA_DIR / "images"
INDEX_PATH = DATA_DIR / "stickers.json"

MAX_BYTES = 5 * 1024 * 1024
MAX_STICKERS = 300
MAX_LABEL = 40
# AI 每轮都会看到可选清单，太长会稀释上下文，所以只给最近的这么多个。
PROMPT_LIMIT = 80

ID_PATTERN = re.compile(r"u-[a-f0-9]{10}")
MARKER_PATTERN = re.compile(r"\[sticker:(u-[a-f0-9]{10})\]")
# AI 有时会把表情包写成文字：【表情包：开心招手】
WRITTEN_PATTERN = re.compile(r"[【\[（(]\s*表情包\s*[：:]\s*([^】\]）)\n]{1,40}?)\s*[】\]）)]")
# 或者在表情包后面多念一遍名字：[sticker:u-…]（开心招手）
ECHO_PATTERN = re.compile(r"\[sticker:(u-[a-f0-9]{10})\](\s*)[（(]\s*([^）)\n]{1,40}?)\s*[）)]")

IMAGE_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)

PROMPT_RULES = (
    "你可以偶尔发一个表情包，格式必须单独成段：[sticker:编号]。"
    "每次最多一个，不要解释这个标记、不要编造编号、不要每次都发。"
    "对方发来的表情包会在聊天记录里写成【表情包：名字】，那是对方在用表情说话，要当成一句话来回应。"
)

LOCK = threading.RLock()


class StickerError(ValueError):
    """给用户看的错误（中文），附带 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:MAX_LABEL]


def sniff_image(raw: bytes) -> tuple[str, str] | None:
    """按文件头认格式，不信文件名：(扩展名, MIME)。"""
    for magic, extension, media_type in IMAGE_TYPES:
        if raw.startswith(magic):
            return extension, media_type
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


# ── 存储 ──────────────────────────────────────────────

def _load() -> list[dict]:
    try:
        items = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in items if isinstance(item, dict) and ID_PATTERN.fullmatch(str(item.get("id", "")))]


def _save(items: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = INDEX_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(INDEX_PATH)


def public(item: dict) -> dict:
    return {
        "id": item["id"],
        "label": item["label"],
        "url": f"/stickers/img/{item['id']}",
        "media_type": item["media_type"],
        "ai_enabled": bool(item.get("ai_enabled", True)),
        "created_at": item["created_at"],
    }


def list_stickers() -> list[dict]:
    with LOCK:
        return [public(item) for item in _load()]


def find(sticker_id: str) -> dict | None:
    if not ID_PATTERN.fullmatch(str(sticker_id or "")):
        return None
    with LOCK:
        return next((item for item in _load() if item["id"] == sticker_id), None)


def image_path(sticker_id: str) -> tuple[Path, str] | None:
    item = find(sticker_id)
    if item is None:
        return None
    path = IMAGE_DIR / item["file"]
    return (path, item["media_type"]) if path.is_file() else None


def add_sticker(raw: bytes, label: str = "") -> dict:
    """保存一张新表情包；label 为空时名字先记成「未命名表情」，可以之后改。"""
    if not raw:
        raise StickerError("图片是空的。", 422)
    if len(raw) > MAX_BYTES:
        raise StickerError("表情包不能超过 5 MB。", 413)
    kind = sniff_image(raw)
    if kind is None:
        raise StickerError("只支持 PNG、JPG、GIF 或 WebP 图片。", 422)
    extension, media_type = kind
    with LOCK:
        items = _load()
        if len(items) >= MAX_STICKERS:
            raise StickerError(f"最多保存 {MAX_STICKERS} 个表情包，请先删除一些。", 409)
        sticker_id = f"u-{secrets.token_hex(5)}"
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        file_name = f"{sticker_id}.{extension}"
        temporary = IMAGE_DIR / f".{file_name}.tmp"
        temporary.write_bytes(raw)
        temporary.replace(IMAGE_DIR / file_name)
        item = {
            "id": sticker_id, "label": clean_label(label) or "未命名表情", "file": file_name,
            "media_type": media_type, "ai_enabled": True, "created_at": now_iso(),
        }
        items.append(item)
        _save(items)
    return public(item)


def update_sticker(sticker_id: str, label: str | None = None, ai_enabled: bool | None = None) -> dict:
    with LOCK:
        items = _load()
        item = next((entry for entry in items if entry["id"] == sticker_id), None)
        if item is None:
            raise StickerError("表情包不存在。", 404)
        if label is not None:
            item["label"] = clean_label(label) or "未命名表情"
        if ai_enabled is not None:
            item["ai_enabled"] = bool(ai_enabled)
        _save(items)
    return public(item)


def delete_sticker(sticker_id: str) -> None:
    with LOCK:
        items = _load()
        item = next((entry for entry in items if entry["id"] == sticker_id), None)
        if item is None:
            raise StickerError("表情包不存在。", 404)
        _save([entry for entry in items if entry["id"] != sticker_id])
        (IMAGE_DIR / item["file"]).unlink(missing_ok=True)


# ── 给 AI 的文字 ──────────────────────────────────────

def labels(*, ai_only: bool = False) -> dict[str, str]:
    """编号 → 名字（先上传的在前）。"""
    with LOCK:
        return {
            item["id"]: item["label"]
            for item in _load()
            if not ai_only or item.get("ai_enabled", True)
        }


def prompt_context() -> str:
    """接在系统提示末尾：发表情包的规矩 + AI 可以选的清单（编号＝名字）。没有可用的就返回空字符串。"""
    choices = list(labels(ai_only=True).items())[-PROMPT_LIMIT:]
    if not choices:
        return ""
    catalog = "；".join(f"{sticker_id}＝{label}" for sticker_id, label in choices)
    return f"{PROMPT_RULES}\n只可从以下表情包中选择（编号＝名字）：{catalog}"


def expand_for_ai(text: str, role: str = "user") -> str:
    """把聊天记录交给 AI 之前调用。

    你发的表情包 → 【表情包：名字】，AI 才读得懂；
    AI 自己发过的 → 保留 [sticker:编号]（只给它看「【表情包：…】」的话，它会学着写这种文字，而不是发真的表情包）；
    已经删掉的 → 【一张已删除的表情包】，免得 AI 再拿这个编号去发。
    """
    text = text or ""
    if not MARKER_PATTERN.search(text):
        return text
    known = labels()

    def replace(match: re.Match) -> str:
        sticker_id = match.group(1)
        if sticker_id not in known:
            return "【一张已删除的表情包】"
        if role == "assistant":
            return f"[sticker:{sticker_id}]"
        return f"【表情包：{known[sticker_id]}】"

    return MARKER_PATTERN.sub(replace, text)


def normalise_reply(text: str) -> str:
    """AI 回复存下来之前调用：把写成文字的【表情包：名字】变回真表情包，去掉紧跟在表情包后面多念的一遍名字。"""
    text = text or ""
    if not (ECHO_PATTERN.search(text) or WRITTEN_PATTERN.search(text)):
        return text
    known = labels()

    def drop_echo(match: re.Match) -> str:
        if known.get(match.group(1)) == match.group(3).strip():
            return f"[sticker:{match.group(1)}]"
        return match.group(0)

    text = ECHO_PATTERN.sub(drop_echo, text)
    by_label = {label: sticker_id for sticker_id, label in labels(ai_only=True).items()}

    def to_marker(match: re.Match) -> str:
        sticker_id = by_label.get(match.group(1).strip())
        return f"[sticker:{sticker_id}]" if sticker_id else match.group(0)

    return WRITTEN_PATTERN.sub(to_marker, text)
