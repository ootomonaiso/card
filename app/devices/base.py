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
