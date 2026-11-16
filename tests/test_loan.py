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
        self.item_id = self.ctx.item_repo.default_item().item_id
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")
        self.hanako = self.ctx.members.register("BB22", "100567", "鈴木 花子", "user")

    def _status(self):
        """単一物品ぶんの状況（status_list の先頭）を返すテスト補助。"""
        return self.ctx.loans.status_list()[0]

    def test_borrow_records_loan_and_due(self):
        # FR-02：貸出で due_at = borrowed_at + duration
        loan = self.ctx.loans.borrow(self.taro, self.item_id, 60)
        self.assertEqual(loan.due_at, "2026-11-08 10:00:00")
        self.assertEqual(self.ctx.lock.unlock_count, 1)  # FR-05 解錠
        st = self._status()
        self.assertTrue(st.is_lent)
        self.assertEqual(st.borrower_name, "山田 太郎")

    def test_second_borrow_blocked_while_lent(self):
        # CON-3：鍵1本。貸出中は同じ物品を他者が借りられない
        self.ctx.loans.borrow(self.taro, self.item_id, 60)
        with self.assertRaises(LoanError):
            self.ctx.loans.borrow(self.hanako, self.item_id, 30)

    def test_invalid_duration_rejected(self):
        with self.assertRaises(LoanError):
            self.ctx.loans.borrow(self.taro, self.item_id, 45)

    def test_borrow_unknown_item_rejected(self):
        with self.assertRaises(LoanError):
            self.ctx.loans.borrow(self.taro, 9999, 60)

    def test_return_by_self(self):
        # FR-03：本人が返却 → 以降貸出可能
        self.ctx.loans.borrow(self.taro, self.item_id, 60)
        loans = self.ctx.loans.find_returnable_loans(self.taro)
        self.assertEqual(len(loans), 1)
        self.ctx.loans.return_loan(loans[0])
        self.assertFalse(self._status().is_lent)
        self.ctx.loans.borrow(self.hanako, self.item_id, 30)  # 別の人も借りられる

    def test_return_by_others_blocked_by_default(self):
        # [10] Q6 既定：本人以外は返却不可
        self.ctx.loans.borrow(self.taro, self.item_id, 60)
        self.assertEqual(self.ctx.loans.find_returnable_loans(self.hanako), [])

    def test_return_by_others_when_allowed(self):
        self.ctx.cfg.allow_return_by_others = True
        self.ctx.loans.borrow(self.taro, self.item_id, 60)
        self.assertEqual(len(self.ctx.loans.find_returnable_loans(self.hanako)), 1)

    def test_overdue_flag(self):
        # FR-09：返却予定を過ぎると延滞
        self.ctx.loans.borrow(self.taro, self.item_id, 15)
        self.clock.set(datetime(2026, 11, 8, 9, 30, 0))  # 15分超過
        self.assertTrue(self._status().is_overdue)


class MultiItemStatusTest(unittest.TestCase):
    """複数物品の状況一覧・複数同時貸出（複数ロッカー運用の想定）。"""

    def setUp(self):
        self.ctx = make_ctx()
        self.item1 = self.ctx.item_repo.default_item().item_id
        self.item2 = self.ctx.item_svc.add_item("予備カメラ", "保管庫B")
        self.item3 = self.ctx.item_svc.add_item("三脚", "保管庫B")
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")
        self.hanako = self.ctx.members.register("BB22", "100567", "鈴木 花子", "user")

    def test_status_list_covers_all_active_items(self):
        statuses = self.ctx.loans.status_list()
        self.assertEqual(len(statuses), 3)
        self.assertEqual({s.item_id for s in statuses},
                         {self.item1, self.item2, self.item3})
        self.assertTrue(all(not s.is_lent for s in statuses))

    def test_available_items_excludes_lent(self):
        self.ctx.loans.borrow(self.taro, self.item1, 60)
        available = self.ctx.loans.available_items()
        self.assertEqual({it.item_id for it in available}, {self.item2, self.item3})

    def test_one_member_can_borrow_multiple_items(self):
        # 1メンバーが複数物品を同時に借りられる（将来の実運用想定）
        self.ctx.loans.borrow(self.taro, self.item1, 60)
        self.ctx.loans.borrow(self.taro, self.item2, 30)
        returnable = self.ctx.loans.find_returnable_loans(self.taro)
        self.assertEqual({ln.item_id for ln in returnable}, {self.item1, self.item2})

    def test_status_list_reports_per_item_borrower(self):
        self.ctx.loans.borrow(self.taro, self.item1, 60)
        self.ctx.loans.borrow(self.hanako, self.item2, 60)
        by_id = {s.item_id: s for s in self.ctx.loans.status_list()}
        self.assertEqual(by_id[self.item1].borrower_name, "山田 太郎")
        self.assertEqual(by_id[self.item2].borrower_name, "鈴木 花子")
        self.assertFalse(by_id[self.item3].is_lent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
