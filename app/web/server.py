"""ローカルWebサーバ（標準ライブラリ http.server・追加依存なし）。

- 127.0.0.1 に bind（localhost 限定：キオスク用途）。
- SSE（/events）でサーバ→ブラウザへ画面状態を push。
- 操作は POST /api/action、カードタッチはリーダースレッド→Terminal→SSE。
"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.context import AppContext
from app.devices.mock import MockCardReader
from app.web.terminal import DURATION_LABELS, Terminal

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_CONTENT_TYPES = {".html": "text/html; charset=utf-8",
                  ".js": "application/javascript; charset=utf-8",
                  ".css": "text/css; charset=utf-8"}


class KioskServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, ctx: AppContext) -> None:
        super().__init__(addr, _Handler)
        self.ctx = ctx
        self.terminal = Terminal(ctx)
        self._clients: set[queue.Queue] = set()
        self._clients_lock = threading.Lock()
        self.terminal.on_change = self.broadcast

        # カードリーダー開始（コールバックはリーダースレッドで走る）
        ctx.card_reader.start(self.terminal.on_card)
        self.terminal.go_standby()

    # ------------------------------------------------ SSE ブロードキャスト
    def register_client(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._clients_lock:
            self._clients.add(q)
        return q

    def unregister_client(self, q: queue.Queue) -> None:
        with self._clients_lock:
            self._clients.discard(q)

    def broadcast(self, state: dict) -> None:
        msg = json.dumps(state, ensure_ascii=False)
        with self._clients_lock:
            for q in self._clients:
                q.put(msg)

    @property
    def is_mock(self) -> bool:
        return isinstance(self.ctx.card_reader, MockCardReader)

    def shutdown_app(self) -> None:
        self.terminal.shutdown()
        self.ctx.card_reader.stop()
        close = getattr(self.ctx.lock, "close", None)
        if callable(close):
            close()


class _Handler(BaseHTTPRequestHandler):
    server: KioskServer  # 型ヒント

    def log_message(self, *args):  # アクセスログを抑制
        pass

    def handle(self):
        # SSE 等でクライアントが切断した際の例外は正常系として黙殺する
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    # --------------------------------------------------------- GET
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send_file(TEMPLATE_DIR / "index.html")
        elif path.startswith("/static/"):
            self._send_file(STATIC_DIR / Path(path).name)
        elif path == "/events":
            self._serve_events()
        elif path == "/api/meta":
            self._send_json(self._meta())
        elif path == "/api/state":
            self._send_json(self.server.terminal.state())
        else:
            self.send_error(404)

    def _meta(self) -> dict:
        t = self.server.terminal
        data = {"item_name": self.server.ctx.cfg.item_name, "mock": self.server.is_mock}
        if self.server.is_mock:
            with self.server.ctx.db_lock:
                members = self.server.ctx.members.list_all()
            data["dev_members"] = [
                {"name": m.name, "idm": m.card_idm, "role": m.role} for m in members
            ]
        return data

    def _serve_events(self):
        q = self.server.register_client()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            # 接続直後に現在状態を送る
            self._sse_write(json.dumps(self.server.terminal.state(), ensure_ascii=False))
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # ハートビート
                    self.wfile.flush()
                    continue
                self._sse_write(msg)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.unregister_client(q)

    def _sse_write(self, data: str):
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    # --------------------------------------------------------- POST
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/action":
            self.send_error(404)
            return
        body = self._read_json()
        result = self._dispatch(body)
        self._send_json(result if result is not None else {"ok": True})

    def _dispatch(self, body: dict):
        t = self.server.terminal
        action = body.get("type")
        if action == "dev_card" and self.server.is_mock:
            self.server.ctx.card_reader.emit(str(body.get("idm", "")).strip())
            return {"ok": True}
        if action == "start":
            t.start()
        elif action == "choose_duration":
            t.choose_duration(int(body["minutes"]))
        elif action == "confirm_return":
            t.confirm_return()
        elif action == "cancel":
            t.cancel()
        elif action == "admin_menu":
            t.admin_menu()
        elif action == "open_member_admin":
            t.open_member_admin()
        elif action == "open_report":
            t.open_report()
        elif action == "admin_self_borrow":
            t.admin_self_borrow()
        elif action == "register_member":
            return t.register_member(body.get("name", ""), body.get("employee_no", ""),
                                     body.get("role", "user"))
        elif action == "set_member_active":
            t.set_member_active(int(body["member_id"]), bool(body["active"]))
        elif action == "export_report":
            return t.export_report(body.get("start", ""), body.get("end", ""),
                                   body.get("path", "lending_log.csv"))
        else:
            return {"ok": False, "message": "unknown action"}
        return {"ok": True}

    # --------------------------------------------------------- helpers
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _send_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, fp: Path):
        if not fp.exists():
            self.send_error(404)
            return
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(fp.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(ctx: AppContext, host: str = "127.0.0.1", port: int = 8000) -> None:
    httpd = KioskServer((host, port), ctx)
    print(f"貸出システム Web: http://{host}:{port}/  （Ctrl+C で停止）")
    if httpd.is_mock:
        print("※ モックモード：画面下の疑似タッチで操作できます")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown_app()
