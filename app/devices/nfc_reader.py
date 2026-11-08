"""実機カードリーダー（RC-S380 / nfcpy）。Raspberry Pi 実機でのみ使用。

CON-4：カード内部データは読まず、IDm（カード固有ID）のみを使う。
別スレッドでポーリングし、同一カードの連続検出は一定間隔で抑止する。
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class NfcCardReader:
    def __init__(self, debounce_seconds: float = 1.5) -> None:
        self._on_touch: Callable[[str], None] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._debounce = debounce_seconds
        self._last_idm: str | None = None
        self._last_at = 0.0

    def start(self, on_touch: Callable[[str], None]) -> None:
        self._on_touch = on_touch
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        import nfc  # nfcpy。実機のみ。

        with nfc.ContactlessFrontend("usb") as clf:
            while not self._stop.is_set():
                tag = clf.connect(
                    rdwr={"on-connect": lambda t: False},
                    terminate=lambda: self._stop.is_set(),
                )
                if tag is None:
                    continue
                idm = self._extract_idm(tag)
                if idm:
                    self._fire(idm)
                time.sleep(0.2)

    @staticmethod
    def _extract_idm(tag) -> str | None:
        # FeliCa は tag.idm（bytes）。それ以外は識別子を16進で。
        idm_bytes = getattr(tag, "idm", None)
        if idm_bytes is None:
            idm_bytes = getattr(tag, "identifier", None)
        if idm_bytes is None:
            return None
        return idm_bytes.hex().upper()

    def _fire(self, idm: str) -> None:
        now = time.monotonic()
        if idm == self._last_idm and (now - self._last_at) < self._debounce:
            return
        self._last_idm = idm
        self._last_at = now
        if self._on_touch is not None:
            self._on_touch(idm)
