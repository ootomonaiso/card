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

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        if path is None:
            path = Path(__file__).resolve().parent.parent / "config.json"
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})
