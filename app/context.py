"""アプリケーションの依存組み立て（DIコンテナ相当）。

DB接続・リポジトリ・サービス・デバイスを一箇所で生成して束ねる。
テストからは clock や conn を差し替えて構築できる。
"""
from __future__ import annotations

import sqlite3
import threading

from app.config import Config
from app.db import connect, init_db
from app.devices.factory import create_card_reader, create_lock
from app.repository.items import ItemRepository
from app.repository.loans import LoanRepository
from app.repository.members import MemberRepository
from app.services.auth import AuthService
from app.services.clock import Clock
from app.services.loan import LoanService
from app.services.member import MemberService
from app.services.report import ReportService


class AppContext:
    def __init__(
        self,
        cfg: Config,
        conn: sqlite3.Connection,
        clock: Clock | None = None,
        card_reader=None,
        lock=None,
    ) -> None:
        self.cfg = cfg
        self.conn = conn
        self.clock = clock or Clock()
        # 全DBアクセスを直列化するロック（WebUI のマルチスレッド対策）
        self.db_lock = threading.RLock()

        self.member_repo = MemberRepository(conn)
        self.item_repo = ItemRepository(conn)
        self.loan_repo = LoanRepository(conn)

        self.card_reader = card_reader if card_reader is not None else create_card_reader(cfg)
        self.lock = lock if lock is not None else create_lock(cfg)

        self.auth = AuthService(self.member_repo)
        self.loans = LoanService(
            cfg, self.clock, self.member_repo, self.item_repo, self.loan_repo, self.lock
        )
        self.members = MemberService(self.clock, self.member_repo)
        self.reports = ReportService(cfg, self.member_repo, self.item_repo, self.loan_repo)

    @classmethod
    def create(cls, cfg: Config | None = None, **overrides) -> "AppContext":
        cfg = cfg or Config.load()
        conn = overrides.pop("conn", None) or connect(cfg.db_path)
        init_db(conn, cfg.item_name, cfg.item_location)
        return cls(cfg, conn, **overrides)
