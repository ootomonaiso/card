"""プラットフォームに応じてデバイスを生成する。

config の card_reader / lock が "auto" のとき：
- Raspberry Pi（かつ対応ライブラリ有り）→ 実機デバイス
- それ以外（Windows 開発機等）→ モック
明示的に "mock" / "real" を指定すればそれに従う。
"""
from __future__ import annotations

from app.config import Config


def _is_raspberry_pi() -> bool:
    try:
        model = open("/proc/device-tree/model", "rb").read().decode(errors="ignore")
        return "Raspberry Pi" in model
    except OSError:
        return False


def create_card_reader(cfg: Config):
    mode = cfg.card_reader
    if mode == "auto":
        mode = "real" if _is_raspberry_pi() else "mock"
    if mode == "real":
        from app.devices.nfc_reader import NfcCardReader
        return NfcCardReader()
    from app.devices.mock import MockCardReader
    return MockCardReader()


def create_lock(cfg: Config):
    mode = cfg.lock
    if mode == "auto":
        mode = "real" if _is_raspberry_pi() else "mock"
    if mode == "real":
        from app.devices.gpio_lock import GpioLock
        return GpioLock(
            pin=cfg.lock_gpio_pin,
            unlock_seconds=cfg.unlock_seconds,
            active_high=cfg.lock_active_high,
            min_reunlock_seconds=cfg.min_reunlock_seconds,
        )
    from app.devices.mock import MockLock
    return MockLock(unlock_seconds=cfg.unlock_seconds)


def create_lock_sensor(cfg: Config):
    """施錠検知センサ（LE-53 カムスイッチ）。既定は "off"（未使用＝常に状態不明）。"""
    mode = cfg.cam_switch
    if mode == "off":
        from app.devices.mock import NullLockSensor
        return NullLockSensor()
    if mode == "auto":
        mode = "real" if _is_raspberry_pi() else "mock"
    if mode == "real":
        from app.devices.cam_switch import GpioCamSwitch
        return GpioCamSwitch(
            pin=cfg.cam_switch_gpio_pin,
            active_low=cfg.cam_switch_active_low,
            bounce_ms=cfg.cam_switch_bounce_ms,
        )
    from app.devices.mock import MockCamSwitch
    return MockCamSwitch()
