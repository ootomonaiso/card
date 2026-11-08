"""貸出・返却サービス（FR-02 / FR-03 / FR-04 / FR-09）。

解錠（FR-05）はこの層から LockController を呼ぶ。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from app.config import Config
from app.devices.base import LockController, LockError
from app.domain.models import Loan, Member
from app.log import audit, get_logger
from app.repository.items import ItemRepository
from app.repository.loans import LoanRepository
from app.repository.members import MemberRepository
from app.services.clock import Clock, from_iso, to_iso

_log = get_logger("loan")


class LoanError(Exception):
    """貸出・返却の業務エラー。"""


@dataclass(frozen=True)
class LoanStatus:
    """待機画面(S01)向けの現在状況。"""
    is_lent: bool
    borrower_name: str | None
    borrower_employee_no: str | None
    due_at: str | None          # ISO
    is_overdue: bool
    open_loan: Loan | None


class LoanService:
    def __init__(
        self,
        cfg: Config,
        clock: Clock,
        members: MemberRepository,
        items: ItemRepository,
        loans: LoanRepository,
        lock: LockController,
    ) -> None:
        self.cfg = cfg
        self.clock = clock
        self.members = members
        self.items = items
        self.loans = loans
        self.lock = lock

    # ---- 状況（FR-04 / FR-09） ----
    def status(self) -> LoanStatus:
        item = self.items.default_item()
        open_loan = self.loans.open_loan_for_item(item.item_id)
        if open_loan is None:
            return LoanStatus(False, None, None, None, False, None)
        borrower = self.members.get(open_loan.member_id)
        now = self.clock.now()
        return LoanStatus(
            is_lent=True,
            borrower_name=borrower.name if borrower else None,
            borrower_employee_no=borrower.employee_no if borrower else None,
            due_at=open_loan.due_at,
            is_overdue=open_loan.is_overdue(now),
            open_loan=open_loan,
        )

    # ---- 貸出（FR-02） ----
    def borrow(self, member: Member, duration_min: int) -> Loan:
        if duration_min not in self.cfg.duration_choices_min:
            raise LoanError(f"不正な貸出時間です: {duration_min}")
        item = self.items.default_item()
        # 鍵は1本（CON-3）。空きでなければ貸出不可。
        if self.loans.count_open(item.item_id) > 0:
            raise LoanError("貸出中のため借りられません")

        now = self.clock.now()
        due = now + timedelta(minutes=duration_min)

        # 先に解錠する（扉が開いて初めて貸出成立とする）。
        # ハード故障時は記録を残さず失敗させ、「貸出中なのに扉が開いていない」
        # 不整合を防ぐ（③ハード故障の検知と表示）。
        try:
            self.lock.unlock()  # FR-05 解錠
        except LockError as e:
            _log.error("解錠失敗（貸出） member_id=%s: %s", member.member_id, e)
            raise LoanError("解錠に失敗しました。係員にお知らせください") from e

        try:
            loan_id = self.loans.insert(
                member_id=member.member_id,
                item_id=item.item_id,
                borrowed_at=to_iso(now),
                duration_min=duration_min,
                due_at=to_iso(due),
            )
        except sqlite3.IntegrityError as e:
            # 部分ユニークインデックス（貸出中は1件）に抵触＝直前に他経路で貸出確定。
            _log.error("貸出記録の競合 member_id=%s: %s", member.member_id, e)
            raise LoanError("貸出中のため借りられません") from e

        audit().info(
            "貸出 loan_id=%s member_id=%s name=%s item=%s duration_min=%s due=%s",
            loan_id, member.member_id, member.name, item.name, duration_min, to_iso(due),
        )
        return Loan(
            loan_id=loan_id,
            member_id=member.member_id,
            item_id=item.item_id,
            borrowed_at=to_iso(now),
            duration_min=duration_min,
            due_at=to_iso(due),
            returned_at=None,
        )

    # ---- 返却（FR-03） ----
    def find_returnable_loan(self, member: Member) -> Loan | None:
        """このメンバーが返却できる貸出中ログ。

        既定は「本人の貸出のみ」。allow_return_by_others=True なら他人の分も可（[10] Q6）。
        """
        item = self.items.default_item()
        open_loan = self.loans.open_loan_for_item(item.item_id)
        if open_loan is None:
            return None
        if open_loan.member_id == member.member_id:
            return open_loan
        if self.cfg.allow_return_by_others:
            return open_loan
        return None

    def return_loan(self, loan: Loan) -> None:
        now = self.clock.now()
        # 返却も先に解錠する。扉が開かなければ物品を戻せないため、
        # 解錠に失敗したら返却扱いにしない（貸出中のまま）。
        try:
            self.lock.unlock()  # FR-05 解錠
        except LockError as e:
            _log.error("解錠失敗（返却） loan_id=%s: %s", loan.loan_id, e)
            raise LoanError("解錠に失敗しました。係員にお知らせください") from e
        self.loans.mark_returned(loan.loan_id, to_iso(now))
        audit().info(
            "返却 loan_id=%s member_id=%s returned_at=%s",
            loan.loan_id, loan.member_id, to_iso(now),
        )
