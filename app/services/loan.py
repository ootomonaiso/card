"""貸出・返却サービス（FR-02 / FR-03 / FR-04 / FR-09）。

解錠（FR-05）はこの層から LockController を呼ぶ。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from app.config import Config
from app.devices.base import LockController, LockError
from app.domain.models import Item, Loan, Member
from app.log import audit, get_logger
from app.repository.items import ItemRepository
from app.repository.loans import LoanRepository
from app.repository.members import MemberRepository
from app.services.clock import Clock, from_iso, to_iso

_log = get_logger("loan")


class LoanError(Exception):
    """貸出・返却の業務エラー。"""


@dataclass(frozen=True)
class ItemStatus:
    """待機画面(S01)向けの、1物品ぶんの現在状況。"""
    item_id: int
    name: str
    location: str | None
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
    def status_list(self) -> list[ItemStatus]:
        """全ての有効な物品について、貸出状況を1クエリ分のまとめで返す。

        貸出中ログは list_open() で一括取得し、物品ごとに突き合わせる
        （物品数が増えてもクエリ回数が膨らまないようにする）。
        """
        open_by_item = {ln.item_id: ln for ln in self.loans.list_open()}
        now = self.clock.now()
        result: list[ItemStatus] = []
        for item in self.items.list_active():
            open_loan = open_by_item.get(item.item_id)
            if open_loan is None:
                result.append(ItemStatus(
                    item_id=item.item_id, name=item.name, location=item.location,
                    is_lent=False, borrower_name=None, borrower_employee_no=None,
                    due_at=None, is_overdue=False, open_loan=None,
                ))
                continue
            borrower = self.members.get(open_loan.member_id)
            result.append(ItemStatus(
                item_id=item.item_id, name=item.name, location=item.location,
                is_lent=True,
                borrower_name=borrower.name if borrower else None,
                borrower_employee_no=borrower.employee_no if borrower else None,
                due_at=open_loan.due_at,
                is_overdue=open_loan.is_overdue(now),
                open_loan=open_loan,
            ))
        return result

    def available_items(self) -> list[Item]:
        """いま貸出可能な（有効かつ空いている）物品の一覧。"""
        open_ids = {ln.item_id for ln in self.loans.list_open()}
        return [it for it in self.items.list_active() if it.item_id not in open_ids]

    # ---- 貸出（FR-02） ----
    def borrow(self, member: Member, item_id: int, duration_min: int) -> Loan:
        if duration_min not in self.cfg.duration_choices_min:
            raise LoanError(f"不正な貸出時間です: {duration_min}")
        item = self.items.get(item_id)
        if item is None or not item.is_active:
            raise LoanError("指定された物品は利用できません")
        # 物品ごとに錠1本（CON-3）。空きでなければ貸出不可。
        # 現状は錠が1ch（全物品共用）だが、将来ロッカーを増設して物品ごとに
        # 錠を分ける場合は factory で item_id→LockController を引けるようにし、
        # ここで item に対応する錠を取得して解錠する想定（デバイス層は今回不改造）。
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
    def find_returnable_loans(self, member: Member) -> list[Loan]:
        """このメンバーが返却できる貸出中ログの一覧（複数物品対応）。

        既定は「本人の貸出のみ」。allow_return_by_others=True なら他人の分も可（[10] Q6）。
        本人の貸出を先頭に並べる（自分の分を優先して返せるように）。
        """
        if self.cfg.allow_return_by_others:
            own = self.loans.list_open_for_member(member.member_id)
            own_ids = {ln.loan_id for ln in own}
            others = [ln for ln in self.loans.list_open() if ln.loan_id not in own_ids]
            return own + others
        return self.loans.list_open_for_member(member.member_id)

    def return_loan(self, loan: Loan) -> None:
        now = self.clock.now()
        # 返却も先に解錠する。扉が開かなければ物品を戻せないため、
        # 解錠に失敗したら返却扱いにしない（貸出中のまま）。
        try:
            self.lock.unlock()  # FR-05 解錠
        except LockError as e:
            _log.error("解錠失敗（返却） loan_id=%s: %s", loan.loan_id, e)
            raise LoanError("解錠に失敗しました。係員にお知らせください") from e
        updated = self.loans.mark_returned(loan.loan_id, to_iso(now))
        if updated == 0:
            # 既に返却済み（画面状態が古い等）。扉は開けてしまったが DB は
            # 整合しているため、異常として記録だけ残し正常終了する（NFR-04）。
            _log.warning("返却記録なし（既に返却済み） loan_id=%s", loan.loan_id)
            audit().info("返却スキップ（既に返却済み） loan_id=%s", loan.loan_id)
            return
        audit().info(
            "返却 loan_id=%s member_id=%s returned_at=%s",
            loan.loan_id, loan.member_id, to_iso(now),
        )
