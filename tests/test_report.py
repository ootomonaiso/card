"""貸借ログCSV出力（FR-07 / NFR-12）の単体テスト。"""
from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.services.clock import FixedClock
from app.services.report import ExportPathError, validate_export_path
from tests.helpers import make_ctx


class CsvTest(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx(FixedClock(datetime(2026, 11, 8, 9, 30, 0)))
        self.clock = self.ctx.clock
        self.item_id = self.ctx.item_repo.default_item().item_id
        self.taro = self.ctx.members.register("AA11", "100234", "山田 太郎", "user")

    def test_csv_export(self):
        # FR-07：帳票同項目・書式でCSV出力
        loan = self.ctx.loans.borrow(self.taro, self.item_id, 60)
        self.clock.set(datetime(2026, 11, 8, 10, 12, 0))
        self.ctx.loans.return_loan(loan)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "log.csv"
            n = self.ctx.reports.export_csv(
                datetime(2026, 11, 1).date(), datetime(2026, 11, 30).date(), out
            )
            self.assertEqual(n, 1)
            with out.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        self.assertEqual(
            rows[0],
            ["氏名", "社員番号", "物品名", "貸出日時", "貸出時間", "返却予定", "返却日時"],
        )
        self.assertEqual(rows[1][0], "山田 太郎")
        self.assertEqual(rows[1][3], "2026/11/08 09:30")
        self.assertEqual(rows[1][4], "60分")
        self.assertEqual(rows[1][5], "2026/11/08 10:30")
        self.assertEqual(rows[1][6], "2026/11/08 10:12")

    def test_csv_injection_neutralized(self):
        # 氏名が数式開始文字なら ' を前置して無害化する（CSVインジェクション対策）
        evil = self.ctx.members.register("CC33", "100888", "=cmd|'/c calc'!A1", "user")
        self.ctx.loans.borrow(evil, self.item_id, 60)
        rows = self.ctx.reports.build_rows(
            datetime(2026, 11, 1).date(), datetime(2026, 11, 30).date()
        )
        self.assertTrue(rows[0][0].startswith("'="))

    def test_csv_has_distinct_item_names(self):
        # 複数物品でも、各行に正しい物品名が出る（物品名列 = index 2）
        item2 = self.ctx.item_svc.add_item("予備カメラ", "保管庫B")
        self.ctx.loans.borrow(self.taro, self.item_id, 60)
        self.ctx.loans.borrow(self.taro, item2, 30)
        rows = self.ctx.reports.build_rows(
            datetime(2026, 11, 1).date(), datetime(2026, 11, 30).date()
        )
        names = {r[2] for r in rows}
        self.assertEqual(names, {"セキュアカメラ", "予備カメラ"})

    def test_csv_excludes_out_of_range(self):
        # 期間外の貸出は出力されない
        self.ctx.loans.borrow(self.taro, self.item_id, 60)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "log.csv"
            n = self.ctx.reports.export_csv(
                datetime(2026, 12, 1).date(), datetime(2026, 12, 31).date(), out
            )
        self.assertEqual(n, 0)


class ExportPathTest(unittest.TestCase):
    """CSV出力先の封じ込め（任意パス書き込み対策）。"""

    def test_allows_csv_in_allowed_dir(self):
        with tempfile.TemporaryDirectory() as d:
            out = validate_export_path("log.csv", [d, "."], "lending.sqlite3")
            # d 配下に解決されるのは相対 "." 側ではなく許可ディレクトリ経由ではないが、
            # カレント配下の log.csv は "." 許可で通る。
            self.assertTrue(str(out).endswith("log.csv"))

    def test_allows_absolute_path_under_allowed_dir(self):
        with tempfile.TemporaryDirectory() as d:
            target = str(Path(d) / "lending_log.csv")
            out = validate_export_path(target, [d], "lending.sqlite3")
            self.assertEqual(out, Path(target).resolve())

    def test_rejects_non_csv_extension(self):
        with self.assertRaises(ExportPathError):
            validate_export_path("lending.service", ["."], "lending.sqlite3")

    def test_rejects_db_overwrite(self):
        with self.assertRaises(ExportPathError):
            # DB 名が .csv でも上書きは拒否
            validate_export_path("x.csv", ["."], "x.csv")

    def test_rejects_traversal_outside_allowed_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            # 許可は d のみ。.. で外へ出るパスは弾かれる。
            with self.assertRaises(ExportPathError):
                validate_export_path(str(Path(d) / ".." / "evil.csv"), [d], "lending.sqlite3")

    def test_rejects_path_outside_allowed_dirs(self):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as other:
            with self.assertRaises(ExportPathError):
                validate_export_path(str(Path(other) / "x.csv"), [allowed], "lending.sqlite3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
