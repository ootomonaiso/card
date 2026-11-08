"""アプリログ（運用ログ）と監査ログの設定。

- 運用ログ  logger "card"        → logs/app.log  ＋ コンソール
    起動・デバイス状態・例外・警告など、障害調査に使う情報。
- 監査ログ  logger "card.audit"  → logs/audit.log
    「誰がいつ何をしたか」の業務記録（貸出/返却/管理操作/認証）。
    運用ログとは別ファイルに分け、propagate=False で混在を防ぐ。

どちらも UTF-8・日次相当のサイズローテーション。未設定（setup_logging 未呼出）
でもハンドラが無いだけで、getLogger したコードはそのまま動く（テストでは無音）。
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from app.config import Config

APP_LOGGER = "card"
AUDIT_LOGGER = "card.audit"

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def setup_logging(cfg: Config) -> None:
    """設定に従ってアプリログ・監査ログのハンドラを構成する（冪等）。"""
    global _configured
    if _configured:
        return

    log_dir = Path(cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    fmt = logging.Formatter(_FORMAT)

    def _rotating(filename: str) -> logging.Handler:
        h = logging.handlers.RotatingFileHandler(
            log_dir / filename,
            maxBytes=cfg.log_max_bytes,
            backupCount=cfg.log_backup_count,
            encoding="utf-8",
        )
        h.setFormatter(fmt)
        return h

    # 運用ログ: ファイル＋コンソール（Windows でも文字化けしないよう UTF-8）
    app_log = logging.getLogger(APP_LOGGER)
    app_log.setLevel(level)
    app_log.handlers.clear()
    app_log.addHandler(_rotating("app.log"))
    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(fmt)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    app_log.addHandler(console)

    # 監査ログ: 専用ファイル（運用ログへは流さない）
    audit_log = logging.getLogger(AUDIT_LOGGER)
    audit_log.setLevel(logging.INFO)
    audit_log.handlers.clear()
    audit_log.addHandler(_rotating("audit.log"))
    audit_log.propagate = False

    _configured = True
    app_log.info("ログ初期化: dir=%s level=%s", log_dir.resolve(), cfg.log_level)


def get_logger(area: str) -> logging.Logger:
    """運用ログ用の子ロガー（例: get_logger("loan") → "card.loan"）。"""
    return logging.getLogger(f"{APP_LOGGER}.{area}")


def audit() -> logging.Logger:
    """監査ログ用ロガー。"""
    return logging.getLogger(AUDIT_LOGGER)
