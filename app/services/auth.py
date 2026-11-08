"""認証サービス（FR-01 / FR-08）。IDm 照合とロール判定。"""
from __future__ import annotations

from app.domain.models import Member
from app.repository.members import MemberRepository


class AuthService:
    def __init__(self, members: MemberRepository) -> None:
        self.members = members

    def authenticate(self, idm: str) -> Member | None:
        """有効な登録メンバーなら Member、未登録/無効なら None。"""
        return self.members.find_active_by_idm(idm)
