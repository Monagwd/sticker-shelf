# -*- coding: utf-8 -*-
"""可选：上传时让 Claude 看图，给表情包起一个 2–10 个字的名字。

要用的话：
    pip install anthropic
    设置环境变量 ANTHROPIC_API_KEY（或者先 `ant auth login`）
没装 / 没设置也完全没关系：名字自己填就行。

GIF 只会被看到第一帧，动作在后面几帧才出现的，名字可能不准，改一下就好。
"""
from __future__ import annotations

import base64
import os
import re

MODEL = os.environ.get("STICKER_LABEL_MODEL", "claude-opus-5-5")
PROMPT = (
    "这是一张聊天表情包。请用 2 到 10 个汉字给它起一个名字，概括它表达的动作和情绪；"
    "图上有字幕时优先用字幕原话。只输出名字本身，不要引号、标点、解释或其他内容。"
)

try:
    import anthropic
except ImportError:  # 没装 SDK：自动起名关闭
    anthropic = None

_client = None


def available() -> bool:
    return anthropic is not None and bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_PROFILE")
    )


def suggest_label(raw: bytes, media_type: str) -> str:
    """返回一个名字；任何问题（没配置、网络、拒绝）都返回空字符串，不影响上传。"""
    global _client
    if not available():
        return ""
    try:
        _client = _client or anthropic.Anthropic(timeout=60, max_retries=1)
        response = _client.beta.messages.create(
            model=MODEL,
            max_tokens=2000,
            output_config={"effort": "low"},
            # 被安全分类误拦时，由服务端自动换模型重试，不用自己维护名单。
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type,
                        "data": base64.standard_b64encode(raw).decode("ascii"),
                    }},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )
    except anthropic.APIStatusError as error:
        print(f"自动起名失败：Claude 返回 {error.status_code}")
        return ""
    except anthropic.APIConnectionError:
        print("自动起名失败：连不上 Claude")
        return ""
    if response.stop_reason == "refusal":
        return ""
    text = next((block.text for block in response.content if block.type == "text"), "")
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return re.sub(r"^[\"'“”‘’「」《》【】\s]+|[\"'“”‘’「」《》【】。，！？!?,.\s]+$", "", first_line)[:20]
