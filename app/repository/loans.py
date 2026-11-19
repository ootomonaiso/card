"""LOAN テーブルのアクセス。追記主体（NFR-04）。"""
from __future__ import annotations

import sqlite3

from app.domain.models import Loan


def _row_to_loan(row: sqlite3.Row) -> Loan:
    return Loan(
        loan_id=row["loan_id"],
        member_id=row["member_id"],
        item_id=row["item_id"],
        borrowed_at=row["borrowed_at"],
        duration_min=row["duration_min"],
        due_at=row["due_at"],
        returned_at=row["returned_at"],
    )


class LoanRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def open_loan_for_item(self, item_id: int) -> Loan | None:
        """貸出中（returned_at IS NULL）のログ。無ければ空き。"""
        row = self.conn.execute(
            "SELECT * FROM LOAN WHERE item_id = ? AND returned_at IS NULL"
            " ORDER BY loan_id DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        return _row_to_loan(row) if row else None

    def list_open(self) -> list[Loan]:
        """全物品の貸出中（returned_at IS NULL）ログを item_id 昇順で返す。

        物品ごとの状況一覧（status_list）を1クエリで組み立てるために使う。
        部分ユニークインデックス idx_loan_one_open により、物品ごとに最大1件。
        """
        rows = self.conn.execute(
            "SELECT * FROM LOAN WHERE returned_at IS NULL ORDER BY item_id"
        ).fetchall()
        return [_row_to_loan(r) for r in rows]

    def list_open_for_member(self, member_id: int) -> list[Loan]:
        """指定メンバーの貸出中ログ（本人の返却候補）。"""
        rows = self.conn.execute(
            "SELECT * FROM LOAN WHERE member_id = ? AND returned_at IS NULL"
            " ORDER BY item_id",
            (member_id,),
        ).fetchall()
        return [_row_to_loan(r) for r in rows]

    def open_item_ids(self) -> set[int]:
        """いま貸出中（returned_at IS NULL）の物品IDの集合。

        「貸出中かどうか」の判定を一箇所に集約するための共有ヘルパ
        （status_list / available_items / 物品管理の状況表示が同じ定義を使う）。
        """
        return {ln.item_id for ln in self.list_open()}

    def count_open(self, item_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM LOAN WHERE item_id = ? AND returned_at IS NULL",
            (item_id,),
        ).fetchone()
        return int(row["c"])

    def insert(
        self,
        member_id: int,
        item_id: int,
        borrowed_at: str,
        duration_min: int,
        due_at: str,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO LOAN(member_id, item_id, borrowed_at, duration_min, due_at)"
            " VALUES(?, ?, ?, ?, ?)",
            (member_id, item_id, borrowed_at, duration_min, due_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def mark_returned(self, loan_id: int, returned_at: str) -> int:
        """返却日時を記録する。更新できた行数（0=既に返却済み等）を返す。"""
        cur = self.conn.execute(
            "UPDATE LOAN SET returned_at = ? WHERE loan_id = ? AND returned_at IS NULL",
            (returned_at, loan_id),
        )
        self.conn.commit()
        return cur.rowcount

    def extend_due(self, loan_id: int, new_due_iso: str, new_duration_min: int) -> int:
        """貸出中ログの返却予定を延長する。更新できた行数（0=返却済み/該当なし）を返す。"""
        cur = self.conn.execute(
            "UPDATE LOAN SET due_at = ?, duration_min = ?"
            " WHERE loan_id = ? AND returned_at IS NULL",
            (new_due_iso, new_duration_min, loan_id),
        )
        self.conn.commit()
        return cur.rowcount

    def list_borrowed_between(self, start_iso: str, end_iso: str) -> list[Loan]:
        """borrowed_at が [start, end] に含まれる貸借ログ（CSV対象）。"""
        rows = self.conn.execute(
            "SELECT * FROM LOAN WHERE borrowed_at >= ? AND borrowed_at <= ?"
            " ORDER BY borrowed_at",
            (start_iso, end_iso),
        ).fetchall()
        return [_row_to_loan(r) for r in rows]
