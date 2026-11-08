"""貸借ログCSV出力（FR-07 / NFR-12）。帳票と同項目・同書式。

CSV列（06 データベース設計書 §5 暫定レイアウト）:
  氏名, 社員番号, 物品名, 貸出日時, 貸出時間, 返却予定, 返却日時
日時書式: config.csv_datetime_format（既定 YYYY/MM/DD hh:mm）
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time
from pathlib import Path

from app.config import Config
from app.repository.items import ItemRepository
from app.repository.loans import LoanRepository
from app.repository.members import MemberRepository
from app.services.clock import from_iso, to_iso

CSV_HEADER = ["氏名", "社員番号", "物品名", "貸出日時", "貸出時間", "返却予定", "返却日時"]

# CSVインジェクション（表計算ソフトが先頭文字を数式と解釈する）対策の先頭文字。
_CSV_RISKY_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Excel 等の数式解釈を防ぐため、危険な先頭文字なら ' を前置する。"""
    if value and value[0] in _CSV_RISKY_PREFIXES:
        return "'" + value
    return value


class ReportService:
    def __init__(
        self,
        cfg: Config,
        members: MemberRepository,
        items: ItemRepository,
        loans: LoanRepository,
    ) -> None:
        self.cfg = cfg
        self.members = members
        self.items = items
        self.loans = loans

    def _fmt(self, iso: str | None) -> str:
        if not iso:
            return ""
        return from_iso(iso).strftime(self.cfg.csv_datetime_format)

    def _fmt_duration(self, minutes: int) -> str:
        return f"{minutes}分"

    def build_rows(self, start: date, end: date) -> list[list[str]]:
        start_iso = to_iso(datetime.combine(start, time.min))
        end_iso = to_iso(datetime.combine(end, time.max))
        loans = self.loans.list_borrowed_between(start_iso, end_iso)
        item_cache: dict[int, str] = {}
        member_cache: dict[int, tuple[str, str]] = {}
        rows: list[list[str]] = []
        for ln in loans:
            if ln.member_id not in member_cache:
                m = self.members.get(ln.member_id)
                member_cache[ln.member_id] = (m.name, m.employee_no) if m else ("", "")
            if ln.item_id not in item_cache:
                it = self.items.get(ln.item_id)
                item_cache[ln.item_id] = it.name if it else ""
            name, emp = member_cache[ln.member_id]
            # 自由入力の列（氏名・社員番号・物品名）は数式解釈対策を施す。
            # 日時・貸出時間はシステム生成で先頭が数字/記号固定のため不要。
            rows.append([
                _csv_safe(name),
                _csv_safe(emp),
                _csv_safe(item_cache[ln.item_id]),
                self._fmt(ln.borrowed_at),
                self._fmt_duration(ln.duration_min),
                self._fmt(ln.due_at),
                self._fmt(ln.returned_at),
            ])
        return rows

    def export_csv(self, start: date, end: date, out_path: str | Path) -> int:
        """CSV を書き出し、出力行数を返す。"""
        rows = self.build_rows(start, end)
        out_path = Path(out_path)
        with out_path.open("w", encoding=self.cfg.csv_encoding, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)
            writer.writerows(rows)
        return len(rows)
