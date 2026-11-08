"""認証（FR-01 / FR-08）の単体テスト。"""
from __future__ import annotations

import unittest

from tests.helpers import make_ctx


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()

    def test_unregistered_card_rejected(self):
        # FR-01：未登録カードは認証失敗
        self.assertIsNone(self.ctx.auth.authenticate("DEADBEEF"))

    def test_registered_card_ok(self):
        self.ctx.members.register("AA11", "100234", "山田 太郎", "user")
        got = self.ctx.auth.authenticate("AA11")
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "山田 太郎")
        self.assertFalse(got.is_admin)

    def test_admin_role(self):
        # FR-08：admin ロールを判定できる
        self.ctx.members.register("ZZ99", "900001", "管理 者一", "admin")
        got = self.ctx.auth.authenticate("ZZ99")
        self.assertTrue(got.is_admin)

    def test_deactivated_card_rejected(self):
        m = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")
        self.ctx.members.deactivate(m.member_id)
        self.assertIsNone(self.ctx.auth.authenticate("AA11"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
