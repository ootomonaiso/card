"""メンバー管理サービス（FR-06）。登録・無効化・削除。"""
from __future__ import annotations

import sqlite3

from app.domain.models import Member
from app.log import audit
from app.repository.members import MemberRepository
from app.services.clock import Clock, to_iso


class MemberError(Exception):
    pass


class MemberService:
    def __init__(self, clock: Clock, members: MemberRepository) -> None:
        self.clock = clock
        self.members = members

    def register(self, card_idm: str, employee_no: str, name: str, role: str = "user") -> Member:
        card_idm = (card_idm or "").strip()
        employee_no = (employee_no or "").strip()
        name = (name or "").strip()
        if not card_idm:
            raise MemberError("社員証をタッチしてください（IDm未取得）")
        if not name:
            raise MemberError("氏名を入力してください")
        if not employee_no:
            raise MemberError("社員番号を入力してください")
        if role not in ("user", "admin"):
            raise MemberError("ロールが不正です")
        existing = self.members.find_by_idm(card_idm)
        if existing is not None:
            raise MemberError("この社員証は既に登録されています")
        try:
            member_id = self.members.insert(
                card_idm, employee_no, name, role, to_iso(self.clock.now())
            )
        except sqlite3.IntegrityError as e:
            raise MemberError("登録に失敗しました（重複の可能性）") from e
        audit().info(
            "メンバー登録 member_id=%s name=%s employee_no=%s role=%s",
            member_id, name, employee_no, role,
        )
        return self.members.get(member_id)  # type: ignore[return-value]

    def deactivate(self, member_id: int) -> None:
        self.members.set_active(member_id, False)
        audit().info("メンバー無効化 member_id=%s", member_id)

    def activate(self, member_id: int) -> None:
        self.members.set_active(member_id, True)
        audit().info("メンバー有効化 member_id=%s", member_id)

    def delete(self, member_id: int) -> None:
        self.members.delete(member_id)
        audit().info("メンバー削除 member_id=%s", member_id)

    def list_all(self) -> list[Member]:
        return self.members.list_all(include_inactive=True)
