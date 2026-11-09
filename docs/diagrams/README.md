# 図面（diagrams）

| 種別 | ソース | 備考 |
|------|--------|------|
| UML図（業務フロー・ユースケース・ER・シーケンス・状態遷移・画面遷移） | 各設計書 `docs/*.md` 内の **Mermaid** | GitHub 上でそのまま描画される。これが正。 |
| 回路図・配線図 | 本フォルダの **SVG** | 下記 3 点。Mermaid では描けないため手描き SVG。 |

## 回路図・配線図（SVG）

- [`pi4_wiring.svg`](pi4_wiring.svg) … 接続構成図（配線概要・使用GPIOピン） → 09 §2
- [`mosfet_driver.svg`](mosfet_driver.svg) … ロック駆動回路（MOSFET ローサイド方式・**推奨**） → 09 §4-1
- [`relay_driver.svg`](relay_driver.svg) … ロック駆動回路（リレー方式） → 09 §4-2

SVG は素の XML なので、テキストエディタや Inkscape 等でそのまま編集できる。

## 非推奨

`全図面.drawio` と `gen_drawio.py` は旧エクスポート（draw.io への手置きレイアウト書き出し）で、**非推奨**。
UML は各ドキュメントの Mermaid、回路図は本フォルダの SVG に移行済み。段階的に削除予定。
