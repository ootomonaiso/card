"""main.py の CLI（--add-admin）のテスト。鶏卵問題の運用復旧用導線。"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = ROOT / "main.py"


class AddAdminCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        self.db_path = tmp_path / "test.sqlite3"
        self.config_path = tmp_path / "config.json"
        self.config_path.write_text(
            json.dumps({
                "db_path": str(self.db_path),
                "log_dir": str(tmp_path / "logs"),
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra_args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(MAIN_PY), "--config", str(self.config_path), *extra_args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )

    def test_add_admin_creates_admin_without_starting_server(self):
        result = self._run("--add-admin", "--idm", "CLI0001", "--name", "復旧 管理者",
                            "--employee-no", "900999")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("管理者を追加しました", result.stdout)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT role, is_active, name FROM MEMBER WHERE card_idm = ?", ("CLI0001",)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "admin")
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], "復旧 管理者")

    def test_add_admin_works_even_when_admin_already_exists(self):
        # 運用復旧用：既に管理者がいても追加できる（セットアップ画面の制限は受けない）
        self._run("--add-admin", "--idm", "CLI0001", "--name", "管理 一", "--employee-no", "900001")
        result = self._run("--add-admin", "--idm", "CLI0002", "--name", "管理 二", "--employee-no", "900002")
        self.assertEqual(result.returncode, 0, result.stderr)

        conn = sqlite3.connect(self.db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM MEMBER WHERE role='admin' AND is_active=1"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)

    def test_add_admin_requires_all_fields(self):
        result = self._run("--add-admin", "--idm", "CLI0001")
        self.assertNotEqual(result.returncode, 0)

    def test_add_admin_rejects_duplicate_idm(self):
        self._run("--add-admin", "--idm", "CLI0001", "--name", "管理 一", "--employee-no", "900001")
        result = self._run("--add-admin", "--idm", "CLI0001", "--name", "管理 二", "--employee-no", "900002")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("失敗", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
