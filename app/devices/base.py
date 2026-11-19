"""デバイス層の抽象インタフェース（05 システム設計書 レイヤ構成）。

カード読取・解錠制御を抽象化し、実機（nfcpy / gpiozero）とモックを差し替え可能にする。
"""
from __future__ import annotations

from typing import Callable, Protocol


class LockError(Exception):
    """解錠ハードウェアの操作に失敗したときに送出する（GPIO 例外など）。"""


class CardReader(Protocol):
    """社員証リーダー。IDm を読み取り、タッチイベントを通知する。"""

    def start(self, on_touch: Callable[[str], None]) -> None:
        """読取を開始。カードタッチ時に on_touch(idm) を呼ぶ。"""
        ...

    def stop(self) -> None:
        """読取を停止し資源を解放する。"""
        ...


class LockController(Protocol):
    """ソレノイドロック制御（通電時解錠：09 ハードウェア設計書）。"""

    def unlock(self) -> None:
        """設定秒数だけ解錠（通電）し、その後必ず施錠（OFF）に戻す。

        解錠の起動（通電開始）に失敗した場合は LockError を送出する。
        施錠への復帰は内部で非同期に行う。
        """
        ...


class LockRegistry:
    """item_id → LockController のマッピング（複数ロック対応、ソフト設計のみ）。

    現行ハードは1チャンネルのみだが、将来ロッカーを増設して物品ごとに錠を分ける場合に
    備え、item_id から対応する LockController を引けるようにしておく。item_ids を
    指定しないスロットは「どの item_ids にも明示的に紐づかない物品」のデフォルト受け皿。
    """

    def __init__(
        self,
        controllers_by_slot: dict[str, "LockController"],
        item_to_slot: dict[int, str],
        default_slot: str,
    ) -> None:
        self._controllers = controllers_by_slot
        self._item_to_slot = item_to_slot
        self._default_slot = default_slot

    @classmethod
    def single(cls, lock: "LockController", slot: str = "default") -> "LockRegistry":
        """単一ロックのみの構成（現行ハード・既存テストの既定）を素早く組み立てる。"""
        return cls({slot: lock}, {}, slot)

    def for_item(self, item_id: int) -> "LockController":
        slot = self._item_to_slot.get(item_id, self._default_slot)
        return self._controllers[slot]

    def close(self) -> None:
        for ctl in set(self._controllers.values()):
            close = getattr(ctl, "close", None)
            if callable(close):
                close()


class LockSensor(Protocol):
    """施錠検知センサ（LE-53 のカムスイッチ：09 §5-1）。

    カムスイッチは「施錠時 ON」。実機は GPIO 入力（プルアップ）で読む。
    """

    def is_locked(self) -> bool | None:
        """施錠されていれば True / 解錠（未施錠）なら False。

        センサ未接続・無効時は None（＝状態不明。呼び出し側は判断に使わない）。
        """
        ...

    def close(self) -> None:
        """GPIO 等の資源を解放する。"""
        ...
