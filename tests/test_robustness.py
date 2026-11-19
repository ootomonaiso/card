"""本番堅牢化（データ整合性・ハード故障検知・設定検証）のテスト。"""
from __future__ import annotations

import sqlite3
import unittest

from app.config import Config, ConfigError
from app.devices.base import LockRegistry
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

    def test_bad_theme_rejected(self):
        with self.assertRaises(ConfigError):
            Config(theme="blue").validate()

    def test_custom_duration_bounds_validated(self):
        with self.assertRaises(ConfigError):
            Config(custom_duration_min_minutes=100, custom_duration_max_minutes=10).validate()

    def test_locks_duplicate_pin_rejected(self):
        with self.assertRaises(ConfigError):
            Config(locks=[
                {"slot": "a", "gpio_pin": 17, "active_high": True, "item_ids": []},
                {"slot": "b", "gpio_pin": 17, "active_high": True, "item_ids": [1]},
            ]).validate()


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
        self.ctx.loans.lock = LockRegistry.single(MockLock(fail=True))  # 解錠失敗を模擬
        self.item_id = self.ctx.item_repo.default_item().item_id
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")

    def _is_lent(self) -> bool:
        return self.ctx.loans.status_list()[0].is_lent

    def test_borrow_fails_without_recording(self):
        with self.assertRaises(LoanError):
            self.ctx.loans.borrow(self.taro, self.item_id, 60)
        # 解錠できなかったので貸出は成立していない
        self.assertFalse(self._is_lent())

    def test_return_fails_keeps_loan_open(self):
        # まず正常に貸出（解錠成功するロックに戻す）
        self.ctx.loans.lock = LockRegistry.single(MockLock())
        self.ctx.loans.borrow(self.taro, self.item_id, 60)
        loan = self.ctx.loans.find_returnable_loans(self.taro)[0]
        # 返却時に解錠失敗 → 返却扱いにしない
        self.ctx.loans.lock = LockRegistry.single(MockLock(fail=True))
        with self.assertRaises(LoanError):
            self.ctx.loans.return_loan(loan)
        self.assertTrue(self._is_lent())


class MemberDeleteGuardTest(unittest.TestCase):
    """物理削除は保守用。貸借ログがあるメンバーは削除できない（NFR-04）。"""

    def setUp(self):
        self.ctx = make_ctx()
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")

    def test_delete_without_loans_succeeds(self):
        self.ctx.members.delete(self.taro.member_id)
        self.assertIsNone(self.ctx.member_repo.find_by_idm("AA11"))

    def test_delete_with_loans_rejected(self):
        from app.services.member import MemberError
        item_id = self.ctx.item_repo.default_item().item_id
        self.ctx.loans.borrow(self.taro, item_id, 60)
        with self.assertRaises(MemberError):
            self.ctx.members.delete(self.taro.member_id)
        # 無効化は常に可能（通常運用の導線）
        self.ctx.members.deactivate(self.taro.member_id)


class DoubleReturnTest(unittest.TestCase):
    """既に返却済みのログへの返却操作は、記録を壊さず正常終了する。"""

    def setUp(self):
        self.ctx = make_ctx()
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")

    def test_second_return_is_noop(self):
        item_id = self.ctx.item_repo.default_item().item_id
        self.ctx.loans.borrow(self.taro, item_id, 60)
        loan = self.ctx.loans.find_returnable_loans(self.taro)[0]
        self.ctx.loans.return_loan(loan)
        first_returned_at = self.ctx.loan_repo.open_loan_for_item(loan.item_id)
        self.assertIsNone(first_returned_at)  # 返却済み＝貸出中なし
        self.ctx.clock.advance(minutes=5)
        self.ctx.loans.return_loan(loan)  # 古い画面状態からの二重返却 → 例外にしない
        row = self.ctx.conn.execute(
            "SELECT returned_at FROM LOAN WHERE loan_id = ?", (loan.loan_id,)
        ).fetchone()
        # 最初の返却日時が上書きされていないこと
        self.assertEqual(row["returned_at"], "2026-11-08 09:00:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
