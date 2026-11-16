# 実装ドキュメント

貸出管理システム（旧称: セキュアカメラ貸出システム）の**実装**に関する資料です。
**設計**（要求・要件・DB・画面・ハード等）は上位の [`docs/`](../) を参照してください。

| # | ドキュメント | 内容 |
|---|-------------|------|
| 01 | [実装ガイド](01_実装ガイド.md) | 構成・実行方法（開発機 / Raspberry Pi）・初期管理者登録CLI・要件トレース |
| 02 | [テスト](02_テスト.md) | テスト構成・実行方法（`pytest`）・カバー範囲 |
| 03 | [ソフトウェア仕様書](03_ソフトウェア仕様書.md) | 実装済み動作の仕様（状態遷移・API・ルール・設定） |

- 言語/スタック：Python 3.11 / WebUI（標準 http.server + SSE、Material Design 3）/ 標準 sqlite3（実機のみ nfcpy・gpiozero）
- 対象機：Raspberry Pi 4 / Raspberry Pi OS Bookworm（Chromium キオスク表示）
- コードは [`app/`](../../app)、テストは [`tests/`](../../tests)（`python -m pytest tests/ -q` で108件）
