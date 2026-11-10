# ハードウェア単体テスト（tools/）

Raspberry Pi 4 実機で、**ハードが生きているか**だけを確認するスタンドアロン・スクリプト。
アプリ本体（`app/`）には依存しないので、ハードの不具合とソフトの不具合を切り分けられる。

| スクリプト | 何を確認するか | 対応課題 |
|------------|----------------|----------|
| [`hwtest_reader.py`](hwtest_reader.py) | 社員証をタッチして **IDm が読めるか**（RC-S380 / nfcpy） | T3 / Q10 |
| [`hwtest_lock.py`](hwtest_lock.py) | GPIO を数秒 ON にして **解錠 → 施錠するか**（駆動回路 + LE-53） | T2 |

配線は [`docs/diagrams/`](../docs/diagrams/)（`mosfet_driver.svg` / `relay_driver.svg` / `pi4_wiring.svg`）参照。

## 準備（Pi 実機）

```bash
pip install nfcpy gpiozero
```

## カードリーダー

```bash
python3 tools/hwtest_reader.py       # タッチするたび IDm 表示 / Ctrl+C で終了・集計
```

- 複数の社員証をタッチして、別々の IDm が安定して読めれば OK。
- 読めないとき: `lsusb` に RC-S380 が出るか / `sudo` で試す / 競合ドライバ（pn533_usb 等）を確認。

## ロック（解錠）

```bash
python3 tools/hwtest_lock.py                         # GPIO17 を 5秒 ON → OFF を1回
python3 tools/hwtest_lock.py --seconds 3 --count 3   # 3秒×3回（連続通電しないか確認）
python3 tools/hwtest_lock.py --active-low            # LOWで通電する回路のとき
```

- 通電中に「カチッ」と解錠し、OFF で施錠に戻れば OK（LE-53 は無通電で自動施錠）。
- スクリプトは中断（Ctrl+C）や異常終了でも **必ず GPIO を OFF** にして終わる。
- ⚠️ 連続通電するとコイルが約70℃まで発熱する。長時間 ON にしない。

> これらは開発機（Windows 等）では動かない（`nfcpy` / `gpiozero` が無いため）。Pi 実機で実行する。
