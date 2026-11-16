"""WebUI のサーバ側状態機械（画面遷移）のテスト（07 画面設計書）。

Terminal は HTTP を介さずに直接駆動できる。on_change で最新stateを捕捉する。
"""
from __future__ import annotations

import unittest
from datetime import datetime

from app.services.clock import FixedClock
from app.web.terminal import Terminal
from tests.helpers import make_ctx


class TerminalFlowTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx(
            FixedClock(datetime(2026, 11, 8, 9, 0, 0)),
            result_screen_seconds=999,   # 自動復帰タイマは発火させない
            idle_timeout_seconds=999,
        )
        self.ctx.members.register("USER1", "100234", "山田 太郎", "user")
        self.ctx.members.register("USER2", "100567", "鈴木 花子", "user")
        self.ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        self.t = Terminal(self.ctx)
        self.last = {}
        self.t.on_change = lambda s: self.last.update(s)
        self.t.go_standby()

    def tearDown(self):
        self.t.shutdown()

    @property
    def screen(self):
        return self.t.screen

    def test_startup_is_standby(self):
        self.assertEqual(self.screen, "standby")
        items = self.last["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["is_lent"])

    def test_unregistered_goes_error(self):
        self.t.on_card("NOPE")
        self.assertEqual(self.screen, "error")
        self.assertIn("登録されていません", self.last["data"]["reason"])

    def test_borrow_flow(self):
        self.t.on_card("USER1")
        self.assertEqual(self.screen, "borrow_time")
        self.t.choose_duration(60)
        self.assertEqual(self.screen, "unlock")
        self.assertEqual(self.last["data"]["mode"], "borrow")
        self.assertEqual(self.ctx.lock.unlock_count, 1)
        self.assertTrue(self.ctx.loans.status_list()[0].is_lent)

    def test_other_user_blocked_while_lent(self):
        self.t.on_card("USER1"); self.t.choose_duration(60)
        self.t.go_standby()
        self.t.on_card("USER2")
        self.assertEqual(self.screen, "error")

    def test_return_flow(self):
        self.t.on_card("USER1"); self.t.choose_duration(60)
        self.t.go_standby()
        self.t.on_card("USER1")
        self.assertEqual(self.screen, "return_confirm")
        self.t.confirm_return()
        self.assertEqual(self.screen, "unlock")
        self.assertEqual(self.last["data"]["mode"], "return")
        self.assertFalse(self.ctx.loans.status_list()[0].is_lent)

    def test_admin_menu_and_member_capture(self):
        self.t.on_card("ADMIN1")
        self.assertEqual(self.screen, "admin_menu")
        self.t.open_member_admin()
        self.assertEqual(self.screen, "member_admin")
        # メンバー管理画面でのカードタッチは登録用にIDmを取り込む
        self.t.on_card("NEWCARD")
        self.assertEqual(self.screen, "member_admin")
        self.assertEqual(self.last["data"]["captured_idm"], "NEWCARD")
        r = self.t.register_member("新人 一郎", "100999", "user")
        self.assertTrue(r["ok"])
        self.assertIsNotNone(self.ctx.auth.authenticate("NEWCARD"))

    def test_admin_self_borrow(self):
        self.t.on_card("ADMIN1")
        self.t.admin_self_borrow()
        self.assertEqual(self.screen, "borrow_time")

    def test_admin_can_return_own_loan(self):
        # 管理者が自分で借りた物品を、管理メニューの返却導線から返せる
        self.t.on_card("ADMIN1")
        self.t.admin_self_borrow()
        self.t.choose_duration(60)
        self.assertTrue(self.ctx.loans.status_list()[0].is_lent)
        # 再タッチ → 管理メニュー（can_return つき）
        self.t.go_standby()
        self.t.on_card("ADMIN1")
        self.assertEqual(self.screen, "admin_menu")
        self.assertTrue(self.last["data"].get("can_return"))
        self.t.admin_return()
        self.assertEqual(self.screen, "return_confirm")
        self.t.confirm_return()
        self.assertEqual(self.screen, "unlock")
        self.assertFalse(self.ctx.loans.status_list()[0].is_lent)

    def test_admin_menu_has_no_return_without_loan(self):
        self.t.on_card("ADMIN1")
        self.assertEqual(self.screen, "admin_menu")
        self.assertFalse(self.last["data"].get("can_return"))

    def test_member_admin_actions_require_admin(self):
        # 管理者ログインしていない（standby）状態では管理操作を拒否する
        before_count = len(self.ctx.members.list_all())
        r = self.t.register_member("不正 太郎", "999", "user")
        self.assertFalse(r["ok"])
        self.assertEqual(len(self.ctx.members.list_all()), before_count)  # 登録されていない

        r2 = self.t.export_report("2026/11/01", "2026/11/30", "x.csv")
        self.assertFalse(r2["ok"])

        uid = self.ctx.members.list_all()[0].member_id
        before = self.ctx.member_repo.get(uid).is_active
        self.t.set_member_active(uid, not before)
        self.assertEqual(self.ctx.member_repo.get(uid).is_active, before)  # 状態は変わらない

    def test_standby_shows_borrower(self):
        self.t.on_card("USER1"); self.t.choose_duration(60)
        self.t.go_standby()
        item = self.last["data"]["items"][0]
        self.assertTrue(item["is_lent"])
        self.assertEqual(item["borrower_name"], "山田 太郎")


class MultiItemTerminalTest(unittest.TestCase):
    """複数物品の貸出/返却導線（物品選択・返却選択）と物品管理画面。"""

    def setUp(self):
        self.ctx = make_ctx(
            FixedClock(datetime(2026, 11, 8, 9, 0, 0)),
            result_screen_seconds=999, idle_timeout_seconds=999,
        )
        self.item1 = self.ctx.item_repo.default_item().item_id
        self.item2 = self.ctx.item_svc.add_item("予備カメラ", "保管庫B")
        self.ctx.members.register("USER1", "100234", "山田 太郎", "user")
        self.ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        self.t = Terminal(self.ctx)
        self.last = {}
        self.t.on_change = lambda s: self.last.update(s)
        self.t.go_standby()

    def tearDown(self):
        self.t.shutdown()

    @property
    def screen(self):
        return self.t.screen

    def test_standby_lists_multiple_items(self):
        items = self.last["data"]["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual({it["name"] for it in items}, {"セキュアカメラ", "予備カメラ"})

    def test_borrow_shows_item_selection_when_multiple_free(self):
        self.t.on_card("USER1")
        self.assertEqual(self.screen, "borrow_item")
        self.assertEqual(len(self.last["data"]["items"]), 2)
        self.t.choose_item(self.item2)
        self.assertEqual(self.screen, "borrow_time")
        self.assertEqual(self.last["data"]["item_name"], "予備カメラ")
        self.t.choose_duration(60)
        self.assertEqual(self.screen, "unlock")
        # 選んだ物品だけが貸出中になる
        by_id = {s.item_id: s for s in self.ctx.loans.status_list()}
        self.assertTrue(by_id[self.item2].is_lent)
        self.assertFalse(by_id[self.item1].is_lent)

    def test_borrow_skips_selection_when_single_free(self):
        # 片方を貸出中にすると空きは1件 → 物品選択を飛ばして時間選択へ直行
        self.ctx.loans.borrow(self.ctx.auth.authenticate("USER1"), self.item1, 60)
        self.t.go_standby()
        self.t.on_card("ADMIN1")  # 管理者で borrow → admin flow
        self.t.admin_self_borrow()
        self.assertEqual(self.screen, "borrow_time")  # 空き1件なので直行
        self.assertEqual(self.last["data"]["item_name"], "予備カメラ")

    def test_return_select_when_multiple_open_loans(self):
        user = self.ctx.auth.authenticate("USER1")
        self.ctx.loans.borrow(user, self.item1, 60)
        self.ctx.loans.borrow(user, self.item2, 60)
        self.t.go_standby()
        self.t.on_card("USER1")
        self.assertEqual(self.screen, "return_select")
        loans = self.last["data"]["loans"]
        self.assertEqual(len(loans), 2)
        self.t.choose_return(loans[0]["loan_id"])
        self.assertEqual(self.screen, "return_confirm")
        self.t.confirm_return()
        self.assertEqual(self.screen, "unlock")
        # 1件返したので残り1件
        self.assertEqual(len(self.ctx.loans.find_returnable_loans(user)), 1)

    def test_return_confirm_borrow_button_switches_to_borrow(self):
        user = self.ctx.auth.authenticate("USER1")
        self.ctx.loans.borrow(user, self.item1, 60)  # 1件だけ借りている
        self.t.go_standby()
        self.t.on_card("USER1")
        self.assertEqual(self.screen, "return_confirm")  # 1件なので確認直行
        # 「借りる」で貸出導線へ（空きは item2 の1件 → borrow_time へ直行）
        self.t.goto_borrow()
        self.assertEqual(self.screen, "borrow_time")
        self.assertEqual(self.last["data"]["item_name"], "予備カメラ")

    def test_goto_borrow_ignored_outside_return_screens(self):
        # 「借りる」は返却確認/返却選択でのみ有効。他画面からの誤/多重リクエストで
        # 進行中の画面を奪われないこと。
        user = self.ctx.auth.authenticate("USER1")
        self.ctx.loans.borrow(user, self.item1, 60)
        self.t.go_standby()
        self.t.on_card("USER1")
        self.t.goto_borrow()          # return_confirm → 正当に borrow_time へ
        self.assertEqual(self.screen, "borrow_time")
        self.t.choose_duration(60)
        self.assertEqual(self.screen, "unlock")  # 解錠中（auto_returnタイマ付き）
        self.t.goto_borrow()          # unlock からの goto_borrow は無視される
        self.assertEqual(self.screen, "unlock")

    def test_item_admin_add_edit_deactivate(self):
        self.t.on_card("ADMIN1")
        self.t.open_item_admin()
        self.assertEqual(self.screen, "item_admin")
        # 追加
        r = self.t.add_item("三脚", "保管庫C")
        self.assertTrue(r["ok"])
        self.assertIn("三脚", [it["name"] for it in self.last["data"]["items"]])
        # 編集
        r2 = self.t.update_item(self.item2, "予備カメラ2", "保管庫D")
        self.assertTrue(r2["ok"])
        self.assertEqual(self.ctx.item_repo.get(self.item2).name, "予備カメラ2")
        # 無効化（他に有効な物品があるのでOK）
        r3 = self.t.set_item_active(self.item2, False)
        self.assertTrue(r3["ok"])
        self.assertFalse(self.ctx.item_repo.get(self.item2).is_active)

    def test_item_admin_cannot_deactivate_lent_item(self):
        user = self.ctx.auth.authenticate("USER1")
        self.ctx.loans.borrow(user, self.item1, 60)
        self.t.on_card("ADMIN1")
        self.t.open_item_admin()
        r = self.t.set_item_active(self.item1, False)
        self.assertFalse(r["ok"])
        self.assertIn("貸出中", r["message"])
        self.assertTrue(self.ctx.item_repo.get(self.item1).is_active)

    def test_item_admin_cannot_deactivate_last_active_item(self):
        self.t.on_card("ADMIN1")
        self.t.open_item_admin()
        # item2 を無効化（残り item1 のみ有効）
        self.t.set_item_active(self.item2, False)
        r = self.t.set_item_active(self.item1, False)
        self.assertFalse(r["ok"])
        self.assertIn("0件", r["message"])
        self.assertTrue(self.ctx.item_repo.get(self.item1).is_active)

    def test_item_admin_requires_admin(self):
        # 管理者セッションでなければ物品操作は拒否
        r = self.t.add_item("不正物品", "x")
        self.assertFalse(r["ok"])
        self.assertEqual(len(self.ctx.item_repo.list_all()), 2)  # 追加されていない


class MemberAdminExtendedTest(unittest.TestCase):
    """メンバー管理（A02）拡充：ロール変更・編集・カード再発行・最後の管理者保護。"""

    def setUp(self):
        self.ctx = make_ctx(
            FixedClock(datetime(2026, 11, 8, 9, 0, 0)),
            result_screen_seconds=999, idle_timeout_seconds=999,
        )
        self.user = self.ctx.members.register("USER1", "100234", "山田 太郎", "user")
        self.admin1 = self.ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        self.admin2 = self.ctx.members.register("ADMIN2", "900002", "管理 者二", "admin")
        self.t = Terminal(self.ctx)
        self.last = {}
        self.t.on_change = lambda s: self.last.update(s)
        self.t.go_standby()
        self.t.on_card("ADMIN1")
        self.t.open_member_admin()

    def tearDown(self):
        self.t.shutdown()

    def test_set_member_role_promotes_user(self):
        r = self.t.set_member_role(self.user.member_id, "admin")
        self.assertTrue(r["ok"])
        self.assertEqual(self.ctx.member_repo.get(self.user.member_id).role, "admin")

    def test_set_member_role_rejects_self_demotion(self):
        # ログイン中の管理者（admin1）は自分自身をuserへ降格できない
        # （_adminは認証時のスナップショットで、DBと食い違ったまま権限が残るのを防ぐ）。
        r = self.t.set_member_role(self.admin1.member_id, "user")
        self.assertFalse(r["ok"])
        self.assertIn("自分自身", r["message"])
        self.assertEqual(self.ctx.member_repo.get(self.admin1.member_id).role, "admin")
        # 自分以外の管理者（admin2）は降格できる
        r2 = self.t.set_member_role(self.admin2.member_id, "user")
        self.assertTrue(r2["ok"])
        self.assertEqual(self.ctx.member_repo.get(self.admin2.member_id).role, "user")

    def test_set_member_role_requires_admin_session(self):
        self.t.go_standby()
        r = self.t.set_member_role(self.user.member_id, "admin")
        self.assertFalse(r["ok"])
        self.assertEqual(self.ctx.member_repo.get(self.user.member_id).role, "user")

    def test_update_member_edits_profile(self):
        r = self.t.update_member(self.user.member_id, "山田 次郎", "100999")
        self.assertTrue(r["ok"])
        updated = self.ctx.member_repo.get(self.user.member_id)
        self.assertEqual(updated.name, "山田 次郎")
        self.assertEqual(updated.employee_no, "100999")

    def test_update_member_rejects_empty_name(self):
        r = self.t.update_member(self.user.member_id, "", "100999")
        self.assertFalse(r["ok"])

    def test_set_member_active_rejects_self_deactivation(self):
        # ログイン中の管理者（admin1）は自分自身を無効化できない。
        r = self.t.set_member_active(self.admin1.member_id, False)
        self.assertFalse(r["ok"])
        self.assertIn("自分自身", r["message"])
        self.assertTrue(self.ctx.member_repo.get(self.admin1.member_id).is_active)
        # 自分以外の管理者（admin2）は無効化できる。
        r2 = self.t.set_member_active(self.admin2.member_id, False)
        self.assertTrue(r2["ok"])
        self.assertFalse(self.ctx.member_repo.get(self.admin2.member_id).is_active)

    def test_card_reissue_flow(self):
        self.t.start_card_reissue(self.user.member_id)
        self.assertEqual(self.last["data"]["reissue_target_id"], self.user.member_id)
        self.t.on_card("NEWCARD")
        self.assertEqual(self.ctx.member_repo.get(self.user.member_id).card_idm, "NEWCARD")
        self.assertIsNone(self.last["data"]["reissue_target_id"])
        self.assertIn("再発行", self.last["data"]["reissue_message"])
        # 旧カードは無効、新カードで認証できる
        self.assertIsNone(self.ctx.auth.authenticate("USER1"))
        self.assertIsNotNone(self.ctx.auth.authenticate("NEWCARD"))

    def test_card_reissue_rejects_duplicate_idm(self):
        self.t.start_card_reissue(self.user.member_id)
        self.t.on_card("ADMIN2")  # 既に admin2 が使っているIDm
        self.assertIn("既に", self.last["data"]["reissue_message"])
        # 変更されていないこと
        self.assertEqual(self.ctx.member_repo.get(self.user.member_id).card_idm, "USER1")

    def test_card_reissue_does_not_interfere_with_new_member_capture(self):
        # カード再発行待ちでないときの通常タッチは、新規登録用のIDm取込のまま
        self.t.on_card("BRANDNEW")
        self.assertEqual(self.last["data"]["captured_idm"], "BRANDNEW")

    def test_cancel_card_reissue(self):
        self.t.start_card_reissue(self.user.member_id)
        self.t.cancel_card_reissue()
        self.assertIsNone(self.last["data"]["reissue_target_id"])
        # キャンセル後のタッチは通常の新規登録取込に戻る
        self.t.on_card("BRANDNEW")
        self.assertEqual(self.last["data"]["captured_idm"], "BRANDNEW")
        self.assertEqual(self.ctx.member_repo.get(self.user.member_id).card_idm, "USER1")


class InitialAdminSetupScreenTest(unittest.TestCase):
    """鶏卵問題対策：有効な管理者が1人もいないときの初期管理者登録導線（setup画面）。"""

    def _term(self, **overrides) -> Terminal:
        ctx = make_ctx(
            FixedClock(datetime(2026, 11, 8, 9, 0, 0)),
            result_screen_seconds=999, idle_timeout_seconds=999,
            **overrides,
        )
        t = Terminal(ctx)
        self.addCleanup(t.shutdown)
        self.last = {}
        t.on_change = lambda s: self.last.update(s)
        t.go_standby()
        return t

    def test_setup_triggered_when_no_admin_exists(self):
        t = self._term()
        t.on_card("NEWCARD")
        self.assertEqual(t.screen, "setup")
        self.assertEqual(self.last["data"]["idm"], "NEWCARD")

    def test_setup_not_triggered_when_active_admin_exists(self):
        t = self._term()
        t.ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        t.on_card("NEWCARD")
        self.assertEqual(t.screen, "error")

    def test_setup_not_triggered_for_registered_user_card(self):
        # 未登録カードでなければ（通常の利用者カード）setupには遷移しない
        t = self._term()
        t.ctx.members.register("USER1", "100234", "山田 太郎", "user")
        t.on_card("USER1")
        self.assertEqual(t.screen, "borrow_time")

    def test_setup_recapture_idm_on_retouch(self):
        t = self._term()
        t.on_card("NEWCARD")
        self.assertEqual(t.screen, "setup")
        t.on_card("OTHERCARD")  # 誤タッチ訂正：再タッチで取り込み直す
        self.assertEqual(t.screen, "setup")
        self.assertEqual(self.last["data"]["idm"], "OTHERCARD")

    def test_register_initial_admin_success_goes_to_admin_menu(self):
        t = self._term()
        t.on_card("NEWCARD")
        r = t.register_initial_admin("初代 管理者", "900001")
        self.assertTrue(r["ok"])
        self.assertEqual(t.screen, "admin_menu")
        self.assertTrue(t.ctx.members.has_active_admin())
        got = t.ctx.auth.authenticate("NEWCARD")
        self.assertIsNotNone(got)
        self.assertTrue(got.is_admin)

    def test_register_initial_admin_rejects_outside_setup_screen(self):
        t = self._term()
        t.ctx.members.register("ADMIN1", "900001", "管理 者一", "admin")
        r = t.register_initial_admin("なりすまし", "000000")
        self.assertFalse(r["ok"])

    def test_register_initial_admin_requires_idm(self):
        t = self._term()
        t.on_card("NEWCARD")
        t.cancel()  # 標準画面へ戻る→ _capture_idm はクリアされる
        # 画面を強制的に setup へ戻しても IDm 未取込のため登録は失敗する
        t.screen = "setup"
        r = t.register_initial_admin("氏名", "1")
        self.assertFalse(r["ok"])


class RequireTapTest(unittest.TestCase):
    """require_tap_to_start の切替で待受画面が変わる。"""

    def _term(self, require_tap: bool) -> Terminal:
        ctx = make_ctx(FixedClock(datetime(2026, 11, 8, 9, 0, 0)),
                       require_tap_to_start=require_tap,
                       result_screen_seconds=999, idle_timeout_seconds=999)
        ctx.members.register("USER1", "100234", "山田 太郎", "user")
        t = Terminal(ctx)
        self.addCleanup(t.shutdown)
        t.go_standby()
        return t

    def test_direct_standby_when_disabled(self):
        t = self._term(False)
        self.assertEqual(t.screen, "standby")

    def test_attract_shown_when_enabled(self):
        t = self._term(True)
        self.assertEqual(t.screen, "attract")

    def test_card_ignored_on_attract(self):
        # attract 画面ではカードは無視。画面タッチが先
        t = self._term(True)
        t.on_card("USER1")
        self.assertEqual(t.screen, "attract")

    def test_start_then_card_works(self):
        t = self._term(True)
        t.start()
        self.assertEqual(t.screen, "standby")
        t.on_card("USER1")
        self.assertEqual(t.screen, "borrow_time")

    def test_returns_to_attract_as_home(self):
        # 使い終わって go_standby すると attract（ホーム）に戻る
        t = self._term(True)
        t.start(); t.on_card("USER1"); t.choose_duration(60)
        t.go_standby()
        self.assertEqual(t.screen, "attract")


if __name__ == "__main__":
    unittest.main(verbosity=2)
