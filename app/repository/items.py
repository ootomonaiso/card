"""ITEM テーブルのアクセス。フェーズ1は1件（セキュアカメラ）。"""
from __future__ import annotations

import sqlite3

from app.domain.models import Item


def _row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        item_id=row["item_id"],
        name=row["name"],
        location=row["location"],
        is_active=bool(row["is_active"]),
    )


class ItemRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, item_id: int) -> Item | None:
        row = self.conn.execute(
            "SELECT * FROM ITEM WHERE item_id = ?", (item_id,)
        ).fetchone()
        return _row_to_item(row) if row else None

    def default_item(self) -> Item:
        """フェーズ1は単一物品。最初の有効な物品を返す。"""
        row = self.conn.execute(
            "SELECT * FROM ITEM WHERE is_active = 1 ORDER BY item_id LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("有効な物品が登録されていません")
        return _row_to_item(row)
