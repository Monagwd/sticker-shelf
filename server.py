#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表情包小抽屉 · 单文件小服务（只用 Python 标准库）。

    python3 server.py            # 然后浏览器打开 http://127.0.0.1:8767

它做三件事：
1. 端出 web/ 里的管理页：上传、改名、开关「小机能不能用」、删除；
2. 端出图片：GET /stickers/img/<编号>，你的聊天前端把 [sticker:编号] 换成这张图；
3. 给你的 AI 三条接口（见 README）：
   GET  /stickers/context     接在系统提示末尾：规矩 + 小机能选的表情包清单
   POST /stickers/expand      聊天记录交给小机之前：你发的表情包 → 【表情包：名字】
   POST /stickers/normalize   小机的回复存下来之前：写成文字的表情包 → 真表情包
"""
import json
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import labeler  # noqa: E402
import stickers  # noqa: E402

HOST, PORT = "127.0.0.1", 8767
PORT_TRIES = 12
MAX_JSON = 64 * 1024


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "web"), **kw)

    def log_message(self, fmt, *args):  # 只打接口，静态文件不刷屏
        if "/stickers/" in (args[0] if args else "") and "/stickers/img/" not in (args[0] if args else ""):
            super().log_message(fmt, *args)

    # ── 小工具 ──
    def _send(self, body: bytes, content_type: str, code: int = 200, cors: bool = False, cache: str = "no-store"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if cors:  # 读接口允许你自己别的端口上的前端来调
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200, cors: bool = False):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code, cors)

    def _error(self, message: str, code: int = 400):
        self._json({"error": message}, code)

    def _same_origin(self) -> bool:
        """改数据的接口只给本页面用：别的网站不能偷偷替你上传或删除。"""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return urlsplit(origin).netloc == host

    def _body(self, limit: int) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise stickers.StickerError("内容太大了。", 413)
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict:
        try:
            data = json.loads(self._body(MAX_JSON) or b"{}")
        except ValueError as error:
            raise stickers.StickerError("请求不是有效的 JSON。") from error
        if not isinstance(data, dict):
            raise stickers.StickerError("请求不是有效的 JSON。")
        return data

    # ── 路由 ──
    def do_OPTIONS(self):
        self._send(b"", "text/plain", 204, cors=True)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/stickers/api/list":
            return self._json({"items": stickers.list_stickers(), "auto_label": labeler.available()})
        if path == "/stickers/context":
            return self._send(stickers.prompt_context().encode("utf-8"), "text/plain; charset=utf-8", cors=True)
        if path.startswith("/stickers/img/"):
            found = stickers.image_path(path.rsplit("/", 1)[-1])
            if found is None:
                return self._error("表情包不存在。", 404)
            file_path, media_type = found
            return self._send(file_path.read_bytes(), media_type, cors=True, cache="public, max-age=604800")
        return super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            if path == "/stickers/expand":
                data = self._json_body()
                role = "assistant" if data.get("role") == "assistant" else "user"
                return self._json({"text": stickers.expand_for_ai(str(data.get("text") or ""), role)}, cors=True)
            if path == "/stickers/normalize":
                return self._json({"text": stickers.normalise_reply(str(self._json_body().get("text") or ""))}, cors=True)
            if not self._same_origin():
                return self._error("只能在表情包小抽屉自己的页面里修改。", 403)
            if path == "/stickers/api/upload":
                raw = self._body(stickers.MAX_BYTES + 1)
                label = unquote(self.headers.get("X-Label") or "")
                auto = False
                if not stickers.clean_label(label):
                    kind = stickers.sniff_image(raw)
                    label = labeler.suggest_label(raw, kind[1]) if kind and len(raw) <= stickers.MAX_BYTES else ""
                    auto = bool(label)
                return self._json({**stickers.add_sticker(raw, label), "auto_labelled": auto}, 201)
            if path == "/stickers/api/update":
                data = self._json_body()
                enabled = data.get("ai_enabled")
                return self._json(stickers.update_sticker(
                    str(data.get("id") or ""),
                    label=data["label"] if isinstance(data.get("label"), str) else None,
                    ai_enabled=enabled if isinstance(enabled, bool) else None,
                ))
            if path == "/stickers/api/delete":
                stickers.delete_sticker(str(self._json_body().get("id") or ""))
                return self._json({"ok": True})
        except stickers.StickerError as error:
            return self._error(str(error), error.status)
        return self._error("没有这个接口。", 404)


def serve():
    # 端口被占就往后挪，免得撞上别的程序。
    for port in range(PORT, PORT + PORT_TRIES):
        try:
            server = ThreadingHTTPServer((HOST, port), Handler)
        except OSError:
            continue
        print(f"表情包小抽屉开在 http://{HOST}:{port}  （关掉这个窗口就停了）")
        if not labeler.available():
            print("没有配置 Claude，自动起名关闭：上传时自己填名字就好（见 README）。")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return
    print(f"{PORT}–{PORT + PORT_TRIES - 1} 端口都被占用了，关掉一些程序再试。")
    sys.exit(1)


if __name__ == "__main__":
    serve()
