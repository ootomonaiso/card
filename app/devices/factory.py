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
    """item_id → LockController の LockRegistry を組み立てる。

    cfg.locks が未指定（既定）なら lock_gpio_pin/lock_active_high から単一スロットを
    自動生成し、現行の「全物品で1ロック共有」動作と完全に同じになる（複数ロック対応は
    ソフト設計のみで、config.json 側の変更は不要）。
    """
    from app.devices.base import LockRegistry

    mode = cfg.lock
    if mode == "auto":
        mode = "real" if _is_raspberry_pi() else "mock"

    slots = cfg.locks or [{
        "slot": "default",
        "gpio_pin": cfg.lock_gpio_pin,
        "active_high": cfg.lock_active_high,
        "item_ids": [],
    }]

    pin_to_controller: dict[int, object] = {}
    controllers_by_slot: dict[str, object] = {}
    item_to_slot: dict[int, str] = {}
    default_slot: str | None = None

    for slot_cfg in slots:
        slot = slot_cfg["slot"]
        pin = slot_cfg["gpio_pin"]
        active_high = slot_cfg.get("active_high", True)
        item_ids = slot_cfg.get("item_ids", [])

        if pin not in pin_to_controller:
            if mode == "real":
                from app.devices.gpio_lock import GpioLock
                pin_to_controller[pin] = GpioLock(
                    pin=pin,
                    unlock_seconds=cfg.unlock_seconds,
                    active_high=active_high,
                    min_reunlock_seconds=cfg.min_reunlock_seconds,
                )
            else:
                from app.devices.mock import MockLock
                pin_to_controller[pin] = MockLock(unlock_seconds=cfg.unlock_seconds)

        controllers_by_slot[slot] = pin_to_controller[pin]
        for item_id in item_ids:
            item_to_slot[item_id] = slot
        if not item_ids and default_slot is None:
            default_slot = slot

    if default_slot is None:
        default_slot = slots[0]["slot"]

    return LockRegistry(controllers_by_slot, item_to_slot, default_slot)


def create_lock_sensor(cfg: Config, notifier=None):
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
            fail_streak_threshold=cfg.cam_switch_fail_streak_threshold,
            notifier=notifier,
        )
    from app.devices.mock import MockCamSwitch
    return MockCamSwitch()
