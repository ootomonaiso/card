"""物品管理サービス（ItemService）の単体テスト。複数物品の追加・編集・無効化ガード。"""
from __future__ import annotations

import unittest

from app.services.item import ItemError
from tests.helpers import make_ctx


class ItemServiceTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.svc = self.ctx.item_svc
        self.item1 = self.ctx.item_repo.default_item().item_id  # 初期シード物品

    def test_add_item(self):
        item_id = self.svc.add_item("予備カメラ", "保管庫B")
        it = self.ctx.item_repo.get(item_id)
        self.assertEqual(it.name, "予備カメラ")
        self.assertEqual(it.location, "保管庫B")
        self.assertTrue(it.is_active)

    def test_add_item_empty_name_rejected(self):
        with self.assertRaises(ItemError):
            self.svc.add_item("  ", "保管庫B")

    def test_add_item_blank_location_allowed(self):
        item_id = self.svc.add_item("三脚", "")
        self.assertIsNone(self.ctx.item_repo.get(item_id).location)

    def test_update_item(self):
        self.svc.update_item(self.item1, "セキュアカメラ改", "保管庫Z")
        it = self.ctx.item_repo.get(self.item1)
        self.assertEqual(it.name, "セキュアカメラ改")
        self.assertEqual(it.location, "保管庫Z")

    def test_update_item_empty_name_rejected(self):
        with self.assertRaises(ItemError):
            self.svc.update_item(self.item1, "", "保管庫Z")

    def test_update_missing_item_rejected(self):
        with self.assertRaises(ItemError):
            self.svc.update_item(9999, "存在しない", "x")

    def test_deactivate_rejected_when_lent(self):
        taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")
        self.svc.add_item("予備カメラ", "保管庫B")  # 有効物品を増やし「最後の1件」ガードを外す
        self.ctx.loans.borrow(taro, self.item1, 60)
        with self.assertRaises(ItemError) as cm:
            self.svc.deactivate_item(self.item1)
        self.assertIn("貸出中", str(cm.exception))
        self.assertTrue(self.ctx.item_repo.get(self.item1).is_active)

    def test_deactivate_rejected_when_last_active(self):
        with self.assertRaises(ItemError) as cm:
            self.svc.deactivate_item(self.item1)  # 有効物品はこれ1件のみ
        self.assertIn("0件", str(cm.exception))
        self.assertTrue(self.ctx.item_repo.get(self.item1).is_active)

    def test_deactivate_and_activate_roundtrip(self):
        item2 = self.svc.add_item("予備カメラ", "保管庫B")
        self.svc.deactivate_item(item2)
        self.assertFalse(self.ctx.item_repo.get(item2).is_active)
        self.assertEqual(len(self.ctx.loans.available_items()), 1)  # item1 のみ
        self.svc.activate_item(item2)
        self.assertTrue(self.ctx.item_repo.get(item2).is_active)
        self.assertEqual(len(self.ctx.loans.available_items()), 2)

    def test_list_with_status_marks_lent(self):
        taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")
        item2 = self.svc.add_item("予備カメラ", "保管庫B")
        self.ctx.loans.borrow(taro, self.item1, 60)
        by_id = {row["item_id"]: row for row in self.svc.list_with_status()}
        self.assertTrue(by_id[self.item1]["is_lent"])
        self.assertFalse(by_id[item2]["is_lent"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
