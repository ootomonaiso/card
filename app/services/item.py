"""物品管理サービス（物品の追加・編集・無効化/有効化）。

ITEM テーブルを複数物品前提で扱う。貸出中の物品は無効化できない、
有効な物品が0件になる無効化は拒否する、といった業務ルールをここで日本語エラーにする。
"""
from __future__ import annotations

from app.log import audit
from app.repository.items import ItemRepository
from app.repository.loans import LoanRepository


class ItemError(Exception):
    """物品管理の業務エラー。"""


class ItemService:
    def __init__(self, items: ItemRepository, loans: LoanRepository) -> None:
        self.items = items
        self.loans = loans

    def list_with_status(self) -> list[dict]:
        """全物品を貸出中フラグ付きで返す（物品管理画面向け）。"""
        open_ids = {ln.item_id for ln in self.loans.list_open()}
        return [
            {
                "item_id": it.item_id,
                "name": it.name,
                "location": it.location or "",
                "is_active": it.is_active,
                "is_lent": it.item_id in open_ids,
            }
            for it in self.items.list_all()
        ]

    def add_item(self, name: str, location: str) -> int:
        name = (name or "").strip()
        location = (location or "").strip()
        if not name:
            raise ItemError("物品名を入力してください")
        item_id = self.items.insert(name, location or None)
        audit().info("物品追加 item_id=%s name=%s location=%s", item_id, name, location)
        return item_id

    def update_item(self, item_id: int, name: str, location: str) -> None:
        name = (name or "").strip()
        location = (location or "").strip()
        if not name:
            raise ItemError("物品名を入力してください")
        if self.items.get(item_id) is None:
            raise ItemError("物品が見つかりません")
        self.items.update(item_id, name, location or None)
        audit().info("物品編集 item_id=%s name=%s location=%s", item_id, name, location)

    def deactivate_item(self, item_id: int) -> None:
        item = self.items.get(item_id)
        if item is None:
            raise ItemError("物品が見つかりません")
        # 貸出中の物品を無効化すると「借りているのに台帳から消える」不整合になる。
        if self.loans.count_open(item_id) > 0:
            raise ItemError("貸出中の物品は無効化できません")
        # 有効な物品が0件になると誰も借りられなくなるため拒否する。
        if item.is_active and self.items.count_active() <= 1:
            raise ItemError("有効な物品が0件になるため無効化できません")
        self.items.set_active(item_id, False)
        audit().info("物品無効化 item_id=%s", item_id)

    def activate_item(self, item_id: int) -> None:
        if self.items.get(item_id) is None:
            raise ItemError("物品が見つかりません")
        self.items.set_active(item_id, True)
        audit().info("物品有効化 item_id=%s", item_id)
