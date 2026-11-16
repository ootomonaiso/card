"""MEMBER テーブルのアクセス。"""
from __future__ import annotations

import sqlite3

from app.domain.models import Member


def _row_to_member(row: sqlite3.Row) -> Member:
    return Member(
        member_id=row["member_id"],
        card_idm=row["card_idm"],
        employee_no=row["employee_no"],
        name=row["name"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )


class MemberRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def find_active_by_idm(self, idm: str) -> Member | None:
        """有効なメンバーを IDm で照合（FR-01）。"""
        row = self.conn.execute(
            "SELECT * FROM MEMBER WHERE card_idm = ? AND is_active = 1",
            (idm,),
        ).fetchone()
        return _row_to_member(row) if row else None

    def find_by_idm(self, idm: str) -> Member | None:
        row = self.conn.execute(
            "SELECT * FROM MEMBER WHERE card_idm = ?", (idm,)
        ).fetchone()
        return _row_to_member(row) if row else None

    def get(self, member_id: int) -> Member | None:
        row = self.conn.execute(
            "SELECT * FROM MEMBER WHERE member_id = ?", (member_id,)
        ).fetchone()
        return _row_to_member(row) if row else None

    def list_all(self, include_inactive: bool = True) -> list[Member]:
        sql = "SELECT * FROM MEMBER"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY member_id"
        return [_row_to_member(r) for r in self.conn.execute(sql).fetchall()]

    def insert(
        self, card_idm: str, employee_no: str, name: str, role: str, created_at: str
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO MEMBER(card_idm, employee_no, name, role, is_active, created_at)"
            " VALUES(?, ?, ?, ?, 1, ?)",
            (card_idm, employee_no, name, role, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_active(self, member_id: int, active: bool) -> None:
        self.conn.execute(
            "UPDATE MEMBER SET is_active = ? WHERE member_id = ?",
            (1 if active else 0, member_id),
        )
        self.conn.commit()

    def set_role(self, member_id: int, role: str) -> None:
        self.conn.execute(
            "UPDATE MEMBER SET role = ? WHERE member_id = ?", (role, member_id)
        )
        self.conn.commit()

    def update_profile(self, member_id: int, name: str, employee_no: str) -> None:
        self.conn.execute(
            "UPDATE MEMBER SET name = ?, employee_no = ? WHERE member_id = ?",
            (name, employee_no, member_id),
        )
        self.conn.commit()

    def set_idm(self, member_id: int, card_idm: str) -> None:
        """カード再発行：登録済みメンバーの card_idm を付け替える。"""
        self.conn.execute(
            "UPDATE MEMBER SET card_idm = ? WHERE member_id = ?", (card_idm, member_id)
        )
        self.conn.commit()

    def count_active_admins(self) -> int:
        """有効な管理者（role='admin' かつ is_active=1）の人数（鶏卵問題対策）。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM MEMBER WHERE role = 'admin' AND is_active = 1"
        ).fetchone()
        return int(row["c"])

    def delete(self, member_id: int) -> None:
        self.conn.execute("DELETE FROM MEMBER WHERE member_id = ?", (member_id,))
        self.conn.commit()
