"""MemberService の拡充（ロール変更/編集/カード再発行/最後の管理者保護）のテスト。"""
from __future__ import annotations

import unittest

from app.services.member import MemberError
from tests.helpers import make_ctx


class InitialAdminSetupTest(unittest.TestCase):
    """鶏卵問題対策：有効な管理者が1人もいないときだけ使える初期登録。"""

    def setUp(self):
        self.ctx = make_ctx()

    def test_has_active_admin_false_on_empty_db(self):
        self.assertFalse(self.ctx.members.has_active_admin())

    def test_register_initial_admin_succeeds_when_no_admin(self):
        m = self.ctx.members.register_initial_admin("CARD1", "900001", "初代 管理者")
        self.assertTrue(m.is_admin)
        self.assertTrue(self.ctx.members.has_active_admin())

    def test_register_initial_admin_rejected_once_admin_exists(self):
        self.ctx.members.register_initial_admin("CARD1", "900001", "初代 管理者")
        with self.assertRaises(MemberError):
            self.ctx.members.register_initial_admin("CARD2", "900002", "二代目 管理者")

    def test_register_initial_admin_rejected_when_admin_registered_normally(self):
        # register() 経由で管理者が既にいる場合も、初期登録は拒否する（二重防御）
        self.ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        with self.assertRaises(MemberError):
            self.ctx.members.register_initial_admin("CARD2", "900002", "二代目 管理者")

    def test_register_initial_admin_still_allowed_when_only_inactive_admin_exists(self):
        # 管理者が居ても無効化されていれば「有効な管理者」は0人なので初期登録を許す。
        # （最後の管理者保護により通常の deactivate() ではこの状態にできないため、
        #  手順の異常やDB直接操作で無効化済みになったケースを想定して直接更新する）
        m = self.ctx.members.register("ADMIN1", "900001", "休止 管理者", "admin")
        self.ctx.member_repo.set_active(m.member_id, False)
        got = self.ctx.members.register_initial_admin("CARD2", "900002", "新任 管理者")
        self.assertTrue(got.is_admin)


class RoleChangeTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.user = self.ctx.members.register("U1", "100001", "山田 太郎", "user")
        self.admin1 = self.ctx.members.register("A1", "900001", "管理 者一", "admin")
        self.admin2 = self.ctx.members.register("A2", "900002", "管理 者二", "admin")

    def test_promote_user_to_admin(self):
        got = self.ctx.members.set_role(self.user.member_id, "admin")
        self.assertTrue(got.is_admin)

    def test_demote_admin_to_user_when_another_admin_exists(self):
        got = self.ctx.members.set_role(self.admin1.member_id, "user")
        self.assertFalse(got.is_admin)

    def test_demote_last_admin_rejected(self):
        self.ctx.members.set_role(self.admin1.member_id, "user")  # 残り管理者は admin2 のみ
        with self.assertRaises(MemberError):
            self.ctx.members.set_role(self.admin2.member_id, "user")
        # 変更されていないこと
        self.assertEqual(self.ctx.member_repo.get(self.admin2.member_id).role, "admin")

    def test_invalid_role_rejected(self):
        with self.assertRaises(MemberError):
            self.ctx.members.set_role(self.user.member_id, "superadmin")


class ProfileEditTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.user = self.ctx.members.register("U1", "100001", "山田 太郎", "user")

    def test_update_profile(self):
        got = self.ctx.members.update_profile(self.user.member_id, "山田 次郎", "100099")
        self.assertEqual(got.name, "山田 次郎")
        self.assertEqual(got.employee_no, "100099")

    def test_update_profile_empty_name_rejected(self):
        with self.assertRaises(MemberError):
            self.ctx.members.update_profile(self.user.member_id, "", "100099")

    def test_update_profile_empty_employee_no_rejected(self):
        with self.assertRaises(MemberError):
            self.ctx.members.update_profile(self.user.member_id, "山田 太郎", "")

    def test_update_profile_missing_member_rejected(self):
        with self.assertRaises(MemberError):
            self.ctx.members.update_profile(99999, "誰か", "1")


class CardReissueTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.taro = self.ctx.members.register("OLDCARD", "100001", "山田 太郎", "user")
        self.hanako = self.ctx.members.register("OTHERCARD", "100002", "鈴木 花子", "user")

    def test_reissue_updates_idm(self):
        got = self.ctx.members.reissue_card(self.taro.member_id, "NEWCARD")
        self.assertEqual(got.card_idm, "NEWCARD")
        # 旧カードはもう使えない／新カードで認証できる
        self.assertIsNone(self.ctx.auth.authenticate("OLDCARD"))
        self.assertIsNotNone(self.ctx.auth.authenticate("NEWCARD"))

    def test_reissue_rejects_idm_already_used_by_other_member(self):
        with self.assertRaises(MemberError):
            self.ctx.members.reissue_card(self.taro.member_id, "OTHERCARD")
        # 変更されていないこと
        self.assertEqual(self.ctx.member_repo.get(self.taro.member_id).card_idm, "OLDCARD")

    def test_reissue_empty_idm_rejected(self):
        with self.assertRaises(MemberError):
            self.ctx.members.reissue_card(self.taro.member_id, "")


class LastAdminProtectionTest(unittest.TestCase):
    """最後の管理者の無効化・削除を拒否する（鶏卵問題の再発防止）。"""

    def setUp(self):
        self.ctx = make_ctx()
        self.admin = self.ctx.members.register("A1", "900001", "唯一 管理者", "admin")

    def test_deactivate_last_admin_rejected(self):
        with self.assertRaises(MemberError):
            self.ctx.members.deactivate(self.admin.member_id)
        self.assertTrue(self.ctx.member_repo.get(self.admin.member_id).is_active)

    def test_delete_last_admin_rejected(self):
        with self.assertRaises(MemberError):
            self.ctx.members.delete(self.admin.member_id)
        self.assertIsNotNone(self.ctx.member_repo.get(self.admin.member_id))

    def test_deactivate_non_last_admin_allowed(self):
        admin2 = self.ctx.members.register("A2", "900002", "もう一人 管理者", "admin")
        self.ctx.members.deactivate(self.admin.member_id)
        self.assertFalse(self.ctx.member_repo.get(self.admin.member_id).is_active)
        self.assertTrue(self.ctx.member_repo.get(admin2.member_id).is_active)

    def test_deactivate_normal_user_unaffected(self):
        user = self.ctx.members.register("U1", "100001", "一般 利用者", "user")
        self.ctx.members.deactivate(user.member_id)  # 最後の管理者保護には引っかからない
        self.assertFalse(self.ctx.member_repo.get(user.member_id).is_active)


if __name__ == "__main__":
    unittest.main(verbosity=2)
