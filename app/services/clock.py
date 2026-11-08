"""時刻の供給（NFR-03）。

本番は OS 時刻（NTP/RTC で同期済み前提）を返す。テストでは固定時刻を注入できる。
日時は ISO 8601 文字列（秒精度）で保存し、表示/CSV で書式を変える。
"""
from __future__ import annotations

from datetime import datetime, timedelta


class Clock:
    """現在時刻を返す。差し替え可能にしてテストを容易にする。"""

    def now(self) -> datetime:
        return datetime.now()


class FixedClock(Clock):
    """テスト用：固定時刻。"""

    def __init__(self, fixed: datetime) -> None:
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed

    def set(self, dt: datetime) -> None:
        self._fixed = dt

    def advance(self, **kwargs) -> None:
        self._fixed = self._fixed + timedelta(**kwargs)


def to_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(sep=" ")


def from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)
