#!/usr/bin/env python3
"""ロック駆動回路の単体テスト（Raspberry Pi 実機で実行）。

GPIO を指定秒だけ ON にして解錠 → OFF で施錠、を数回くり返すだけの確認用。
MOSFET/リレー ＋ ソレノイド LE-53（DC5V/2W・通電時解錠）の配線確認に使う。
アプリ本体には依存しない（ハード単体の切り分け用）。

使い方（Pi のターミナルで）:
  python3 tools/hwtest_lock.py                      # GPIO17 を 5秒 ON → OFF を1回
  python3 tools/hwtest_lock.py --seconds 3 --count 3 --interval 4
  python3 tools/hwtest_lock.py --pin 17 --active-low   # LOWで通電する回路のとき

確認ポイント:
  - 通電中に「カチッ」と解錠し、扉／ラッチが開くか
  - OFF で施錠に戻るか（LE-53 は無通電で自動施錠）
  - 発熱: 連続通電でコイルは約70℃まで上がる。本スクリプトは必ず OFF に戻す。
"""
from __future__ import annotations

import argparse
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser(description="ロック駆動回路テスト（GPIOパルス）")
    ap.add_argument("--pin", type=int, default=17, help="解錠用GPIO（BCM番号, 既定17）")
    ap.add_argument("--seconds", type=float, default=5.0, help="1回の通電（解錠）秒数")
    ap.add_argument("--count", type=int, default=1, help="解錠回数")
    ap.add_argument("--interval", type=float, default=3.0, help="解錠と解錠の間隔（秒）")
    ap.add_argument("--active-low", action="store_true",
                    help="LOWで通電する駆動回路のとき指定（既定はHIGHで通電）")
    args = ap.parse_args()

    try:
        from gpiozero import DigitalOutputDevice
    except Exception as e:  # 開発機や未インストール時
        print("gpiozero を import できません。Raspberry Pi 実機で `pip install gpiozero` を実行してください。")
        print(f"詳細: {e}")
        return 1

    active_high = not args.active_low
    print(f"GPIO{args.pin} / active_{'high' if active_high else 'low'} / "
          f"{args.seconds}s 通電 × {args.count}回（間隔 {args.interval}s）")
    print("※ 通電中に解錠音がするか／扉が開くかを確認してください。\n")

    dev = DigitalOutputDevice(args.pin, active_high=active_high, initial_value=False)
    try:
        for i in range(1, args.count + 1):
            print(f"[{i}/{args.count}] 通電（解錠）… {args.seconds}s", flush=True)
            dev.on()
            time.sleep(args.seconds)
            dev.off()
            print(f"[{i}/{args.count}] OFF（施錠）")
            if i < args.count:
                time.sleep(args.interval)
        print("\n完了。")
        return 0
    except KeyboardInterrupt:
        print("\n中断しました。")
        return 130
    finally:
        # 何があっても通電を止める（発熱・焼損防止）
        try:
            dev.off()
            dev.close()
            print("GPIO を OFF にして解放しました。")
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
