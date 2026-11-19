"""複数ロック対応（ソフト設計）：LockRegistry と factory.create_lock() のテスト。

物理配線は1チャンネルのままで良いという制約（config.locks 未指定時は現行動作と
完全一致）と、item_id ごとに異なるスロットへ振り分けられることを確認する。
"""
from __future__ import annotations

import unittest

from app.config import Config
from app.devices.base import LockRegistry
from app.devices.factory import create_lock
from app.devices.mock import MockLock


class LockRegistrySingleTest(unittest.TestCase):
    def test_single_wraps_bare_controller(self):
        lock = MockLock()
        reg = LockRegistry.single(lock)
        self.assertIs(reg.for_item(1), lock)
        self.assertIs(reg.for_item(9999), lock)  # 未知の item_id も同じ受け皿に落ちる


class CreateLockDefaultConfigTest(unittest.TestCase):
    """locks 未指定（既定）は、現行の「全物品で1ロック共有」と完全に同じ。"""

    def test_default_config_single_shared_lock(self):
        reg = create_lock(Config(lock="mock"))
        a = reg.for_item(1)
        b = reg.for_item(2)
        self.assertIs(a, b)  # 全物品が同じ1個のロックを共有


class CreateLockMultiSlotTest(unittest.TestCase):
    """複数ロック設定（ソフト設計）：item_ids でスロットを明示指定できる。"""

    def setUp(self):
        self.cfg = Config(lock="mock", locks=[
            {"slot": "A", "gpio_pin": 17, "active_high": True, "item_ids": [1, 2]},
            {"slot": "B", "gpio_pin": 18, "active_high": True, "item_ids": []},
        ])
        self.reg = create_lock(self.cfg)

    def test_mapped_items_use_their_slot(self):
        self.assertIsInstance(self.reg.for_item(1), MockLock)
        self.assertIs(self.reg.for_item(1), self.reg.for_item(2))  # 同じスロット=同じ錠

    def test_unmapped_item_falls_back_to_default_slot(self):
        # item_ids を指定していないスロット（B）が受け皿になる
        self.assertIsNot(self.reg.for_item(1), self.reg.for_item(99))

    def test_close_closes_every_distinct_controller(self):
        self.reg.close()  # 例外が出ないこと（MockLockにはcloseが無いので何もしない）


class CreateLockSharedPinTest(unittest.TestCase):
    """同じ gpio_pin を複数スロットで指定しても、コントローラは1個しか作らない。"""

    def test_dedups_controller_by_pin(self):
        cfg = Config(lock="mock", locks=[
            {"slot": "A", "gpio_pin": 17, "active_high": True, "item_ids": [1]},
            {"slot": "B", "gpio_pin": 17, "active_high": True, "item_ids": [2]},
        ])
        reg = create_lock(cfg)
        self.assertIs(reg.for_item(1), reg.for_item(2))


if __name__ == "__main__":
    unittest.main()
