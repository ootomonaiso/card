"""キオスク端末の状態機械（サーバ側コントローラ）。

ブラウザは「サーバが指示した画面を描画するだけ」の薄い作りにし、
画面遷移ロジック（認証→貸出/返却/管理/エラー）はここに一元化する。
状態が変わるたび on_change(state) を呼び、サーバが SSE でブラウザへ push する。
画面遷移は 07_画面設計書（S01〜S07 / A01〜A03）に対応する。
"""
from __future__ import annotations

import threading
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Callable

from app.config import ConfigError
from app.context import AppContext
from app.log import audit, get_logger
from app.services.clock import from_iso, to_iso
from app.services.item import ItemError
from app.services.loan import LoanError
from app.services.member import MemberError
from app.services.report import CSV_HEADER, ExportPathError, validate_export_path
from app.services.timesync import ntp_status

DURATION_LABELS = {15: "15分", 30: "30分", 60: "1時間", 120: "2時間", 240: "4時間", 480: "8時間"}

# LoanService が解錠ハード故障を re-wrap したときのメッセージの一部。
# エラー表示の文脈分け（③ハード故障の検知と表示）に使う軽量な目印であり、
# 正式なエラーコードではない（今後文脈が増えたら enum 化を検討）。
_HARDWARE_ERROR_HINT = "解錠に失敗"

_log = get_logger("terminal")

# 設定画面（FR-19）から編集できるフィールド。起動時に一度しか読まれない項目
# （デバイス選択・GPIO・テーマ等）は含めない＝再起動不要で安全に反映できるものだけ。
_EDITABLE_SETTINGS = (
    "unlock_seconds", "idle_timeout_seconds", "result_screen_seconds",
    "standby_refresh_seconds", "return_confirm_hold_seconds", "due_soon_minutes",
    "show_borrower_name", "allow_return_by_others", "require_tap_to_start",
    "teams_notify_overdue", "teams_notify_errors", "teams_notify_routine",
)


def _coerce_like(current, value):
    """既定値 current と同じ型へ value を変換する（JSON 由来の揺れを吸収）。

    bool は "true"/"1"/"on" 等の文字列も受ける（チェックボックス送信対策）。
    """
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "on", "yes")
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


