"""SQLite 接続とスキーマ初期化。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def connect(db_path: str) -> sqlite3.Connection:
    # WebUI はリクエストごとに別スレッドで処理されるため、接続をスレッド間で共有する。
    # 同時アクセスは AppContext.db_lock で直列化する（単一キオスク・低並行の前提）。
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection, item_name: str, item_location: str) -> None:
    """スキーマを作成し、物品（カメラ1件）が無ければ投入する。"""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    row = conn.execute("SELECT COUNT(*) AS c FROM ITEM").fetchone()
    if row["c"] == 0:
        conn.execute(
            "INSERT INTO ITEM(name, location, is_active) VALUES(?, ?, 1)",
            (item_name, item_location),
        )
    conn.commit()
