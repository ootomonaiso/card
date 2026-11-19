"""設定の読み込み（NFR-13：解錠秒数・タイムアウト等を設定で変更可能）。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    db_path: str = "lending.sqlite3"
    # item_name / item_location は「空DBの初回起動時に入れる最初の1件」の初期シード。
    # 物品マスタの実体は ITEM テーブル（複数物品対応）で、以後の増減は物品管理画面で行う。
    # 既に物品が登録済みのDBでは、この値は参照されない（後方互換のフォールバック）。
    item_name: str = "セキュアカメラ"
    item_location: str = "保管庫A"

    unlock_seconds: float = 5.0
    min_reunlock_seconds: float = 3.0
    idle_timeout_seconds: float = 30.0
    result_screen_seconds: float = 6.0
    # 待機画面を定期的に作り直す間隔（延滞表示などを最新化する：FR-09）
    standby_refresh_seconds: float = 20.0

    duration_choices_min: list[int] = field(default_factory=lambda: [15, 30, 60, 120, 240, 480])
    csv_datetime_format: str = "%Y/%m/%d %H:%M"
    csv_encoding: str = "utf-8-sig"
    # CSV 出力を許可するディレクトリ（管理者入力の任意パス書き込みを封じ込める）。
    # 既定はカレントと Bookworm の USB 自動マウント先（/media, /mnt）。配下の *.csv のみ許可。
    csv_export_dirs: list[str] = field(default_factory=lambda: [".", "/media", "/mnt"])

    # 課題管理表の未決事項（[10] Q4/Q6 等）を設定で切替
    show_borrower_name: bool = True
    allow_return_by_others: bool = False

    # 最初に「画面にタッチしてはじめる」待受を挟むか（true=要タッチ / false=直接カード待ち）
    require_tap_to_start: bool = False

    # ハードウェア（09_ハードウェア設計書）
    # lock_gpio_pin / lock_active_high は後方互換のフォールバック。
    # locks を指定しない（既定）場合、この2値から単一スロットの locks が組み立てられ、
    # 現行の「全物品で1ロック共有」動作と完全に同じになる。
    lock_gpio_pin: int = 17
    lock_active_high: bool = True
    # 複数ロック対応（ソフト設計）。各要素: slot名, gpio_pin, active_high, item_ids（紐づく物品ID。
    # 空リストは「どの item_ids にも明示的に紐づかない物品のデフォルト受け皿」を意味する）。
    # 既定は空リスト＝未指定（lock_gpio_pin/lock_active_high から単一スロットを自動生成）。
    locks: list[dict] = field(default_factory=list)

    # 施錠検知センサ（LE-53 カムスイッチ：09 §5-1）。既定は "off"（未使用）。
    # 配線・現物確認が済んだら "auto"（Pi では実機, それ以外はモック）等に変更する。
    cam_switch: str = "off"        # "off" | "auto" | "mock" | "real"
    cam_switch_gpio_pin: int = 27
    cam_switch_active_low: bool = True  # 施錠で接点が GND に落ちる（内部プルアップ）
    cam_switch_bounce_ms: int = 50
    # 連続して何回読み取り失敗したら「配線異常疑い」として error ログ/通知を1回発火するか
    cam_switch_fail_streak_threshold: int = 5

    # デバイス選択: "auto" | "mock" | "real"
    card_reader: str = "auto"
    lock: str = "auto"

    # ログ（監査ログ／運用ログ）。NFR として本番運用で追跡可能にする。
    log_dir: str = "logs"
    log_level: str = "INFO"
    log_max_bytes: int = 1_000_000
    log_backup_count: int = 7

    # UI テーマ（管理者がconfig.jsonで設定。エンドユーザー向けトグルは設けない）
    theme: str = "dark"  # "dark" | "light"

    # カスタム貸出時間（端末での分単位フリー入力。duration_choices_min のプリセットに加え、
    # この範囲内の任意の整数分も許可する）
    custom_duration_min_minutes: int = 1
    custom_duration_max_minutes: int = 1440

    # 返却確認画面での長押し秒数（誤操作防止）。0 を指定するとワンタップ確認に戻る。
    return_confirm_hold_seconds: float = 3.0

    # 待受画面で「まもなく返却」として強調する残り時間のしきい値（分）。
    # 残り時間が 0 より大きく、この値以下なら warn 色で「あと◯分」を表示する（FR-09 の補助）。
    due_soon_minutes: int = 15

    # 閉め忘れ検知（09 §5-1 カムスイッチ活用）。cam_switch が有効（is_locked が None 以外）な
    # ときのみ作用する。解錠後この秒数を過ぎても施錠されなければ通知し、relock_alert_repeat 回
    # まで再確認する。cam_switch="off"（既定）では完全 no-op。
    relock_alert_seconds: float = 30.0
    relock_alert_repeat: int = 3

    # Teams Webhook 通知。URL 未設定なら完全に no-op。
    teams_webhook_url: str = ""
    teams_notify_overdue: bool = True
    teams_notify_errors: bool = True
    teams_notify_routine: bool = False

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        if path is None:
            path = Path(__file__).resolve().parent.parent / "config.json"
        path = Path(path)
        if not path.exists():
            cfg = cls()
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
            cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.validate()
        # 読み込み元のパスを覚えておき、save() で同じファイルへ書き戻せるようにする
        # （設定画面からの永続化で使う。dataclass フィールドではないので JSON には出ない）。
        cfg._source_path = path
        return cfg

    def save(self, path: str | Path | None = None) -> None:
        """現在の設定値を JSON へ書き出す（設定画面からの永続化）。

        保存前に validate() で不正値を弾く。path 省略時は load() で読んだ元ファイル、
        それも無ければ既定の config.json に書く。_source_path 等の内部属性は出力しない。
        """
        self.validate()
        if path is None:
            path = getattr(self, "_source_path", None) or (
                Path(__file__).resolve().parent.parent / "config.json"
            )
        path = Path(path)
        data = {f: getattr(self, f) for f in self.__dataclass_fields__}  # type: ignore[attr-defined]
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def validate(self) -> None:
        """設定値の妥当性を検査する。不正なら ConfigError を送出。"""
        errors: list[str] = []
        if self.unlock_seconds <= 0:
            errors.append("unlock_seconds は正の値である必要があります")
        if self.min_reunlock_seconds < 0:
            errors.append("min_reunlock_seconds は 0 以上である必要があります")
        if self.idle_timeout_seconds <= 0:
            errors.append("idle_timeout_seconds は正の値である必要があります")
        if self.result_screen_seconds <= 0:
            errors.append("result_screen_seconds は正の値である必要があります")
        if self.standby_refresh_seconds <= 0:
            errors.append("standby_refresh_seconds は正の値である必要があります")
        if not self.duration_choices_min:
            errors.append("duration_choices_min は 1 件以上必要です")
        elif any((not isinstance(m, int)) or m <= 0 for m in self.duration_choices_min):
            errors.append("duration_choices_min は正の整数のみ指定できます")
        if not self.csv_export_dirs:
            errors.append("csv_export_dirs は 1 件以上必要です")
        elif any((not isinstance(d, str)) or not d.strip() for d in self.csv_export_dirs):
            errors.append("csv_export_dirs は空でない文字列のみ指定できます")
        if self.card_reader not in ("auto", "mock", "real"):
            errors.append("card_reader は auto/mock/real のいずれかです")
        if self.lock not in ("auto", "mock", "real"):
            errors.append("lock は auto/mock/real のいずれかです")
        if self.cam_switch not in ("off", "auto", "mock", "real"):
            errors.append("cam_switch は off/auto/mock/real のいずれかです")
        if self.cam_switch_fail_streak_threshold <= 0:
            errors.append("cam_switch_fail_streak_threshold は正の整数である必要があります")
        if self.log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            errors.append("log_level が不正です")
        if self.theme not in ("dark", "light"):
            errors.append("theme は dark/light のいずれかです")
        if not isinstance(self.custom_duration_min_minutes, int) or self.custom_duration_min_minutes <= 0:
            errors.append("custom_duration_min_minutes は正の整数である必要があります")
        if not isinstance(self.custom_duration_max_minutes, int) or self.custom_duration_max_minutes <= 0:
            errors.append("custom_duration_max_minutes は正の整数である必要があります")
        elif self.custom_duration_min_minutes > self.custom_duration_max_minutes:
            errors.append("custom_duration_min_minutes は custom_duration_max_minutes 以下である必要があります")
        if self.return_confirm_hold_seconds < 0:
            errors.append("return_confirm_hold_seconds は 0 以上である必要があります")
        if not isinstance(self.due_soon_minutes, int) or self.due_soon_minutes <= 0:
            errors.append("due_soon_minutes は正の整数である必要があります")
        if self.relock_alert_seconds <= 0:
            errors.append("relock_alert_seconds は正の値である必要があります")
        if not isinstance(self.relock_alert_repeat, int) or self.relock_alert_repeat <= 0:
            errors.append("relock_alert_repeat は正の整数である必要があります")
        if self.teams_webhook_url and not self.teams_webhook_url.startswith("https://"):
            errors.append("teams_webhook_url は https:// で始まる必要があります")
        if not isinstance(self.locks, list):
            errors.append("locks はリストである必要があります")
        else:
            seen_pins: set[int] = set()
            seen_slots: set[str] = set()
            for slot_cfg in self.locks:
                if not isinstance(slot_cfg, dict):
                    errors.append("locks の各要素はオブジェクトである必要があります")
                    continue
                pin = slot_cfg.get("gpio_pin")
                slot = slot_cfg.get("slot")
                item_ids = slot_cfg.get("item_ids", [])
                if not isinstance(pin, int):
                    errors.append("locks[].gpio_pin は整数である必要があります")
                elif pin in seen_pins:
                    errors.append(f"locks[].gpio_pin が重複しています: {pin}")
                else:
                    seen_pins.add(pin)
                if not isinstance(slot, str) or not slot.strip():
                    errors.append("locks[].slot は空でない文字列である必要があります")
                elif slot in seen_slots:
                    errors.append(f"locks[].slot が重複しています: {slot}")
                else:
                    seen_slots.add(slot)
                if not isinstance(item_ids, list) or any(not isinstance(i, int) for i in item_ids):
                    errors.append("locks[].item_ids は整数のリストである必要があります")
        if errors:
            raise ConfigError("config.json の設定が不正です: " + " / ".join(errors))


class ConfigError(Exception):
    """設定値が不正なときに送出する。"""