class Terminal:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.cfg = ctx.cfg
        # DBアクセスを直列化する共有ロック（状態遷移もこのロックで保護）
        self._lock = ctx.db_lock
        self.on_change: Callable[[dict], None] = lambda state: None

        self.screen = "standby"
        self.payload: dict = {}
        self._admin = None          # 管理者（A01〜A03の戻り先）
        self._borrower = None       # 貸出操作中のメンバー
        self._borrow_item = None    # 貸出操作中に選択した物品（複数物品対応）
        self._borrow_duration: int | None = None  # borrow_confirm に進む前に選んだ分数
        self._borrow_available_count = 0  # エラー表示の文脈分け用（単品/複数物品）
        self._return_loan = None    # 返却対象ログ
        self._return_count = 0      # エラー表示の文脈分け用（単品/複数物品）
        self._overdue_notified: set[int] = set()  # Teams通知済みの loan_id（重複通知防止）
        self._capture_idm: str | None = None  # A02 登録用/setup用に取り込んだIDm
        self._reissue_target: int | None = None  # カード再発行待ちのメンバーID（A02）
        self._reissue_message: str = ""          # カード再発行の結果メッセージ（A02）

        self._force_return = False  # 管理者強制返却の最中か（借りる/延長ボタンを出さない）

        self._idle_timer: threading.Timer | None = None
        self._return_timer: threading.Timer | None = None
        self._refresh_timer: threading.Timer | None = None
        self._lock_watch_timer: threading.Timer | None = None  # 閉め忘れ検知（FR-18）
        self._closed = False
        self._start_refresh_loop()

    # ---------------------------------------------------------- 日時整形
    def _fmt(self, iso: str | None) -> str:
        return from_iso(iso).strftime(self.cfg.csv_datetime_format) if iso else ""

    # ---------------------------------------------------------- エラー文脈
    @staticmethod
    def _item_count_context(count: int) -> str:
        """単品/複数物品のどちらで発生したエラーかを示す軽量な文脈ヒント。"""
        return "multi_item" if count > 1 else "single_item"

    def _loan_error_context(self, e: Exception, count: int) -> str:
        if _HARDWARE_ERROR_HINT in str(e):
            return "hardware"
        return self._item_count_context(count)

    # ---------------------------------------------------------- 状態の送出
    def state(self) -> dict:
        return {"screen": self.screen, "data": self.payload}

    def _emit(self) -> None:
        self.on_change(self.state())

    def _goto(self, screen: str, payload: dict | None = None, *, auto_return: float | None = None) -> None:
        self.screen = screen
        self.payload = payload or {}
        self._cancel_return_timer()
        if auto_return is not None:
            self._return_timer = threading.Timer(auto_return, self.go_standby)
            self._return_timer.daemon = True
            self._return_timer.start()
        self._reset_idle()
        self._emit()

    # ---------------------------------------------------------- 画面構築
    @staticmethod
    def _group_by_category(items: list[dict]) -> dict:
        """物品のカテゴリ(ラベル)が複数種類ある場合のみ groups キーを追加する。

        未分類の物品は「未分類」というラベルにまとめる。カテゴリラベルが1種類
        （全未分類含む）なら items のフラット構造のみを返し、既存の描画
        （カテゴリ非対応）との後方互換を保つ。
        """
        labels = [it.get("category") or "未分類" for it in items]
        payload: dict = {"items": items}
        if len(set(labels)) >= 2:
            groups: dict[str, list[dict]] = {}
            for it, label in zip(items, labels):
                groups.setdefault(label, []).append(it)
            payload["groups"] = [
                {"category": cat, "items": its} for cat, its in groups.items()
            ]
        return payload

    def _standby_payload(self) -> dict:
        # 全物品の状況をリストで渡す。描画側（app.js）が物品1件なら従来のシンプル表示、
        # 複数件なら一覧表示に出し分ける。物品名はDBの値を使う（cfg.item_name は使わない）。
        now = self.ctx.clock.now()
        items: list[dict] = []
        for st in self.ctx.loans.status_list():
            item: dict = {"name": st.name, "is_lent": st.is_lent, "category": st.category or ""}
            if st.is_lent:
                item["is_overdue"] = st.is_overdue
                item["due_at"] = self._fmt(st.due_at)
                # 返却までの残り時間（分）と「まもなく返却」フラグを添える（FR-09 の補助）。
                # 延滞中は remaining_min が負になるが、表示は既存の overdue 色に任せる。
                if st.due_at:
                    remaining = int((from_iso(st.due_at) - now).total_seconds() // 60)
                    item["remaining_min"] = remaining
                    item["soon"] = 0 <= remaining <= self.cfg.due_soon_minutes
                if self.cfg.show_borrower_name and st.borrower_name:
                    item["borrower_name"] = st.borrower_name
            items.append(item)
        return self._group_by_category(items)

    def _home_screen(self) -> str:
        """待受のホーム画面。要タッチ設定なら attract、そうでなければ standby。"""
        return "attract" if self.cfg.require_tap_to_start else "standby"

    def _reset_member_admin_state(self) -> None:
        """メンバー管理（A02）で使う一時状態をまとめてクリアする。

        取り込み済みIDm・カード再発行待ち・結果メッセージを一括で消す。
        go_standby と open_member_admin の両方から呼び、クリア漏れを防ぐ。
        """
        self._capture_idm = None
        self._reissue_target = None
        self._reissue_message = ""

    def go_standby(self) -> None:
        """ホーム（待受）へ戻る。設定により attract / standby を選ぶ。"""
        with self._lock:
            self._admin = self._borrower = self._return_loan = None
            self._borrow_item = None
            self._borrow_duration = None
            self._force_return = False
            self._reset_member_admin_state()
            self._goto(self._home_screen(), self._standby_payload())

    def start(self) -> None:
        """attract 画面で画面タッチされたら、社員証待ち（standby）へ進む。"""
        with self._lock:
            if self.screen != "attract":
                return
            self._goto("standby", self._standby_payload())

    def _start_refresh_loop(self) -> None:
        """待機画面の表示（延滞など）を定期的に最新化するタイマを回す（FR-09）。"""
        if self._closed:
            return
        self._refresh_timer = threading.Timer(
            self.cfg.standby_refresh_seconds, self._periodic_refresh
        )
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _periodic_refresh(self) -> None:
        # ホーム（待受）に居るときだけ状況を再計算し、変化があれば push する。
        with self._lock:
            if self.screen == self._home_screen():
                payload = self._standby_payload()
                if payload != self.payload:
                    self.payload = payload
                    self._emit()
            self._scan_overdue()
        self._start_refresh_loop()

    def _scan_overdue(self) -> None:
        """新たに延滞になった貸出を見つけたら Teams へ通知する（画面に関係なく常時監視）。

        loan_id を記録して同じ貸出への重複通知を防ぐ（永続化はしない。再起動で
        リセットされても、通知が1回増える程度で実害は無いため割り切る）。
        """
        for st in self.ctx.loans.status_list():
            loan = st.open_loan
            if loan is None or not st.is_overdue:
                continue
            if loan.loan_id in self._overdue_notified:
                continue
            self._overdue_notified.add(loan.loan_id)
            self.ctx.notifier.notify_overdue(
                st.name, st.borrower_name or "", self._fmt(st.due_at)
            )

    # ---------------------------------------------------------- カードタッチ
    def on_card(self, idm: str) -> None:
        with self._lock:
            self._reset_idle()
            if self.screen == "member_admin":
                if self._reissue_target is not None:
                    # カード再発行待ち：このタッチのIDmを対象メンバーへ付け替える
                    try:
                        self.ctx.members.reissue_card(self._reissue_target, idm)
                        self._reissue_message = "カードを再発行しました"
                    except MemberError as e:
                        self._reissue_message = str(e)
                    self._reissue_target = None
                    self.payload = self._member_admin_payload()
                    self._emit()
                    return
                # 登録用にIDmを取り込む（A02）
                self._capture_idm = idm
                self.payload = self._member_admin_payload()
                self._emit()
                return
            if self.screen == "setup":
                # 初期管理者登録画面：誤タッチ訂正用に再タッチでIDmを取り込み直せる
                self._capture_idm = idm
                self.payload = {"idm": idm}
                self._emit()
                return
            if self.screen != "standby":
                return  # 待機画面以外のタッチは無視（誤操作防止）

            member = self.ctx.auth.authenticate(idm)
            if member is None:
                if not self.ctx.members.has_active_admin():
                    # 鶏卵問題対策：有効な管理者が1人もいない間だけ、
                    # 未登録カードのタッチを初期管理者登録画面へ誘導する。
                    audit().info("初期管理者登録へ遷移 idm=%s", idm)
                    self._capture_idm = idm
                    self._goto("setup", {"idm": idm})
                    return
                audit().info("認証失敗（未登録/無効） idm=%s", idm)
                self._goto("error", {"reason": "この社員証は登録されていません", "context": "auth"},
                           auto_return=self.cfg.result_screen_seconds)
                return
            if member.is_admin:
                audit().info("管理者ログイン member_id=%s name=%s", member.member_id, member.name)
                self._admin = member
                self._goto("admin_menu", self._admin_menu_payload())
                return
            # 未返却があれば返却導線を優先する（現仕様を維持）。
            returnable = self.ctx.loans.find_returnable_loans(member)
            if returnable:
                self._borrower = member
                self._start_return(returnable)
                return
            self._begin_borrow(member)

    # ---------------------------------------------------------- 貸出/返却の分岐ヘルパ
    def _begin_borrow(self, member) -> None:
        """空き物品数に応じて、物品選択（borrow_item）か時間選択（borrow_time）へ進む。"""
        available = self.ctx.loans.available_items()
        self._borrow_available_count = len(available)
        if not available:
            self._goto("error", {"reason": "空いている物品がありません", "context": "no_items"},
                       auto_return=self.cfg.result_screen_seconds)
            return
        self._borrower = member
        if len(available) == 1:
            # 空きが1つだけならタッチ回数を増やさず時間選択へ直行。
            self._borrow_item = available[0]
            self._goto("borrow_time", self._borrow_time_payload())
        else:
            self._borrow_item = None
            self._goto("borrow_item", self._borrow_item_payload(available))

    def _start_return(self, returnable) -> None:
        """返却候補数に応じて、返却物品選択（return_select）か返却確認へ進む。"""
        self._return_count = len(returnable)
        if len(returnable) == 1:
            self._return_loan = returnable[0]
            self._goto("return_confirm", self._return_confirm_payload(returnable[0]))
        else:
            self._goto("return_select", self._return_select_payload(returnable))

    # ---------------------------------------------------------- 貸出（S03/S04）
    def _borrow_item_payload(self, items) -> dict:
        return self._group_by_category([
            {
                "item_id": it.item_id, "name": it.name, "location": it.location or "",
                "category": it.category or "",
            }
            for it in items
        ])

    def _borrow_time_payload(self) -> dict:
        choices = [{"min": m, "label": DURATION_LABELS.get(m, f"{m}分")}
                   for m in self.cfg.duration_choices_min]
        data: dict = {
            "choices": choices,
            "custom_min": self.cfg.custom_duration_min_minutes,
            "custom_max": self.cfg.custom_duration_max_minutes,
        }
        if self._borrow_item is not None:
            data["item_name"] = self._borrow_item.name
        return data

    def choose_item(self, item_id: int) -> None:
        """物品選択画面（borrow_item）で物品を選ぶ → 時間選択へ。"""
        with self._lock:
            if self.screen != "borrow_item" or self._borrower is None:
                return
            available = {it.item_id: it for it in self.ctx.loans.available_items()}
            item = available.get(item_id)
            if item is None:
                self._goto("error", {
                    "reason": "この物品は選べません",
                    "context": self._item_count_context(self._borrow_available_count),
                }, auto_return=self.cfg.result_screen_seconds)
                return
            self._borrow_item = item
            self._goto("borrow_time", self._borrow_time_payload())

    def choose_duration(self, minutes: int) -> None:
        """貸出時間を選ぶ（まだ貸出は確定しない）→ 取り出し確認画面へ。"""
        with self._lock:
            if self.screen != "borrow_time" or self._borrower is None or self._borrow_item is None:
                return
            if not self.ctx.loans.is_valid_duration(minutes):
                self._goto("error", {
                    "reason": f"不正な貸出時間です: {minutes}",
                    "context": self._item_count_context(self._borrow_available_count),
                }, auto_return=self.cfg.result_screen_seconds)
                return
            self._borrow_duration = minutes
            self._goto("borrow_confirm", self._borrow_confirm_payload())

    def _borrow_confirm_payload(self) -> dict:
        due_preview = self.ctx.clock.now() + timedelta(minutes=self._borrow_duration)
        return {
            "item_name": self._borrow_item.name,
            "duration_min": self._borrow_duration,
            "due_at": self._fmt(to_iso(due_preview)),
        }

    def confirm_borrow(self) -> None:
        """取り出し確認画面（borrow_confirm）で「開錠する」を押したときに、実際に貸出・解錠する。"""
        with self._lock:
            if (
                self.screen != "borrow_confirm"
                or self._borrower is None
                or self._borrow_item is None
                or self._borrow_duration is None
            ):
                return
            try:
                loan = self.ctx.loans.borrow(
                    self._borrower, self._borrow_item.item_id, self._borrow_duration
                )
            except LoanError as e:
                self._goto("error", {
                    "reason": str(e),
                    "context": self._loan_error_context(e, self._borrow_available_count),
                }, auto_return=self.cfg.result_screen_seconds)
                return
            item_name = self._borrow_item.name
            self._goto("unlock", {"mode": "borrow", "due_at": self._fmt(loan.due_at),
                                  "item_name": item_name},
                       auto_return=self.cfg.result_screen_seconds)
            self._start_lock_watch(item_name)  # 閉め忘れ検知（FR-18）

    # ---------------------------------------------------------- 返却（S05/S07）
    def _item_name(self, item_id: int) -> str:
        item = self.ctx.item_repo.get(item_id)
        return item.name if item else ""

    def _return_confirm_payload(self, loan) -> dict:
        data = {
            "item_name": self._item_name(loan.item_id),
            "borrowed_at": self._fmt(loan.borrowed_at),
            "due_at": self._fmt(loan.due_at),
            "hold_seconds": self.cfg.return_confirm_hold_seconds,
            # 通常の返却導線では「延長」「借りる」も出す。管理者の強制返却中は
            # 他人の貸出を操作しているため、これらは出さない（返却/やめるのみ）。
            "can_extend": not self._force_return,
            "allow_borrow": not self._force_return,
        }
        if self._force_return:
            member = self.ctx.member_repo.get(loan.member_id)
            if member is not None:
                data["borrower_name"] = member.name
        return data

    def _return_select_payload(self, loans) -> dict:
        return {"loans": [
            {
                "loan_id": ln.loan_id,
                "item_name": self._item_name(ln.item_id),
                "borrowed_at": self._fmt(ln.borrowed_at),
                "due_at": self._fmt(ln.due_at),
            }
            for ln in loans
        ]}

    def choose_return(self, loan_id: int) -> None:
        """返却物品選択画面（return_select）で返す物品を選ぶ → 返却確認へ。"""
        with self._lock:
            if self.screen != "return_select" or self._borrower is None:
                return
            loans = {ln.loan_id: ln for ln in self.ctx.loans.find_returnable_loans(self._borrower)}
            loan = loans.get(loan_id)
            if loan is None:
                self._goto("error", {
                    "reason": "この貸出は返却できません",
                    "context": self._item_count_context(self._return_count),
                }, auto_return=self.cfg.result_screen_seconds)
                return
            self._return_loan = loan
            self._goto("return_confirm", self._return_confirm_payload(loan))

    def goto_borrow(self) -> None:
        """返却確認／返却選択画面から「借りる」へ移る（貸出導線に切り替え）。"""
        with self._lock:
            # 「借りる」ボタンはこの2画面にしか出ない。他画面からの誤/多重リクエストで
            # 進行中の画面（解錠中など）を奪われないよう、画面を限定する。
            if self.screen not in ("return_confirm", "return_select"):
                return
            if self._force_return:
                return  # 管理者強制返却中は貸出導線へ移らせない
            member = self._borrower or self._admin
            if member is None:
                return
            self._begin_borrow(member)

    # ---------------------------------------------------------- 延長（FR-16）
    def _extend_time_payload(self) -> dict:
        choices = [{"min": m, "label": DURATION_LABELS.get(m, f"{m}分")}
                   for m in self.cfg.duration_choices_min]
        data: dict = {
            "choices": choices,
            "custom_min": self.cfg.custom_duration_min_minutes,
            "custom_max": self.cfg.custom_duration_max_minutes,
        }
        if self._return_loan is not None:
            data["item_name"] = self._item_name(self._return_loan.item_id)
            data["due_at"] = self._fmt(self._return_loan.due_at)
        return data

    def open_extend(self) -> None:
        """返却確認画面から「延長する」→ 延長時間の選択へ。"""
        with self._lock:
            if self.screen != "return_confirm" or self._return_loan is None:
                return
            # 管理者の強制返却中は他人の貸出なので延長させない。
            if self._force_return:
                return
            self._goto("extend_time", self._extend_time_payload())

    def choose_extension(self, minutes: int) -> None:
        """延長時間を選ぶ → 延長を確定し、結果画面へ。"""
        with self._lock:
            if self.screen != "extend_time" or self._return_loan is None:
                return
            try:
                loan = self.ctx.loans.extend(self._return_loan, minutes)
            except LoanError as e:
                self._goto("error", {"reason": str(e), "context": "single_item"},
                           auto_return=self.cfg.result_screen_seconds)
                return
            self._return_loan = loan
            self._goto("extended", {
                "item_name": self._item_name(loan.item_id),
                "due_at": self._fmt(loan.due_at),
            }, auto_return=self.cfg.result_screen_seconds)

    # ---------------------------------------------------------- 強制返却（FR-17）
    def _force_return_select_payload(self) -> dict:
        loans = []
        for st in self.ctx.loans.status_list():
            if not st.is_lent or st.open_loan is None:
                continue
            loans.append({
                "loan_id": st.open_loan.loan_id,
                "item_name": st.name,
                "borrower_name": st.borrower_name or "",
                "due_at": self._fmt(st.due_at),
                "is_overdue": st.is_overdue,
            })
        return {"loans": loans}

    def open_force_return(self) -> None:
        """管理者が、貸出中の物品（他人の分を含む）を強制的に返却する導線を開く。"""
        with self._lock:
            denied = self._require_admin("強制返却")
            if denied:
                return
            self._reset_idle()
            self._force_return = True
            self._goto("force_return_select", self._force_return_select_payload())

    def choose_force_return(self, loan_id: int) -> None:
        """強制返却の対象を選ぶ → 返却確認（既存画面を流用）へ。"""
        with self._lock:
            if self.screen != "force_return_select" or self._admin is None:
                return
            loan = next(
                (ln for ln in self.ctx.loans.loans.list_open() if ln.loan_id == loan_id),
                None,
            )
            if loan is None:
                self._goto("error", {"reason": "この貸出は返却できません", "context": "multi_item"},
                           auto_return=self.cfg.result_screen_seconds)
                return
            audit().info(
                "管理者強制返却 開始 admin_id=%s loan_id=%s",
                self._admin.member_id, loan.loan_id,
            )
            self._return_loan = loan
            self._goto("return_confirm", self._return_confirm_payload(loan))

    # ---------------------------------------------------------- 閉め忘れ検知（FR-18）
    def _start_lock_watch(self, item_name: str) -> None:
        """解錠後、一定時間で施錠されたか確認するタイマを開始する。

        cam_switch 無効（cfg.cam_switch=="off"）なら何もしない（既定で完全 no-op）。
        """
        self._cancel_lock_watch()
        if self.cfg.cam_switch == "off":
            return
        self._lock_watch_timer = threading.Timer(
            self.cfg.relock_alert_seconds, self._check_lock, args=(item_name, 1)
        )
        self._lock_watch_timer.daemon = True
        self._lock_watch_timer.start()

    def _check_lock(self, item_name: str, attempt: int) -> None:
        with self._lock:
            if self._closed:
                return
            locked = self.ctx.lock_sensor.is_locked()
            if locked is True:
                return  # 施錠済み。監視終了。
            if locked is False:
                # 未施錠＝閉め忘れの疑い。通知し、上限まで再確認する。
                self.ctx.notifier.notify_not_locked(
                    item_name, self.cfg.relock_alert_seconds * attempt
                )
            # locked is None（読み取り不明）は通知せず、上限まで再確認だけ続ける。
            if attempt < self.cfg.relock_alert_repeat:
                self._lock_watch_timer = threading.Timer(
                    self.cfg.relock_alert_seconds, self._check_lock,
                    args=(item_name, attempt + 1),
                )
                self._lock_watch_timer.daemon = True
                self._lock_watch_timer.start()

    def _cancel_lock_watch(self) -> None:
        if self._lock_watch_timer is not None:
            self._lock_watch_timer.cancel()
            self._lock_watch_timer = None

    def confirm_return(self) -> None:
        with self._lock:
            if self.screen != "return_confirm" or self._return_loan is None:
                return
            try:
                self.ctx.loans.return_loan(self._return_loan)
            except LoanError as e:
                # 解錠失敗などは待機へ戻さずエラー画面で通知する（③）。
                self._goto("error", {
                    "reason": str(e),
                    "context": self._loan_error_context(e, self._return_count),
                }, auto_return=self.cfg.result_screen_seconds)
                return
            item_name = self._item_name(self._return_loan.item_id)
            self._force_return = False
            self._goto("unlock", {"mode": "return", "item_name": item_name},
                       auto_return=self.cfg.result_screen_seconds)
            self._start_lock_watch(item_name)  # 閉め忘れ検知（FR-18）

    def cancel(self) -> None:
        self.go_standby()

    # ---------------------------------------------------------- 管理（A01〜A03）
    def _require_admin(self, what: str) -> dict | None:
        """管理者セッションでなければ監査ログを残し、拒否レスポンスを返す。

        許可なら None。結果を返す管理操作で `denied = self._require_admin(...);
        if denied: return denied` の形で使い、認可チェックと監査を一箇所に集約する。
        """
        if self._admin is None:
            audit().info("権限なしで%sを試行 → 拒否", what)
            return {"ok": False, "message": "権限がありません"}
        return None

    def admin_menu(self) -> None:
        with self._lock:
            if self._admin is None:
                return
            self._goto("admin_menu", self._admin_menu_payload())

    def _dashboard_stats(self) -> dict:
        """管理メニューの先頭に出すサマリ（貸出中/延滞/本日/今月の貸出回数）。

        既存メソッド（status_list / list_borrowed_between）の再利用に留め、
        重い集計クエリは増やさない。
        """
        statuses = self.ctx.loans.status_list()
        lent = sum(1 for st in statuses if st.is_lent)
        overdue = sum(1 for st in statuses if st.is_overdue)
        now = self.ctx.clock.now()
        day_start = datetime.combine(now.date(), datetime.min.time())
        month_start = datetime.combine(now.date().replace(day=1), datetime.min.time())
        now_iso = to_iso(now)
        today = len(self.ctx.loan_repo.list_borrowed_between(to_iso(day_start), now_iso))
        month = len(self.ctx.loan_repo.list_borrowed_between(to_iso(month_start), now_iso))
        return {"lent": lent, "overdue": overdue, "today": today, "month": month}

    def _admin_menu_payload(self) -> dict:
        data: dict = {"admin_name": self._admin.name}
        # 管理者自身の未返却があれば、管理メニューから返却できるようにする。
        # （is_admin はカードタッチで admin_menu へ直行するため、通常の返却導線に乗らない）
        loans = self.ctx.loans.find_returnable_loans(self._admin)
        if loans:
            data["can_return"] = True
            data["return_count"] = len(loans)
        stats = self._dashboard_stats()
        data["stats"] = stats
        # 誰かが借りている物品があれば、強制返却（他人の分を含む）を出す（FR-17）。
        data["any_lent"] = stats["lent"] > 0
        # 時刻同期の状態（延滞判定の信頼性の可視化：P7）。
        data["time_sync"] = ntp_status()
        # カムスイッチ（施錠検知）が有効なら現在の施錠状態を見せる（09 §5-1）。
        # 無効/不明（None）のときはキーごと出さない。
        locked = self.ctx.lock_sensor.is_locked()
        if locked is not None:
            data["lock_state"] = "locked" if locked else "unlocked"
        return data

    def admin_return(self) -> None:
        """管理メニューから、管理者自身が借りている物品を返却する（複数対応）。"""
        with self._lock:
            if self._admin is None:
                return
            loans = self.ctx.loans.find_returnable_loans(self._admin)
            if not loans:
                self._goto("admin_menu", self._admin_menu_payload())
                return
            self._borrower = self._admin
            self._start_return(loans)

    def open_member_admin(self) -> None:
        with self._lock:
            if self._admin is None:
                return
            self._reset_member_admin_state()
            self._goto("member_admin", self._member_admin_payload())

    def open_report(self) -> None:
        with self._lock:
            if self._admin is None:
                return
            today = date.today()
            self._goto("report", {
                "start": today.replace(day=1).strftime("%Y/%m/%d"),
                "end": today.strftime("%Y/%m/%d"),
                "path": "lending_log.csv",
                "result": "",
            })

    def admin_self_borrow(self) -> None:
        with self._lock:
            if self._admin is None:
                return
            self._begin_borrow(self._admin)

    # ---------------------------------------------------------- ログ閲覧（FR-12）
    def _history_payload(self, start: date, end: date) -> dict:
        rows = self.ctx.reports.history_rows(start, end)
        return {
            "header": CSV_HEADER,
            "rows": rows,
            "start": start.strftime("%Y/%m/%d"),
            "end": end.strftime("%Y/%m/%d"),
            "total": len(rows),
        }

    def open_history(self) -> None:
        """管理メニューから貸借ログを画面で閲覧する（既定は当月）。"""
        with self._lock:
            if self._admin is None:
                return
            today = date.today()
            self._goto("history", self._history_payload(today.replace(day=1), today))

    def view_history(self, start_s: str, end_s: str) -> dict:
        with self._lock:
            denied = self._require_admin("ログ閲覧")
            if denied:
                return denied
            self._reset_idle()
            try:
                start = datetime.strptime(start_s.strip(), "%Y/%m/%d").date()
                end = datetime.strptime(end_s.strip(), "%Y/%m/%d").date()
            except ValueError:
                return {"ok": False, "message": "日付は YYYY/MM/DD 形式で入力してください"}
            self.payload = self._history_payload(start, end)
            self._emit()
            return {"ok": True, "message": f"{self.payload['total']} 件"}

    # ---------------------------------------------------------- 設定画面（FR-19）
    def _settings_payload(self) -> dict:
        c = self.cfg
        return {
            "values": {f: getattr(c, f) for f in _EDITABLE_SETTINGS},
            # 起動時依存で画面からは変えられない（参考表示用・読み取り専用）。
            "readonly": {
                "card_reader": c.card_reader, "lock": c.lock,
                "cam_switch": c.cam_switch, "theme": c.theme,
            },
        }

    def open_settings(self) -> None:
        with self._lock:
            if self._admin is None:
                return
            self._goto("settings", self._settings_payload())

    def update_settings(self, values: dict) -> dict:
        """設定画面からの保存。検証→その場反映→config.json へ永続化。"""
        with self._lock:
            denied = self._require_admin("設定変更")
            if denied:
                return denied
            self._reset_idle()
            # 型を既定値から推定して変換（JSON 由来の文字列/数値を吸収）。
            staged: dict = {}
            for key in _EDITABLE_SETTINGS:
                if key not in values:
                    continue
                current = getattr(self.cfg, key)
                try:
                    staged[key] = _coerce_like(current, values[key])
                except (ValueError, TypeError):
                    return {"ok": False, "message": f"{key} の値が不正です"}
            # まずコピーに当てて検証（不正なら ctx.cfg は一切触らない）。
            trial = replace(self.cfg, **staged)
            try:
                trial.validate()
            except ConfigError as e:
                return {"ok": False, "message": str(e)}
            # 検証OK：実 cfg をその場で更新（大半のサービスは利用時に cfg を読む）。
            for key, val in staged.items():
                setattr(self.cfg, key, val)
            # 通知ON/OFFは Notifier の内部フラグにも反映する。
            self.ctx.notifier._overdue_enabled = self.cfg.teams_notify_overdue
            self.ctx.notifier._errors_enabled = self.cfg.teams_notify_errors
            self.ctx.notifier._routine_enabled = self.cfg.teams_notify_routine
            try:
                self.cfg.save()
            except OSError as e:
                _log.error("設定の保存に失敗: %s", e)
                return {"ok": False, "message": f"保存に失敗しました: {e}"}
            audit().info("設定変更 %s", staged)
            self.payload = self._settings_payload()
            self._emit()
            return {"ok": True, "message": "設定を保存しました"}

    # ---------------------------------------------------------- 物品管理
    def open_item_admin(self) -> None:
        with self._lock:
            if self._admin is None:
                return
            self._goto("item_admin", self._item_admin_payload())

    def _item_admin_payload(self) -> dict:
        return {"items": self.ctx.item_svc.list_with_status()}

    def add_item(self, name: str, location: str, category: str = "") -> dict:
        with self._lock:
            denied = self._require_admin("物品追加")
            if denied:
                return denied
            self._reset_idle()
            try:
                self.ctx.item_svc.add_item(name, location, category)
            except ItemError as e:
                return {"ok": False, "message": str(e)}
            self.payload = self._item_admin_payload()
            self._emit()
            return {"ok": True, "message": f"{(name or '').strip()} を追加しました"}

    def update_item(self, item_id: int, name: str, location: str, category: str = "") -> dict:
        with self._lock:
            denied = self._require_admin("物品編集")
            if denied:
                return denied
            self._reset_idle()
            try:
                self.ctx.item_svc.update_item(item_id, name, location, category)
            except ItemError as e:
                return {"ok": False, "message": str(e)}
            self.payload = self._item_admin_payload()
            self._emit()
            return {"ok": True, "message": "更新しました"}

    def set_item_active(self, item_id: int, active: bool) -> dict:
        with self._lock:
            denied = self._require_admin("物品状態変更")
            if denied:
                return denied
            self._reset_idle()
            try:
                if active:
                    self.ctx.item_svc.activate_item(item_id)
                else:
                    self.ctx.item_svc.deactivate_item(item_id)
            except ItemError as e:
                return {"ok": False, "message": str(e)}
            self.payload = self._item_admin_payload()
            self._emit()
            return {"ok": True, "message": "更新しました"}

    def _member_admin_payload(self) -> dict:
        members = [{
            "member_id": m.member_id, "name": m.name, "employee_no": m.employee_no,
            "role": m.role, "is_active": m.is_active,
        } for m in self.ctx.members.list_all()]
        return {
            "captured_idm": self._capture_idm or "",
            "members": members,
            "reissue_target_id": self._reissue_target,
            "reissue_message": self._reissue_message,
        }

    def register_member(self, name: str, employee_no: str, role: str) -> dict:
        with self._lock:
            denied = self._require_admin("メンバー登録")
            if denied:
                return denied
            self._reset_idle()
            try:
                self.ctx.members.register(self._capture_idm or "", employee_no, name, role)
            except MemberError as e:
                return {"ok": False, "message": str(e)}
            self._capture_idm = None
            self.payload = self._member_admin_payload()
            self._emit()
            return {"ok": True, "message": f"{name} を登録しました"}

    def register_initial_admin(self, name: str, employee_no: str) -> dict:
        """初期管理者登録（setup画面）。成功したら admin_menu へ進む。"""
        with self._lock:
            if self.screen != "setup":
                return {"ok": False, "message": "不正な操作です"}
            self._reset_idle()
            try:
                member = self.ctx.members.register_initial_admin(
                    self._capture_idm or "", employee_no, name
                )
            except MemberError as e:
                return {"ok": False, "message": str(e)}
            audit().info(
                "初期管理者登録 member_id=%s name=%s", member.member_id, member.name
            )
            self._capture_idm = None
            self._admin = member
            self._goto("admin_menu", self._admin_menu_payload())
            return {"ok": True, "message": f"{name} を管理者として登録しました"}

    def set_member_active(self, member_id: int, active: bool) -> dict:
        with self._lock:
            denied = self._require_admin("メンバー状態変更")
            if denied:
                return denied
            self._reset_idle()
            # ログイン中の管理者自身の無効化は、この場の権限（_adminは認証時のスナップ
            # ショット）がDBと食い違ったまま残るため禁止する。
            if not active and member_id == self._admin.member_id:
                return {"ok": False, "message": "ログイン中の自分自身は無効化できません"}
            try:
                if active:
                    self.ctx.members.activate(member_id)
                else:
                    self.ctx.members.deactivate(member_id)
            except MemberError as e:
                return {"ok": False, "message": str(e)}
            self.payload = self._member_admin_payload()
            self._emit()
            return {"ok": True, "message": "更新しました"}

    def set_member_role(self, member_id: int, role: str) -> dict:
        with self._lock:
            denied = self._require_admin("ロール変更")
            if denied:
                return denied
            self._reset_idle()
            # 自分自身をuserへ降格すると、この場の管理者権限（_adminは認証時の
            # スナップショット）がDBと食い違ったまま残るため禁止する。
            if role == "user" and member_id == self._admin.member_id:
                return {"ok": False, "message": "ログイン中の自分自身は一般に変更できません"}
            try:
                self.ctx.members.set_role(member_id, role)
            except MemberError as e:
                return {"ok": False, "message": str(e)}
            self.payload = self._member_admin_payload()
            self._emit()
            return {"ok": True, "message": "ロールを変更しました"}

    def update_member(self, member_id: int, name: str, employee_no: str) -> dict:
        with self._lock:
            denied = self._require_admin("メンバー編集")
            if denied:
                return denied
            self._reset_idle()
            try:
                self.ctx.members.update_profile(member_id, name, employee_no)
            except MemberError as e:
                return {"ok": False, "message": str(e)}
            self.payload = self._member_admin_payload()
            self._emit()
            return {"ok": True, "message": "更新しました"}

    def start_card_reissue(self, member_id: int) -> None:
        """対象メンバーを「カード待ち」状態にする。次のタッチで付け替える。"""
        with self._lock:
            if self._admin is None or self.screen != "member_admin":
                audit().info("権限なしでカード再発行を試行 member_id=%s → 拒否", member_id)
                return
            self._reset_idle()
            self._capture_idm = None  # 新規登録の取込みと混同しないようクリア
            self._reissue_target = member_id
            self._reissue_message = ""
            self.payload = self._member_admin_payload()
            self._emit()

    def cancel_card_reissue(self) -> None:
        with self._lock:
            # start_card_reissue と同様、メンバー管理画面でのみ有効
            # （他画面で呼ばれると member_admin の payload を誤って push してしまう）。
            if self._admin is None or self.screen != "member_admin":
                return
            self._reset_idle()
            self._reissue_target = None
            self.payload = self._member_admin_payload()
            self._emit()

    def export_report(self, start_s: str, end_s: str, path: str) -> dict:
        with self._lock:
            denied = self._require_admin("CSV出力")
            if denied:
                return denied
            self._reset_idle()
            try:
                start = datetime.strptime(start_s.strip(), "%Y/%m/%d").date()
                end = datetime.strptime(end_s.strip(), "%Y/%m/%d").date()
            except ValueError:
                return {"ok": False, "message": "日付は YYYY/MM/DD 形式で入力してください"}
            try:
                safe_path = validate_export_path(
                    path, self.cfg.csv_export_dirs, self.cfg.db_path
                )
            except ExportPathError as e:
                _log.warning("CSV出力先が拒否されました path=%s: %s", path, e)
                return {"ok": False, "message": str(e)}
            try:
                n = self.ctx.reports.export_csv(start, end, safe_path)
            except OSError as e:
                _log.error("CSV出力に失敗 path=%s: %s", path, e)
                return {"ok": False, "message": str(e)}
            audit().info(
                "CSV出力 start=%s end=%s rows=%s path=%s",
                start_s.strip(), end_s.strip(), n, safe_path,
            )
            return {"ok": True, "message": f"{n} 件を書き出しました → {safe_path}"}

    # ---------------------------------------------------------- 無操作タイムアウト（NFR-06）
    def _reset_idle(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        self._idle_timer = threading.Timer(self.cfg.idle_timeout_seconds, self._on_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _on_idle(self) -> None:
        # 既にホーム（attract/standby）に居るなら何もしない。それ以外は待受へ戻す。
        if self.screen != self._home_screen():
            self.go_standby()

    def _cancel_return_timer(self) -> None:
        if self._return_timer is not None:
            self._return_timer.cancel()
            self._return_timer = None

    def shutdown(self) -> None:
        self._closed = True  # 定期リフレッシュの再スケジュールを止める
        for t in (self._idle_timer, self._return_timer, self._refresh_timer,
                  self._lock_watch_timer):
            if t is not None:
                t.cancel()
