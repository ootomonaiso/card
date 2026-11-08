"""テスト共通のセットアップ（インメモリDB・モックデバイス・固定時計）。"""
from __future__ import annotations

from datetime import datetime

from app.config import Config
from app.context import AppContext
from app.db import connect, init_db
from app.devices.mock import MockCardReader, MockLock
from app.services.clock import FixedClock

DEFAULT_NOW = datetime(2026, 11, 8, 9, 0, 0)


def make_ctx(clock: FixedClock | None = None, **cfg_overrides) -> AppContext:
    """モックデバイス＋インメモリDBの AppContext を作る。"""
    clock = clock or FixedClock(DEFAULT_NOW)
    cfg = Config(db_path=":memory:", unlock_seconds=0.01, **cfg_overrides)
    conn = connect(":memory:")
    init_db(conn, cfg.item_name, cfg.item_location)
    return AppContext(
        cfg, conn, clock=clock,
        card_reader=MockCardReader(),
        lock=MockLock(unlock_seconds=0.01),
    )
