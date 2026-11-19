"""時刻同期の状態確認（P7 / NFR-03 の補助）。

延滞判定は OS 時刻に依存するため、管理者が「時刻が信頼できるか」を一目で
確認できるようにする。Raspberry Pi OS（systemd-timesyncd）を前提に timedatectl を
best-effort で呼ぶだけの薄いヘルパ。追加依存は入れない（標準ライブラリのみ）。
"""
from __future__ import annotations

import subprocess

from app.log import get_logger

_log = get_logger("timesync")


def ntp_status() -> str:
    """NTP 同期状態を返す。

    - "synced":   OS が時刻同期済み（NTPSynchronized=yes）
    - "unsynced": 同期していない
    - "unknown":  判定できない（非 Linux / timedatectl 不在 / 実行失敗）
    """
    try:
        out = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=2.0, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        # Windows 開発機や timedatectl が無い環境ではここに来る。障害ではないので info。
        _log.info("時刻同期状態を取得できませんでした: %s", e)
        return "unknown"
    value = (out.stdout or "").strip().lower()
    if value in ("yes", "true", "1"):
        return "synced"
    if value in ("no", "false", "0"):
        return "unsynced"
    return "unknown"
