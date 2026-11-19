"""アプリケーションの依存組み立て（DIコンテナ相当）。

DB接続・リポジトリ・サービス・デバイスを一箇所で生成して束ねる。
テストからは clock や conn を差し替えて構築できる。
"""
from __future__ import annotations

import sqlite3
import threading

from app.config import Config
from app.db import connect, init_db
from app.devices.base import LockRegistry
from app.devices.factory import create_card_reader, create_lock, create_lock_sensor
from app.repository.items import ItemRepository
from app.repository.loans import LoanRepository
from app.repository.members import MemberRepository
from app.services.auth import AuthService
from app.services.clock import Clock
from app.services.item import ItemService
from app.services.loan import LoanService
from app.services.member import MemberService
from app.services.notify import TeamsNotifier
from app.services.report import ReportService


class AppContext:
    def __init__(
        self,
        cfg: Config,
        conn: sqlite3.Connection,
        clock: Clock | None = None,
        card_reader=None,
        lock=None,
        lock_sensor=None,
        notifier: TeamsNotifier | None = None,
    ) -> None:
        self.cfg = cfg
        self.conn = conn
        self.clock = clock or Clock()
        # 全DBアクセスを直列化するロック（WebUI のマルチスレッド対策）
        self.db_lock = threading.RLock()

        self.member_repo = MemberRepository(conn)
        self.item_repo = ItemRepository(conn)
        self.loan_repo = LoanRepository(conn)

        self.notifier = notifier if notifier is not None else TeamsNotifier(
            cfg.teams_webhook_url, cfg.teams_notify_overdue,
            cfg.teams_notify_errors, cfg.teams_notify_routine,
        )

        self.card_reader = card_reader if card_reader is not None else create_card_reader(cfg)
        lock_obj = lock if lock is not None else create_lock(cfg)
        # 単体の LockController（テスト等から直接渡される場合）は単一スロットの
        # LockRegistry に包み、LoanService からは常に for_item() で引けるようにする。
        self.lock: LockRegistry = (
            lock_obj if isinstance(lock_obj, LockRegistry) else LockRegistry.single(lock_obj)
        )
        self.lock_sensor = (
            lock_sensor if lock_sensor is not None else create_lock_sensor(cfg, self.notifier)
        )

        self.auth = AuthService(self.member_repo)
        self.loans = LoanService(
            cfg, self.clock, self.member_repo, self.item_repo, self.loan_repo, self.lock,
            self.notifier,
        )
        self.members = MemberService(self.clock, self.member_repo)
        self.item_svc = ItemService(self.item_repo, self.loan_repo)
        self.reports = ReportService(cfg, self.member_repo, self.item_repo, self.loan_repo)

    @classmethod
    def create(cls, cfg: Config | None = None, **overrides) -> "AppContext":
        cfg = cfg or Config.load()
        conn = overrides.pop("conn", None) or connect(cfg.db_path)
        init_db(conn, cfg.item_name, cfg.item_location)
        return cls(cfg, conn, **overrides)
