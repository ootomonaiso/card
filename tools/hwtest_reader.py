#!/usr/bin/env python3
"""カードリーダー（RC-S380 / nfcpy）の単体テスト（Raspberry Pi 実機で実行）。

社員証をタッチして IDm（カード固有ID）が読めるかを確認するだけ。
社員証が FeliCa か、RC-S380 + nfcpy で IDm が取れるか（課題 T3 / Q10）の
切り分けに使う。アプリ本体には依存しない。

使い方（Pi のターミナルで）:
  python3 tools/hwtest_reader.py     # タッチするたびに IDm を表示（Ctrl+C で終了）

読めないとき:
  - `lsusb` に "Sony ... RC-S380" が見えるか
  - 権限: うまくいかなければ `sudo python3 tools/hwtest_reader.py` で試す
          （恒久対応は udev ルールで一般ユーザに許可）
  - 競合ドライバ: カーネルの pn533_usb 等がデバイスを掴んでいないか
"""
from __future__ import annotations

import sys
import time


def extract_idm(tag) -> str | None:
    """FeliCa は tag.idm（bytes）。それ以外は identifier を16進で返す。"""
    b = getattr(tag, "idm", None)
    if b is None:
        b = getattr(tag, "identifier", None)
    return b.hex().upper() if b else None


def main() -> int:
    try:
        import nfc
    except Exception as e:
        print("nfcpy を import できません。Raspberry Pi 実機で `pip install nfcpy` を実行してください。")
        print(f"詳細: {e}")
        return 1

    print(f"nfcpy {getattr(nfc, '__version__', '?')} / RC-S380 を開いています…")
    try:
        clf = nfc.ContactlessFrontend("usb")
    except Exception as e:
        print("リーダーを開けません（usb）。lsusb / 権限 / 競合ドライバを確認してください。")
        print(f"詳細: {e}")
        return 1

    print("準備OK。社員証をタッチしてください（Ctrl+C で終了）\n")
    seen: set[str] = set()
    count = 0
    last_idm: str | None = None
    last_at = 0.0
    try:
        while True:
            # on-connect が False を返すと、タグ検出のみで切断する（読み取りはしない）
            tag = clf.connect(rdwr={"on-connect": lambda t: False})
            if tag is None:
                continue
            idm = extract_idm(tag)
            now = time.monotonic()
            if idm and not (idm == last_idm and (now - last_at) < 1.0):  # 簡易デバウンス
                count += 1
                seen.add(idm)
                last_idm, last_at = idm, now
                print(f"  #{count}  IDm={idm}  type={type(tag).__name__}")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print(f"\n終了。読取 {count} 回 / ユニーク {len(seen)} 枚")
        for s in sorted(seen):
            print(f"  - {s}")
        return 0
    finally:
        try:
            clf.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
