"""キオスク端末の状態機械（サーバ側コントローラ）。

ブラウザは「サーバが指示した画面を描画するだけ」の薄い作りにし、
画面遷移ロジック（認証→貸出/返却/管理/エラー）はここに一元化する。
状態が変わるたび on_change(state) を呼び、サーバが SSE でブラウザへ push する。

Tkinter 版コントローラ（app/ui）と同じ遷移をサーバ側へ移したもの。
"""
from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Callable

from app.context import AppContext
from app.services.clock import from_iso
from app.services.loan import LoanError
from app.services.member import MemberError

DURATION_LABELS = {15: "15分", 30: "30分", 60: "1時間", 120: "2時間", 240: "4時間", 480: "8時間"}


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
        self._return_loan = None    # 返却対象ログ
        self._capture_idm: str | None = None  # A02 登録用に取り込んだIDm

        self._idle_timer: threading.Timer | None = None
        self._return_timer: threading.Timer | None = None

    # ---------------------------------------------------------- 日時整形
    def _fmt(self, iso: str | None) -> str:
        return from_iso(iso).strftime(self.cfg.csv_datetime_format) if iso else ""

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
    def _standby_payload(self) -> dict:
        st = self.ctx.loans.status()
        data: dict = {"is_lent": st.is_lent, "item_name": self.cfg.item_name}
        if st.is_lent:
            data["is_overdue"] = st.is_overdue
            data["due_at"] = self._fmt(st.due_at)
            if self.cfg.show_borrower_name and st.borrower_name:
                data["borrower_name"] = st.borrower_name
        return data

    def _home_screen(self) -> str:
        """待受のホーム画面。要タッチ設定なら attract、そうでなければ standby。"""
        return "attract" if self.cfg.require_tap_to_start else "standby"

    def go_standby(self) -> None:
        """ホーム（待受）へ戻る。設定により attract / standby を選ぶ。"""
        with self._lock:
            self._admin = self._borrower = self._return_loan = self._capture_idm = None
            self._goto(self._home_screen(), self._standby_payload())

    def start(self) -> None:
        """attract 画面で画面タッチされたら、社員証待ち（standby）へ進む。"""
        with self._lock:
            if self.screen != "attract":
                return
            self._goto("standby", self._standby_payload())

    def refresh(self) -> None:
        """現在画面を作り直して再送（SSE再接続時の初期表示用）。"""
        with self._lock:
            if self.screen == "standby":
                self.payload = self._standby_payload()
            self._emit()

    # ---------------------------------------------------------- カードタッチ
    def on_card(self, idm: str) -> None:
        with self._lock:
            self._reset_idle()
            if self.screen == "member_admin":
                # 登録用にIDmを取り込む（A02）
                self._capture_idm = idm
                self.payload = self._member_admin_payload()
                self._emit()
                return
            if self.screen != "standby":
                return  # 待機画面以外のタッチは無視（誤操作防止）

            member = self.ctx.auth.authenticate(idm)
            if member is None:
                self._goto("error", {"reason": "この社員証は登録されていません"},
                           auto_return=self.cfg.result_screen_seconds)
                return
            if member.is_admin:
                self._admin = member
                self._goto("admin_menu", {"admin_name": member.name})
                return
            returnable = self.ctx.loans.find_returnable_loan(member)
            if returnable is not None:
                self._borrower = member
                self._return_loan = returnable
                self._goto("return_confirm", {
                    "borrowed_at": self._fmt(returnable.borrowed_at),
                    "due_at": self._fmt(returnable.due_at),
                })
                return
            if self.ctx.loans.status().is_lent:
                self._goto("error", {"reason": "貸出中のため借りられません"},
                           auto_return=self.cfg.result_screen_seconds)
                return
            self._borrower = member
            self._goto("borrow_time", self._borrow_time_payload())

    # ---------------------------------------------------------- 貸出（S03/S04）
    def _borrow_time_payload(self) -> dict:
        choices = [{"min": m, "label": DURATION_LABELS.get(m, f"{m}分")}
                   for m in self.cfg.duration_choices_min]
        return {"choices": choices}

    def choose_duration(self, minutes: int) -> None:
        with self._lock:
            if self.screen != "borrow_time" or self._borrower is None:
                return
            try:
                loan = self.ctx.loans.borrow(self._borrower, minutes)
            except LoanError as e:
                self._goto("error", {"reason": str(e)}, auto_return=self.cfg.result_screen_seconds)
                return
            self._goto("unlock", {"mode": "borrow", "due_at": self._fmt(loan.due_at)},
                       auto_return=self.cfg.result_screen_seconds)

    # ---------------------------------------------------------- 返却（S05/S07）
    def confirm_return(self) -> None:
        with self._lock:
            if self.screen != "return_confirm" or self._return_loan is None:
                return
            self.ctx.loans.return_loan(self._return_loan)
            self._goto("unlock", {"mode": "return"}, auto_return=self.cfg.result_screen_seconds)

    def cancel(self) -> None:
        self.go_standby()

    # ---------------------------------------------------------- 管理（A01〜A03）
    def admin_menu(self) -> None:
        with self._lock:
            if self._admin is None:
                return
            self._goto("admin_menu", {"admin_name": self._admin.name})

    def open_member_admin(self) -> None:
        with self._lock:
            if self._admin is None:
                return
            self._capture_idm = None
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
            if self.ctx.loans.status().is_lent:
                self._goto("error", {"reason": "貸出中のため借りられません"},
                           auto_return=self.cfg.result_screen_seconds)
                return
            self._borrower = self._admin
            self._goto("borrow_time", self._borrow_time_payload())

    def _member_admin_payload(self) -> dict:
        members = [{
            "member_id": m.member_id, "name": m.name, "employee_no": m.employee_no,
            "role": m.role, "is_active": m.is_active,
        } for m in self.ctx.members.list_all()]
        return {"captured_idm": self._capture_idm or "", "members": members}

    def register_member(self, name: str, employee_no: str, role: str) -> dict:
        with self._lock:
            self._reset_idle()
            try:
                self.ctx.members.register(self._capture_idm or "", employee_no, name, role)
            except MemberError as e:
                return {"ok": False, "message": str(e)}
            self._capture_idm = None
            self.payload = self._member_admin_payload()
            self._emit()
            return {"ok": True, "message": f"{name} を登録しました"}

    def set_member_active(self, member_id: int, active: bool) -> None:
        with self._lock:
            self._reset_idle()
            if active:
                self.ctx.members.activate(member_id)
            else:
                self.ctx.members.deactivate(member_id)
            self.payload = self._member_admin_payload()
            self._emit()

    def export_report(self, start_s: str, end_s: str, path: str) -> dict:
        with self._lock:
            self._reset_idle()
            try:
                start = datetime.strptime(start_s.strip(), "%Y/%m/%d").date()
                end = datetime.strptime(end_s.strip(), "%Y/%m/%d").date()
            except ValueError:
                return {"ok": False, "message": "日付は YYYY/MM/DD 形式で入力してください"}
            try:
                n = self.ctx.reports.export_csv(start, end, path.strip())
            except OSError as e:
                return {"ok": False, "message": str(e)}
            return {"ok": True, "message": f"{n} 件を書き出しました → {path}"}

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
        for t in (self._idle_timer, self._return_timer):
            if t is not None:
                t.cancel()
