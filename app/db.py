"""SQLite 接続とスキーマ初期化。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.log import get_logger

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
_log = get_logger("db")


def connect(db_path: str) -> sqlite3.Connection:
    # WebUI はリクエストごとに別スレッドで処理されるため、接続をスレッド間で共有する。
    # 同時アクセスは AppContext.db_lock で直列化する（単一キオスク・低並行の前提）。
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL：読み書きの衝突に強く、クラッシュ耐性も高い（:memory: では無視される）。
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection, item_name: str, item_location: str) -> None:
    """スキーマを作成し、ITEM が空のときだけ config の物品を初期シードとして投入する。

    ITEM テーブルが物品マスタの実体（複数物品対応）。config の item_name/item_location は
    「空DBの初回起動時に入れる最初の1件」と、物品が未登録になった場合のフォールバックに
    格下げされており、以後の物品の増減は物品管理画面（ItemService）で行う。
    """
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # 起動時にDBの健全性を軽く点検（破損していれば運用ログに警告）。
    row = conn.execute("PRAGMA quick_check").fetchone()
    if row is not None and row[0] != "ok":
        _log.error("DB整合性チェックに失敗: %s", row[0])
    row = conn.execute("SELECT COUNT(*) AS c FROM ITEM").fetchone()
    if row["c"] == 0:
        # ITEM が空のときだけ初期物品を1件投入（既存の物品群には触れない）。
        conn.execute(
            "INSERT INTO ITEM(name, location, is_active) VALUES(?, ?, 1)",
            (item_name, item_location),
        )
    conn.commit()
