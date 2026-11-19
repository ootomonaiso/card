"""ITEM テーブルのアクセス。複数物品に対応（将来のロッカー増設を見込む）。"""
from __future__ import annotations

import sqlite3

from app.domain.models import Item


def _row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        item_id=row["item_id"],
        name=row["name"],
        location=row["location"],
        is_active=bool(row["is_active"]),
        category=row["category"],
    )


class ItemRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, item_id: int) -> Item | None:
        row = self.conn.execute(
            "SELECT * FROM ITEM WHERE item_id = ?", (item_id,)
        ).fetchone()
        return _row_to_item(row) if row else None

    def list_active(self) -> list[Item]:
        """有効な物品を item_id 昇順で返す（貸出対象の母集団）。"""
        rows = self.conn.execute(
            "SELECT * FROM ITEM WHERE is_active = 1 ORDER BY item_id"
        ).fetchall()
        return [_row_to_item(r) for r in rows]

    def list_all(self) -> list[Item]:
        """無効な物品も含めて全件（物品管理画面向け）。"""
        rows = self.conn.execute(
            "SELECT * FROM ITEM ORDER BY item_id"
        ).fetchall()
        return [_row_to_item(r) for r in rows]

    def count_active(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM ITEM WHERE is_active = 1"
        ).fetchone()
        return int(row["c"])

    def default_item(self) -> Item:
        """最初の有効な物品を返す（CLI/後方互換の既定物品）。

        複数物品運用では status_list()/available_items()（LoanService）を使う。
        単一物品の設置や保守スクリプトのための便宜メソッドとして残す。
        """
        row = self.conn.execute(
            "SELECT * FROM ITEM WHERE is_active = 1 ORDER BY item_id LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("有効な物品が登録されていません")
        return _row_to_item(row)

    def insert(self, name: str, location: str | None, category: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO ITEM(name, location, category, is_active) VALUES(?, ?, ?, 1)",
            (name, location, category),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update(
        self, item_id: int, name: str, location: str | None, category: str | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE ITEM SET name = ?, location = ?, category = ? WHERE item_id = ?",
            (name, location, category, item_id),
        )
        self.conn.commit()

    def set_active(self, item_id: int, active: bool) -> None:
        self.conn.execute(
            "UPDATE ITEM SET is_active = ? WHERE item_id = ?",
            (1 if active else 0, item_id),
        )
        self.conn.commit()
