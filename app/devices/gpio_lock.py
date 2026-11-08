"""実機ソレノイドロック制御（GPIO / gpiozero）。Raspberry Pi 実機でのみ使用。

09 ハードウェア設計書 / FR-05 / NFR-08：
- 通電時解錠（LE-53）。GPIO を数秒だけ ON にして解錠し、その後必ず OFF へ。
- 連続通電しない（発熱・焼損防止）。最小再解錠間隔を設けて連打を抑止。
"""
from __future__ import annotations

import threading
import time


class GpioLock:
    def __init__(
        self,
        pin: int = 17,
        unlock_seconds: float = 5.0,
        active_high: bool = True,
        min_reunlock_seconds: float = 3.0,
    ) -> None:
        from gpiozero import DigitalOutputDevice  # Pi 実機のみ

        self.unlock_seconds = unlock_seconds
        self.min_reunlock = min_reunlock_seconds
        # active_high=True: HIGH で通電（駆動回路の論理に合わせて設定）
        self._dev = DigitalOutputDevice(
            pin, active_high=active_high, initial_value=False
        )
        self._lock = threading.Lock()
        self._busy = False
        self._last_unlock = 0.0

    def unlock(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._busy:
                return  # 解錠中は再入しない
            if (now - self._last_unlock) < self.min_reunlock:
                return  # 連打抑止
            self._busy = True
            self._last_unlock = now

        def _pulse() -> None:
            try:
                self._dev.on()          # 通電 → 解錠
                time.sleep(self.unlock_seconds)
            finally:
                self._dev.off()         # 必ず OFF（通電停止）
                with self._lock:
                    self._busy = False

        threading.Thread(target=_pulse, daemon=True).start()

    def close(self) -> None:
        try:
            self._dev.off()
            self._dev.close()
        except Exception:
            pass
