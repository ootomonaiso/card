"""エントリポイント。

  python main.py            Webサーバ起動（http://127.0.0.1:8000/）
  python main.py --seed     デモ用メンバーを投入してから起動
  python main.py --init     DBを初期化するだけ
  python main.py --port 80  ポート変更
  python main.py --add-admin --idm <IDm> --name <氏名> --employee-no <番号>
                            管理者を非対話で追加（サーバは起動しない／運用復旧用）

Raspberry Pi 実機では config.json の card_reader/lock を "auto" のままにすれば
RC-S380(nfcpy) と GPIO(gpiozero) を自動選択。Windows 等ではモックで動く。
UI は Pi 上の Chromium をキオスク表示して使う（docs/impl/01_実装ガイド.md 参照）。
"""
from __future__ import annotations

import argparse

from app.config import Config, ConfigError
from app.context import AppContext
from app.log import get_logger, setup_logging
from app.services.member import MemberError


def seed(ctx: AppContext) -> None:
    samples = [
        ("0102030405060708", "100234", "山田 太郎", "user"),
        ("1112131415161718", "100567", "鈴木 花子", "user"),
        ("2122232425262728", "900001", "管理 者一", "admin"),
    ]
    for idm, emp, name, role in samples:
        if ctx.member_repo.find_by_idm(idm) is None:
            ctx.members.register(idm, emp, name, role)
    print("デモメンバーを投入しました")


def main() -> None:
    parser = argparse.ArgumentParser(description="貸出管理システム")
    parser.add_argument("--seed", action="store_true", help="デモ用メンバーを投入")
    parser.add_argument("--init", action="store_true", help="DB初期化のみ")
    parser.add_argument("--config", default=None, help="config.json のパス")
    parser.add_argument("--host", default="127.0.0.1", help="バインドするホスト（既定 localhost）")
    parser.add_argument("--port", type=int, default=8000, help="ポート（既定 8000）")
    parser.add_argument("--allow-remote", action="store_true",
                        help="ループバック以外へのバインドを明示的に許可する（既定は拒否）")
    parser.add_argument("--add-admin", action="store_true",
                        help="管理者を非対話で追加する（--idm --name --employee-no が必須／サーバは起動しない）")
    parser.add_argument("--idm", default=None, help="--add-admin 用：カードのIDm")
    parser.add_argument("--name", default=None, help="--add-admin 用：氏名")
    parser.add_argument("--employee-no", default=None, help="--add-admin 用：社員番号")
    args = parser.parse_args()

    try:
        cfg = Config.load(args.config)
    except ConfigError as e:
        parser.error(str(e))

    setup_logging(cfg)
    log = get_logger("main")
    log.info("起動: item=%s db=%s", cfg.item_name, cfg.db_path)

    ctx = AppContext.create(cfg)

    if args.init:
        print(f"DB を初期化しました: {cfg.db_path}")
        return
    if args.add_admin:
        if not (args.idm and args.name and args.employee_no):
            parser.error("--add-admin には --idm --name --employee-no が必須です")
        try:
            member = ctx.members.register(args.idm, args.employee_no, args.name, "admin")
        except MemberError as e:
            print(f"管理者追加に失敗しました: {e}")
            raise SystemExit(1)
        print(f"管理者を追加しました: {member.name}（member_id={member.member_id}）")
        return
    if args.seed:
        seed(ctx)

    # 管理操作はサーバ全体で単一セッション（per-client 認証/CSRF なし）のため、
    # localhost 以外へ公開すると第三者が管理機能を叩けてしまう。既定で拒否する。
    _LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
    if args.host not in _LOOPBACK_HOSTS and not args.allow_remote:
        parser.error(
            f"host={args.host!r} はループバックではありません。"
            "本システムは per-client 認証/CSRF を持たず localhost 運用が前提です。"
            "ネットワーク公開が本当に必要な場合のみ --allow-remote を併用してください。"
        )
    if args.host not in _LOOPBACK_HOSTS:
        log.warning(
            "ループバック以外へバインドします host=%s: 管理機能が無認証で露出します（--allow-remote 指定）",
            args.host,
        )

    from app.web.server import serve
    serve(ctx, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
