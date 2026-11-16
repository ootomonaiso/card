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
        self._guard_last_admin(member_id, "無効化")
        self.members.set_active(member_id, False)
        audit().info("メンバー無効化 member_id=%s", member_id)

    def activate(self, member_id: int) -> None:
        self.members.set_active(member_id, True)
        audit().info("メンバー有効化 member_id=%s", member_id)

    def delete(self, member_id: int) -> None:
        """物理削除（保守用）。貸借ログがあるメンバーは削除できない（NFR-04）。

        通常運用は deactivate（無効化）を使う。UI からは露出しない。
        """
        self._guard_last_admin(member_id, "削除")
        try:
            self.members.delete(member_id)
        except sqlite3.IntegrityError as e:
            raise MemberError(
                "貸借ログがあるため削除できません。無効化を使ってください"
            ) from e
        audit().info("メンバー削除 member_id=%s", member_id)

    def set_role(self, member_id: int, role: str) -> Member:
        """ロール変更（user↔admin）。最後の管理者は user に落とせない。"""
        if role not in ("user", "admin"):
            raise MemberError("ロールが不正です")
        member = self.members.get(member_id)
        if member is None:
            raise MemberError("メンバーが見つかりません")
        if member.role == "admin" and role == "user":
            self._guard_last_admin(member_id, "ロール変更")
        self.members.set_role(member_id, role)
        audit().info("ロール変更 member_id=%s role=%s", member_id, role)
        return self.members.get(member_id)  # type: ignore[return-value]

    def update_profile(self, member_id: int, name: str, employee_no: str) -> Member:
        """氏名・社員番号の編集。"""
        name = (name or "").strip()
        employee_no = (employee_no or "").strip()
        if not name:
            raise MemberError("氏名を入力してください")
        if not employee_no:
            raise MemberError("社員番号を入力してください")
        member = self.members.get(member_id)
        if member is None:
            raise MemberError("メンバーが見つかりません")
        self.members.update_profile(member_id, name, employee_no)
        audit().info(
            "メンバー編集 member_id=%s name=%s employee_no=%s", member_id, name, employee_no
        )
        return self.members.get(member_id)  # type: ignore[return-value]

    def reissue_card(self, member_id: int, card_idm: str) -> Member:
        """カード再発行：既存メンバーの card_idm を新しいカードへ付け替える。"""
        card_idm = (card_idm or "").strip()
        if not card_idm:
            raise MemberError("社員証をタッチしてください（IDm未取得）")
        member = self.members.get(member_id)
        if member is None:
            raise MemberError("メンバーが見つかりません")
        existing = self.members.find_by_idm(card_idm)
        if existing is not None and existing.member_id != member_id:
            raise MemberError("このカードは既に他のメンバーに登録されています")
        try:
            self.members.set_idm(member_id, card_idm)
        except sqlite3.IntegrityError as e:
            raise MemberError("カード再発行に失敗しました（重複の可能性）") from e
        audit().info("カード再発行 member_id=%s", member_id)
        return self.members.get(member_id)  # type: ignore[return-value]

    def has_active_admin(self) -> bool:
        """有効な管理者が1人以上いるか（鶏卵問題の判定に使う）。"""
        return self.members.count_active_admins() > 0

    def register_initial_admin(self, card_idm: str, employee_no: str, name: str) -> Member:
        """初期セットアップ専用：有効な管理者が1人も居ないときだけ使える管理者登録。

        セキュリティ上重要：呼び出し元（setup 画面）の判定だけに頼らず、
        ここでも有効な管理者の有無を再検査して多重に防御する。
        """
        if self.has_active_admin():
            raise MemberError("既に管理者が登録されているため、この操作は使用できません")
        return self.register(card_idm, employee_no, name, "admin")

    def _guard_last_admin(self, member_id: int, action: str) -> None:
        """最後の管理者を無効化・ロール変更・削除できないようにする（鶏卵問題の再発防止）。"""
        member = self.members.get(member_id)
        if member is None:
            return
        if member.role == "admin" and member.is_active and self.members.count_active_admins() <= 1:
            raise MemberError(f"最後の管理者は{action}できません")

    def list_all(self) -> list[Member]:
        return self.members.list_all(include_inactive=True)
