"""設定の読み込み（NFR-13：解錠秒数・タイムアウト等を設定で変更可能）。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    db_path: str = "lending.sqlite3"
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

    # 課題管理表の未決事項（[10] Q4/Q6 等）を設定で切替
    show_borrower_name: bool = True
    allow_return_by_others: bool = False

    # 最初に「画面にタッチしてはじめる」待受を挟むか（true=要タッチ / false=直接カード待ち）
    require_tap_to_start: bool = False

    # ハードウェア（09_ハードウェア設計書）
    lock_gpio_pin: int = 17
    lock_active_high: bool = True

    # デバイス選択: "auto" | "mock" | "real"
    card_reader: str = "auto"
    lock: str = "auto"

    # ログ（監査ログ／運用ログ）。NFR として本番運用で追跡可能にする。
    log_dir: str = "logs"
    log_level: str = "INFO"
    log_max_bytes: int = 1_000_000
    log_backup_count: int = 7

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
        return cfg

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
        if self.card_reader not in ("auto", "mock", "real"):
            errors.append("card_reader は auto/mock/real のいずれかです")
        if self.lock not in ("auto", "mock", "real"):
            errors.append("lock は auto/mock/real のいずれかです")
        if self.log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            errors.append("log_level が不正です")
        if errors:
            raise ConfigError("config.json の設定が不正です: " + " / ".join(errors))


class ConfigError(Exception):
    """設定値が不正なときに送出する。"""
