"""エントリポイント。

  python main.py            Webサーバ起動（http://127.0.0.1:8000/）
  python main.py --seed     デモ用メンバーを投入してから起動
  python main.py --init     DBを初期化するだけ
  python main.py --port 80  ポート変更

Raspberry Pi 実機では config.json の card_reader/lock を "auto" のままにすれば
RC-S380(nfcpy) と GPIO(gpiozero) を自動選択。Windows 等ではモックで動く。
UI は Pi 上の Chromium をキオスク表示して使う（docs/impl/01_実装ガイド.md 参照）。
"""
from __future__ import annotations

import argparse

from app.config import Config
from app.context import AppContext


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
    parser = argparse.ArgumentParser(description="セキュアカメラ貸出システム")
    parser.add_argument("--seed", action="store_true", help="デモ用メンバーを投入")
    parser.add_argument("--init", action="store_true", help="DB初期化のみ")
    parser.add_argument("--config", default=None, help="config.json のパス")
    parser.add_argument("--host", default="127.0.0.1", help="バインドするホスト（既定 localhost）")
    parser.add_argument("--port", type=int, default=8000, help="ポート（既定 8000）")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    ctx = AppContext.create(cfg)

    if args.init:
        print(f"DB を初期化しました: {cfg.db_path}")
        return
    if args.seed:
        seed(ctx)

    from app.web.server import serve
    serve(ctx, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
