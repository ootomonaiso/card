"""実機の施錠検知センサ（LE-53 カムスイッチ / gpiozero）。Raspberry Pi 実機でのみ使用。

09 ハードウェア設計書 §5-1：
- カムスイッチは「施錠時 ON（接点が閉じる）」。茶→GPIO 入力、黒→GND の想定。
- Pi 内部プルアップを有効化し、施錠（接点閉）で入力 LOW、解錠で HIGH。
- ソフトでデバウンス（開閉の過渡でバタつくため）。

※ケーブル色・接点の NO/NC は現物からの推定のため、実機ではテスターで確認すること。
"""
from __future__ import annotations

from app.log import get_logger

_log = get_logger("device")


class GpioCamSwitch:
    def __init__(self, pin: int = 27, active_low: bool = True, bounce_ms: int = 50) -> None:
        from gpiozero import Button  # Pi 実機のみ

        # active_low=True: 施錠で接点が GND に落ちる配線（内部プルアップで待受 HIGH）。
        # gpiozero の Button は「押された（is_pressed）」= pull_up 時に入力 LOW。
        # すなわち施錠（接点閉）→ is_pressed True を「施錠」に対応させる。
        self._btn = Button(
            pin, pull_up=active_low, bounce_time=(bounce_ms / 1000.0 if bounce_ms else None)
        )
        _log.info("カムスイッチ入力を初期化 pin=%s active_low=%s", pin, active_low)

    def is_locked(self) -> bool | None:
        try:
            return bool(self._btn.is_pressed)
        except Exception as e:  # 読み取り異常は不明扱い（判断には使わせない）
            _log.error("カムスイッチの読み取りに失敗: %s", e)
            return None

    def close(self) -> None:
        try:
            self._btn.close()
        except Exception:
            pass
