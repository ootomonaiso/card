"""本番堅牢化（データ整合性・ハード故障検知・設定検証）のテスト。"""
from __future__ import annotations

import sqlite3
import unittest

from app.config import Config, ConfigError
from app.devices.mock import MockLock
from app.services.clock import to_iso
from app.services.loan import LoanError
from tests.helpers import make_ctx


class ConfigValidationTest(unittest.TestCase):
    def test_valid_default(self):
        Config().validate()  # 例外が出ないこと

    def test_negative_unlock_rejected(self):
        with self.assertRaises(ConfigError):
            Config(unlock_seconds=-1).validate()

    def test_empty_duration_rejected(self):
        with self.assertRaises(ConfigError):
            Config(duration_choices_min=[]).validate()

    def test_bad_duration_value_rejected(self):
        with self.assertRaises(ConfigError):
            Config(duration_choices_min=[15, 0]).validate()

    def test_bad_device_mode_rejected(self):
        with self.assertRaises(ConfigError):
            Config(card_reader="??").validate()


class OpenLoanInvariantTest(unittest.TestCase):
    """貸出中は1件まで、をDBの部分ユニークインデックスが保証する。"""

    def setUp(self):
        self.ctx = make_ctx()
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")
        self.hanako = self.ctx.members.register("BB22", "100567", "鈴木 花子", "user")
        self.item = self.ctx.item_repo.default_item()

    def test_db_rejects_second_open_loan(self):
        # アプリ層のチェックを通さず直接 INSERT しても、DBが二重貸出を拒否する
        now = to_iso(self.ctx.clock.now())
        self.ctx.loan_repo.insert(self.taro.member_id, self.item.item_id, now, 60, now)
        with self.assertRaises(sqlite3.IntegrityError):
            self.ctx.loan_repo.insert(self.hanako.member_id, self.item.item_id, now, 60, now)

    def test_reborrow_allowed_after_return(self):
        now = to_iso(self.ctx.clock.now())
        loan_id = self.ctx.loan_repo.insert(
            self.taro.member_id, self.item.item_id, now, 60, now
        )
        self.ctx.loan_repo.mark_returned(loan_id, now)
        # 返却後は再び貸出レコードを作れる
        self.ctx.loan_repo.insert(self.hanako.member_id, self.item.item_id, now, 60, now)


class LockFailureTest(unittest.TestCase):
    """解錠ハード故障時は記録を残さず業務エラーにする（③）。"""

    def setUp(self):
        self.ctx = make_ctx()
        self.ctx.loans.lock = MockLock(fail=True)  # 解錠失敗を模擬
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")

    def test_borrow_fails_without_recording(self):
        with self.assertRaises(LoanError):
            self.ctx.loans.borrow(self.taro, 60)
        # 解錠できなかったので貸出は成立していない
        self.assertFalse(self.ctx.loans.status().is_lent)

    def test_return_fails_keeps_loan_open(self):
        # まず正常に貸出（解錠成功するロックに戻す）
        self.ctx.loans.lock = MockLock()
        self.ctx.loans.borrow(self.taro, 60)
        loan = self.ctx.loans.find_returnable_loan(self.taro)
        # 返却時に解錠失敗 → 返却扱いにしない
        self.ctx.loans.lock = MockLock(fail=True)
        with self.assertRaises(LoanError):
            self.ctx.loans.return_loan(loan)
        self.assertTrue(self.ctx.loans.status().is_lent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
