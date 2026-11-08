"""モックデバイス（開発機・テスト用）。

- MockCardReader: プログラムから emit() で IDm を発火。UI からは「疑似タッチ」ボタンで使う。
- MockLock: 解錠を記録するだけ（実際のGPIOは叩かない）。発熱/逆起電力の心配なし。
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from app.devices.base import LockError
from app.log import get_logger

_log = get_logger("device")


class MockCardReader:
    def __init__(self) -> None:
        self._on_touch: Callable[[str], None] | None = None

    def start(self, on_touch: Callable[[str], None]) -> None:
        self._on_touch = on_touch

    def stop(self) -> None:
        self._on_touch = None

    def emit(self, idm: str) -> None:
        """疑似カードタッチ。"""
        if self._on_touch is not None:
            self._on_touch(idm)


class MockLock:
    def __init__(self, unlock_seconds: float = 5.0, fail: bool = False) -> None:
        self.unlock_seconds = unlock_seconds
        self.unlock_count = 0
        self.is_energized = False
        # fail=True で解錠失敗（ハード故障）を模擬してテストできる。
        self.fail = fail

    def unlock(self) -> None:
        if self.fail:
            _log.error("[MockLock] 解錠失敗を模擬")
            raise LockError("模擬: 解錠に失敗しました")
        self.unlock_count += 1
        self.is_energized = True
        _log.info("[MockLock] 解錠（通電）… %.2fs", self.unlock_seconds)

        def _off() -> None:
            time.sleep(self.unlock_seconds)
            self.is_energized = False
            _log.info("[MockLock] 施錠（通電OFF）")

        threading.Thread(target=_off, daemon=True).start()
