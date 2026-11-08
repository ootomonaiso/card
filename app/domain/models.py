"""ドメインモデル（06_データベース設計書 準拠）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.clock import from_iso


@dataclass(frozen=True)
class Member:
    member_id: int
    card_idm: str
    employee_no: str
    name: str
    role: str  # 'user' | 'admin'
    is_active: bool
    created_at: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class Item:
    item_id: int
    name: str
    location: str | None
    is_active: bool


@dataclass(frozen=True)
class Loan:
    loan_id: int
    member_id: int
    item_id: int
    borrowed_at: str
    duration_min: int
    due_at: str
    returned_at: str | None

    @property
    def is_open(self) -> bool:
        """返却されていない（貸出中）か。"""
        return self.returned_at is None

    def is_overdue(self, now: datetime) -> bool:
        """延滞か（貸出中かつ返却予定を過ぎている）。"""
        return self.is_open and now > from_iso(self.due_at)
