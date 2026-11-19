"""UI/UX 改善で追加した機能の単体・結合テスト。

- 貸出延長（FR-16）
- 管理者による強制返却（FR-17）
- 閉め忘れ検知（FR-18）
- ログ閲覧（FR-12）
- 待受のカウントダウン表示（FR-09 補助）
- 設定画面（FR-19）
- 時刻同期ステータス（P7）
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from app.config import Config, ConfigError
from app.devices.mock import MockCamSwitch
from app.services.clock import FixedClock
from app.services.loan import LoanError
from app.services import timesync
from app.web.terminal import Terminal
from tests.helpers import DEFAULT_NOW, make_ctx


# ---------------------------------------------------------------- 延長（FR-16）
class ExtendTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.item_id = self.ctx.item_repo.default_item().item_id
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")

    def test_extend_pushes_due_and_duration(self):
        loan = self.ctx.loans.borrow(self.taro, self.item_id, 60)  # due 10:00
        extended = self.ctx.loans.extend(loan, 30)
        self.assertEqual(extended.due_at, "2026-11-08 10:30:00")
        self.assertEqual(extended.duration_min, 90)
        # DB にも反映されている
        self.assertEqual(self.ctx.loans.status_list()[0].due_at, "2026-11-08 10:30:00")

    def test_extend_overdue_loan(self):
        loan = self.ctx.loans.borrow(self.taro, self.item_id, 15)  # due 09:15
        self.ctx.clock.set(datetime(2026, 11, 8, 10, 0, 0))  # 延滞中
        self.assertTrue(self.ctx.loans.status_list()[0].is_overdue)
        extended = self.ctx.loans.extend(loan, 60)  # 延長で延滞解消できる
        self.assertEqual(extended.due_at, "2026-11-08 10:15:00")
        self.assertFalse(self.ctx.loans.status_list()[0].is_overdue)

    def test_extend_invalid_minutes_rejected(self):
        loan = self.ctx.loans.borrow(self.taro, self.item_id, 60)
        with self.assertRaises(LoanError):
            self.ctx.loans.extend(loan, 0)

    def test_extend_returned_loan_rejected(self):
        loan = self.ctx.loans.borrow(self.taro, self.item_id, 60)
        self.ctx.loans.return_loan(loan)
        with self.assertRaises(LoanError):
            self.ctx.loans.extend(loan, 30)


# ------------------------------------------------- 強制返却 & 閉め忘れ（FR-17/18）
class TerminalFeatureTest(unittest.TestCase):
    def setUp(self):
        self.sensor = MockCamSwitch(locked=False)  # 既定「未施錠」
        self.notifier = MagicMock()
        self.ctx = make_ctx(
            FixedClock(DEFAULT_NOW),
            result_screen_seconds=999, idle_timeout_seconds=999,
            standby_refresh_seconds=999,
            cam_switch="mock", relock_alert_seconds=999, relock_alert_repeat=1,
            lock_sensor=self.sensor, notifier=self.notifier,
        )
        self.ctx.members.register("USER1", "100234", "山田 太郎", "user")
        self.ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        self.t = Terminal(self.ctx)
        self.last = {}
        self.t.on_change = lambda s: self.last.update(s)
        self.t.go_standby()

    def tearDown(self):
        self.t.shutdown()

    def _borrow_as_user(self):
        self.t.on_card("USER1")
        self.t.choose_duration(60)
        self.t.confirm_borrow()
        self.t.go_standby()

    # ---- 強制返却 ----
    def test_admin_force_return(self):
        self._borrow_as_user()
        self.t.on_card("ADMIN1")
        self.assertEqual(self.t.screen, "admin_menu")
        self.assertTrue(self.last["data"]["any_lent"])
        self.t.open_force_return()
        self.assertEqual(self.t.screen, "force_return_select")
        loans = self.last["data"]["loans"]
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0]["borrower_name"], "山田 太郎")
        self.t.choose_force_return(loans[0]["loan_id"])
        self.assertEqual(self.t.screen, "return_confirm")
        # 強制返却中は「借りる」「延長」を出さず、利用者名を見せる
        self.assertFalse(self.last["data"]["allow_borrow"])
        self.assertFalse(self.last["data"]["can_extend"])
        self.assertEqual(self.last["data"]["borrower_name"], "山田 太郎")
        self.t.confirm_return()
        self.assertEqual(self.t.screen, "unlock")
        self.assertFalse(self.ctx.loans.status_list()[0].is_lent)

    def test_force_return_requires_admin(self):
        self._borrow_as_user()
        self.t.on_card("USER1")  # 一般ユーザー（貸出中なので返却画面へ）
        self.t.open_force_return()  # 権限なし → 無視
        self.assertNotEqual(self.t.screen, "force_return_select")

    # ---- 閉め忘れ検知 ----
    def test_relock_alert_when_unlocked(self):
        # センサが「未施錠」のまま確認が走れば通知する
        self.t._check_lock("セキュアカメラ", 1)
        self.notifier.notify_not_locked.assert_called_once()

    def test_no_relock_alert_when_locked(self):
        self.sensor.set_locked(True)
        self.t._check_lock("セキュアカメラ", 1)
        self.notifier.notify_not_locked.assert_not_called()

    def test_no_relock_alert_when_sensor_off(self):
        # cam_switch=off のときは watch を開始しない（タイマが立たない）
        self.ctx.cfg.cam_switch = "off"
        self.t._start_lock_watch("セキュアカメラ")
        self.assertIsNone(self.t._lock_watch_timer)

    # ---- 待受カウントダウン ----
    def test_standby_countdown_soon_flag(self):
        self.t.on_card("USER1")
        self.t.choose_duration(15)  # due 09:15（残り15分 ≤ due_soon_minutes=15）
        self.t.confirm_borrow()
        self.t.go_standby()
        item = self.last["data"]["items"][0]
        self.assertEqual(item["remaining_min"], 15)
        self.assertTrue(item["soon"])

    # ---- ダッシュボード & 時刻同期 ----
    def test_admin_menu_stats(self):
        self._borrow_as_user()
        self.t.on_card("ADMIN1")
        stats = self.last["data"]["stats"]
        self.assertEqual(stats["lent"], 1)
        self.assertIn("time_sync", self.last["data"])

    # ---- 履歴（FR-12） ----
    def test_history_view(self):
        self._borrow_as_user()
        self.t.on_card("ADMIN1")
        self.t.open_history()
        self.assertEqual(self.t.screen, "history")
        self.assertEqual(self.last["data"]["total"], 1)
        self.assertIn("氏名", self.last["data"]["header"])

    # ---- 設定画面（FR-19） ----
    def test_update_settings_persists(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.json"
            self.ctx.cfg._source_path = cfg_path
            self.t.on_card("ADMIN1")
            r = self.t.update_settings({"due_soon_minutes": "30", "show_borrower_name": False})
            self.assertTrue(r["ok"], r)
            self.assertEqual(self.ctx.cfg.due_soon_minutes, 30)  # 即時反映
            self.assertFalse(self.ctx.cfg.show_borrower_name)
            self.assertTrue(cfg_path.exists())  # 永続化
            reloaded = Config.load(cfg_path)
            self.assertEqual(reloaded.due_soon_minutes, 30)

    def test_update_settings_invalid_rejected(self):
        self.t.on_card("ADMIN1")
        r = self.t.update_settings({"due_soon_minutes": "-5"})
        self.assertFalse(r["ok"])
        self.assertEqual(self.ctx.cfg.due_soon_minutes, 15)  # 変更されない

    def test_update_settings_requires_admin(self):
        r = self.t.update_settings({"due_soon_minutes": "30"})
        self.assertFalse(r["ok"])
        self.assertIn("権限", r["message"])


# ---------------------------------------------------------------- 時刻同期（P7）
class TimesyncTest(unittest.TestCase):
    def test_status_is_one_of_expected(self):
        self.assertIn(timesync.ntp_status(), ("synced", "unsynced", "unknown"))

    def test_unknown_on_command_failure(self):
        # timedatectl が無い/失敗する環境では unknown
        orig = timesync.subprocess.run
        timesync.subprocess.run = MagicMock(side_effect=OSError("not found"))
        try:
            self.assertEqual(timesync.ntp_status(), "unknown")
        finally:
            timesync.subprocess.run = orig

    def test_synced_parsing(self):
        orig = timesync.subprocess.run
        timesync.subprocess.run = MagicMock(
            return_value=MagicMock(stdout="yes\n")
        )
        try:
            self.assertEqual(timesync.ntp_status(), "synced")
        finally:
            timesync.subprocess.run = orig


# ---------------------------------------------------------------- config 拡張
class ConfigFeatureTest(unittest.TestCase):
    def test_new_defaults_valid(self):
        c = Config()
        c.validate()
        self.assertEqual(c.due_soon_minutes, 15)

    def test_invalid_due_soon_rejected(self):
        with self.assertRaises(ConfigError):
            Config(due_soon_minutes=0).validate()

    def test_invalid_relock_rejected(self):
        with self.assertRaises(ConfigError):
            Config(relock_alert_seconds=0).validate()
        with self.assertRaises(ConfigError):
            Config(relock_alert_repeat=0).validate()

    def test_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            c = Config(due_soon_minutes=42)
            c.save(p)
            self.assertEqual(Config.load(p).due_soon_minutes, 42)


if __name__ == "__main__":
    unittest.main()
