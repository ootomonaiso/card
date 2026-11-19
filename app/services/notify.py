"""Teams Webhook 通知（延滞・ハード異常・通常の貸出/返却）。

Microsoft Teams の incoming webhook に POST するだけの薄いクライアント。
標準ライブラリの urllib のみを使い、requests 等の新規依存は追加しない。
通知はキオスクの操作をブロックしてはならないため、常にデーモンスレッドで
fire-and-forget し、通信失敗は全て握り潰してログにだけ残す。
"""
from __future__ import annotations

import json
import threading
import urllib.request

from app.log import get_logger

_log = get_logger("notify")
_TIMEOUT_SECONDS = 3.0


class TeamsNotifier:
    def __init__(
        self,
        webhook_url: str,
        notify_overdue: bool = True,
        notify_errors: bool = True,
        notify_routine: bool = False,
    ) -> None:
        self.webhook_url = webhook_url
        # メソッド名（notify_overdue 等）と衝突しないよう別名で保持する。
        self._overdue_enabled = notify_overdue
        self._errors_enabled = notify_errors
        self._routine_enabled = notify_routine

    def _post(self, text: str) -> None:
        if not self.webhook_url:
            return  # URL未設定なら完全に no-op（既定の運用コストゼロ）

        def _send() -> None:
            try:
                body = json.dumps({"text": text}).encode("utf-8")
                req = urllib.request.Request(
                    self.webhook_url, data=body,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS)
            except Exception as e:  # ネットワーク異常は解錠等の業務処理を止めない
                _log.warning("Teams Webhook 送信に失敗: %s", e)

        threading.Thread(target=_send, daemon=True).start()

    def notify_overdue(self, item_name: str, member_name: str, due_at: str) -> None:
        if not self._overdue_enabled:
            return
        self._post(f"⏰ 延滞: {item_name}（{member_name} 様 / 返却予定 {due_at}）")

    def notify_error(self, message: str) -> None:
        if not self._errors_enabled:
            return
        self._post(f"⚠️ エラー: {message}")

    def notify_routine(self, action: str, item_name: str, member_name: str) -> None:
        if not self._routine_enabled:
            return
        label = "貸出" if action == "borrow" else "返却"
        self._post(f"{label}: {item_name}（{member_name} 様）")
