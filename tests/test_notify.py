"""Teams Webhook通知（TeamsNotifier）の単体テスト。

実際のネットワーク送信は _post() に切り出されているため、ここでは _post を
差し替えてフラグ判定・メッセージ内容だけを検証する（スレッド起動やHTTPは見ない）。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.services.notify import TeamsNotifier


class TeamsNotifierTest(unittest.TestCase):
    def _make(self, **kwargs) -> TeamsNotifier:
        n = TeamsNotifier("https://example.invalid/webhook", **kwargs)
        n._post = MagicMock()
        return n

    def test_no_url_is_noop(self):
        # webhook_url が空文字のときは _post がネットワークに触れず即座に戻る
        # （スレッドも立てない）ことだけを確認する。
        n = TeamsNotifier("")
        n._post("test")  # 例外が出ないこと

    def test_overdue_enabled_by_default(self):
        n = self._make()
        n.notify_overdue("物品A", "山田 太郎", "2026/11/08 10:00")
        n._post.assert_called_once()
        self.assertIn("物品A", n._post.call_args[0][0])

    def test_overdue_disabled(self):
        n = self._make(notify_overdue=False)
        n.notify_overdue("物品A", "山田 太郎", "2026/11/08 10:00")
        n._post.assert_not_called()

    def test_error_enabled_by_default(self):
        n = self._make()
        n.notify_error("解錠失敗")
        n._post.assert_called_once()
        self.assertIn("解錠失敗", n._post.call_args[0][0])

    def test_routine_disabled_by_default(self):
        n = self._make()
        n.notify_routine("borrow", "物品A", "山田 太郎")
        n._post.assert_not_called()

    def test_routine_enabled_when_configured(self):
        n = self._make(notify_routine=True)
        n.notify_routine("borrow", "物品A", "山田 太郎")
        n._post.assert_called_once()
        self.assertIn("貸出", n._post.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
