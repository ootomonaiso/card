-- セキュアカメラ貸出システム スキーマ（06_データベース設計書 準拠）
-- SQLite

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS MEMBER (
  member_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  card_idm    TEXT NOT NULL UNIQUE,
  employee_no TEXT NOT NULL,
  name        TEXT NOT NULL,
  role        TEXT NOT NULL CHECK(role IN ('user','admin')),
  is_active   INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ITEM (
  item_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  name      TEXT NOT NULL,
  location  TEXT,
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS LOAN (
  loan_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id    INTEGER NOT NULL REFERENCES MEMBER(member_id),
  item_id      INTEGER NOT NULL REFERENCES ITEM(item_id),
  borrowed_at  TEXT NOT NULL,
  -- 貸出時間の選択肢は config.duration_choices_min で管理する（二重管理を避け、
  -- ここでは正値のみを保証）。妥当性はサービス層が設定値と照合して担保する。
  duration_min INTEGER NOT NULL CHECK(duration_min > 0),
  due_at       TEXT NOT NULL,
  returned_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_loan_active ON LOAN(item_id, returned_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_member_idm ON MEMBER(card_idm);

-- 1つの物品につき未返却（貸出中）は同時に1件まで、をDBレベルで保証する（CON-3）。
-- アプリ側のチェックが破られても二重貸出を物理的に防ぐ安全網。
CREATE UNIQUE INDEX IF NOT EXISTS idx_loan_one_open
  ON LOAN(item_id) WHERE returned_at IS NULL;
