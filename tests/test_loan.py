"""貸出・返却・状況・延滞（FR-02 / FR-03 / FR-04 / FR-09, CON-3）の単体テスト。"""
from __future__ import annotations

import unittest
from datetime import datetime

from app.services.loan import LoanError
from tests.helpers import make_ctx


class BorrowReturnTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.clock = self.ctx.clock  # FixedClock
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")
        self.hanako = self.ctx.members.register("BB22", "100567", "鈴木 花子", "user")

    def test_borrow_records_loan_and_due(self):
        # FR-02：貸出で due_at = borrowed_at + duration
        loan = self.ctx.loans.borrow(self.taro, 60)
        self.assertEqual(loan.due_at, "2026-11-08 10:00:00")
        self.assertEqual(self.ctx.lock.unlock_count, 1)  # FR-05 解錠
        st = self.ctx.loans.status()
        self.assertTrue(st.is_lent)
        self.assertEqual(st.borrower_name, "山田 太郎")

    def test_second_borrow_blocked_while_lent(self):
        # CON-3：鍵1本。貸出中は他者が借りられない
        self.ctx.loans.borrow(self.taro, 60)
        with self.assertRaises(LoanError):
            self.ctx.loans.borrow(self.hanako, 30)

    def test_invalid_duration_rejected(self):
        with self.assertRaises(LoanError):
            self.ctx.loans.borrow(self.taro, 45)

    def test_return_by_self(self):
        # FR-03：本人が返却 → 以降貸出可能
        self.ctx.loans.borrow(self.taro, 60)
        loan = self.ctx.loans.find_returnable_loan(self.taro)
        self.assertIsNotNone(loan)
        self.ctx.loans.return_loan(loan)
        self.assertFalse(self.ctx.loans.status().is_lent)
        self.ctx.loans.borrow(self.hanako, 30)  # 別の人も借りられる

    def test_return_by_others_blocked_by_default(self):
        # [10] Q6 既定：本人以外は返却不可
        self.ctx.loans.borrow(self.taro, 60)
        self.assertIsNone(self.ctx.loans.find_returnable_loan(self.hanako))

    def test_return_by_others_when_allowed(self):
        self.ctx.cfg.allow_return_by_others = True
        self.ctx.loans.borrow(self.taro, 60)
        self.assertIsNotNone(self.ctx.loans.find_returnable_loan(self.hanako))

    def test_overdue_flag(self):
        # FR-09：返却予定を過ぎると延滞
        self.ctx.loans.borrow(self.taro, 15)
        self.clock.set(datetime(2026, 11, 8, 9, 30, 0))  # 15分超過
        self.assertTrue(self.ctx.loans.status().is_overdue)


if __name__ == "__main__":
    unittest.main(verbosity=2)
