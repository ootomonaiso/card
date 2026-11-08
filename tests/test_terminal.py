"""WebUI のサーバ側状態機械（画面遷移）のテスト（07 画面設計書）。

Terminal は HTTP を介さずに直接駆動できる。on_change で最新stateを捕捉する。
"""
from __future__ import annotations

import unittest
from datetime import datetime

from app.services.clock import FixedClock
from app.web.terminal import Terminal
from tests.helpers import make_ctx


class TerminalFlowTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx(
            FixedClock(datetime(2026, 11, 8, 9, 0, 0)),
            result_screen_seconds=999,   # 自動復帰タイマは発火させない
            idle_timeout_seconds=999,
        )
        self.ctx.members.register("USER1", "100234", "山田 太郎", "user")
        self.ctx.members.register("USER2", "100567", "鈴木 花子", "user")
        self.ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        self.t = Terminal(self.ctx)
        self.last = {}
        self.t.on_change = lambda s: self.last.update(s)
        self.t.go_standby()

    def tearDown(self):
        self.t.shutdown()

    @property
    def screen(self):
        return self.t.screen

    def test_startup_is_standby(self):
        self.assertEqual(self.screen, "standby")
        self.assertFalse(self.last["data"]["is_lent"])

    def test_unregistered_goes_error(self):
        self.t.on_card("NOPE")
        self.assertEqual(self.screen, "error")
        self.assertIn("登録されていません", self.last["data"]["reason"])

    def test_borrow_flow(self):
        self.t.on_card("USER1")
        self.assertEqual(self.screen, "borrow_time")
        self.t.choose_duration(60)
        self.assertEqual(self.screen, "unlock")
        self.assertEqual(self.last["data"]["mode"], "borrow")
        self.assertEqual(self.ctx.lock.unlock_count, 1)
        self.assertTrue(self.ctx.loans.status().is_lent)

    def test_other_user_blocked_while_lent(self):
        self.t.on_card("USER1"); self.t.choose_duration(60)
        self.t.go_standby()
        self.t.on_card("USER2")
        self.assertEqual(self.screen, "error")

    def test_return_flow(self):
        self.t.on_card("USER1"); self.t.choose_duration(60)
        self.t.go_standby()
        self.t.on_card("USER1")
        self.assertEqual(self.screen, "return_confirm")
        self.t.confirm_return()
        self.assertEqual(self.screen, "unlock")
        self.assertEqual(self.last["data"]["mode"], "return")
        self.assertFalse(self.ctx.loans.status().is_lent)

    def test_admin_menu_and_member_capture(self):
        self.t.on_card("ADMIN1")
        self.assertEqual(self.screen, "admin_menu")
        self.t.open_member_admin()
        self.assertEqual(self.screen, "member_admin")
        # メンバー管理画面でのカードタッチは登録用にIDmを取り込む
        self.t.on_card("NEWCARD")
        self.assertEqual(self.screen, "member_admin")
        self.assertEqual(self.last["data"]["captured_idm"], "NEWCARD")
        r = self.t.register_member("新人 一郎", "100999", "user")
        self.assertTrue(r["ok"])
        self.assertIsNotNone(self.ctx.auth.authenticate("NEWCARD"))

    def test_admin_self_borrow(self):
        self.t.on_card("ADMIN1")
        self.t.admin_self_borrow()
        self.assertEqual(self.screen, "borrow_time")

    def test_standby_shows_borrower(self):
        self.t.on_card("USER1"); self.t.choose_duration(60)
        self.t.go_standby()
        d = self.last["data"]
        self.assertTrue(d["is_lent"])
        self.assertEqual(d["borrower_name"], "山田 太郎")


class RequireTapTest(unittest.TestCase):
    """require_tap_to_start の切替で待受画面が変わる。"""

    def _term(self, require_tap: bool) -> Terminal:
        ctx = make_ctx(FixedClock(datetime(2026, 11, 8, 9, 0, 0)),
                       require_tap_to_start=require_tap,
                       result_screen_seconds=999, idle_timeout_seconds=999)
        ctx.members.register("USER1", "100234", "山田 太郎", "user")
        t = Terminal(ctx)
        self.addCleanup(t.shutdown)
        t.go_standby()
        return t

    def test_direct_standby_when_disabled(self):
        t = self._term(False)
        self.assertEqual(t.screen, "standby")

    def test_attract_shown_when_enabled(self):
        t = self._term(True)
        self.assertEqual(t.screen, "attract")

    def test_card_ignored_on_attract(self):
        # attract 画面ではカードは無視。画面タッチが先
        t = self._term(True)
        t.on_card("USER1")
        self.assertEqual(t.screen, "attract")

    def test_start_then_card_works(self):
        t = self._term(True)
        t.start()
        self.assertEqual(t.screen, "standby")
        t.on_card("USER1")
        self.assertEqual(t.screen, "borrow_time")

    def test_returns_to_attract_as_home(self):
        # 使い終わって go_standby すると attract（ホーム）に戻る
        t = self._term(True)
        t.start(); t.on_card("USER1"); t.choose_duration(60)
        t.go_standby()
        self.assertEqual(t.screen, "attract")


if __name__ == "__main__":
    unittest.main(verbosity=2)
