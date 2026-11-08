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
  duration_min INTEGER NOT NULL CHECK(duration_min IN (15,30,60,120,240,480)),
  due_at       TEXT NOT NULL,
  returned_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_loan_active ON LOAN(item_id, returned_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_member_idm ON MEMBER(card_idm);
