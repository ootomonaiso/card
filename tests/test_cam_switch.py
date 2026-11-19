"""施錠検知センサ（LE-53 カムスイッチ）のテスト：デバイス・ファクトリ・管理メニュー表示。"""
from __future__ import annotations

import unittest
from datetime import datetime

from unittest.mock import MagicMock

from app.config import Config
from app.devices.cam_switch import GpioCamSwitch
from app.devices.factory import create_lock_sensor
from app.devices.mock import MockCamSwitch, NullLockSensor
from app.services.clock import FixedClock
from app.web.terminal import Terminal
from tests.helpers import make_ctx


class MockCamSwitchTest(unittest.TestCase):
    def test_default_locked(self):
        s = MockCamSwitch()
        self.assertTrue(s.is_locked())

    def test_set_locked(self):
        s = MockCamSwitch(locked=True)
        s.set_locked(False)
        self.assertFalse(s.is_locked())

    def test_null_sensor_is_unknown(self):
        self.assertIsNone(NullLockSensor().is_locked())


class FactoryTest(unittest.TestCase):
    def test_off_returns_null_sensor(self):
        # 既定（off）は NullLockSensor（状態不明）
        s = create_lock_sensor(Config())
        self.assertIsNone(s.is_locked())

    def test_mock_mode_returns_mock(self):
        s = create_lock_sensor(Config(cam_switch="mock"))
        self.assertIsInstance(s, MockCamSwitch)

    def test_invalid_mode_rejected(self):
        from app.config import ConfigError
        with self.assertRaises(ConfigError):
            Config(cam_switch="bogus").validate()


class FailStreakEscalationTest(unittest.TestCase):
    """連続読み取り失敗が閾値に達したら一度だけ notifier.notify_error を呼ぶ。

    実機 gpiozero.Button への依存を避けるため、__init__ を経由せず属性を直接セットして
    is_locked() のロジックのみを検証する。
    """

    class _FailingButton:
        @property
        def is_pressed(self):
            raise RuntimeError("fail")

    def _make_switch(self, threshold: int, notifier) -> GpioCamSwitch:
        switch = GpioCamSwitch.__new__(GpioCamSwitch)
        switch._btn = self._FailingButton()
        switch._fail_streak_threshold = threshold
        switch._fail_streak = 0
        switch._notifier = notifier
        return switch

    def test_escalates_once_at_threshold(self):
        notifier = MagicMock()
        switch = self._make_switch(threshold=3, notifier=notifier)
        for _ in range(5):
            self.assertIsNone(switch.is_locked())
        notifier.notify_error.assert_called_once()

    def test_streak_resets_on_success(self):
        notifier = MagicMock()
        switch = self._make_switch(threshold=2, notifier=notifier)
        self.assertIsNone(switch.is_locked())
        switch._btn = MagicMock(is_pressed=True)
        self.assertTrue(switch.is_locked())
        self.assertEqual(switch._fail_streak, 0)


class AdminMenuLockStateTest(unittest.TestCase):
    """カムスイッチ有効時は管理メニューに施錠状態を出し、無効時は出さない。"""

    def _admin_menu(self, lock_sensor):
        ctx = make_ctx(FixedClock(datetime(2026, 11, 8, 9, 0, 0)),
                       lock_sensor=lock_sensor,
                       result_screen_seconds=999, idle_timeout_seconds=999)
        ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        t = Terminal(ctx)
        last = {}
        t.on_change = lambda s: last.update(s)
        t.go_standby()
        t.on_card("ADMIN1")   # 管理者ログイン → admin_menu
        self.assertEqual(last["screen"], "admin_menu")
        t.shutdown()
        return last["data"]

    def test_shows_locked(self):
        data = self._admin_menu(MockCamSwitch(locked=True))
        self.assertEqual(data["lock_state"], "locked")

    def test_shows_unlocked(self):
        data = self._admin_menu(MockCamSwitch(locked=False))
        self.assertEqual(data["lock_state"], "unlocked")

    def test_omitted_when_disabled(self):
        data = self._admin_menu(NullLockSensor())
        self.assertNotIn("lock_state", data)


if __name__ == "__main__":
    unittest.main()
