# セキュアカメラ貸出システム

社員証タッチで保管庫を解錠し、貸借ログを残す貸出システム。
UI は **ローカルWebアプリ**（標準ライブラリのみ・追加依存なし）で、Pi 上では Chromium をキオスク表示して使う。
対象機: **Raspberry Pi 4 / Raspberry Pi OS Bookworm / Python 3.11**（開発機ではデバイスをモックして同じコードが動く）。

## クイックスタート（開発機 / Windows）

```bash
python main.py --seed                    # デモ起動 → ブラウザで http://127.0.0.1:8000/
python -m unittest discover -s tests     # テスト
```

モックモードでは画面下の「疑似タッチ」バーでカードを模擬操作できる。

## ドキュメント

| 区分 | 場所 | 内容 |
|------|------|------|
| 設計書 | [`docs/`](docs/) | 要求・要件・業務フロー・DB・画面・ハード等（00〜11） |
| 実装ドキュメント | [`docs/impl/`](docs/impl/) | 構成・実行方法・要件トレース・テスト |

- 実装ガイド → [`docs/impl/01_実装ガイド.md`](docs/impl/01_実装ガイド.md)
- テスト → [`docs/impl/02_テスト.md`](docs/impl/02_テスト.md)

## 構成概要

```
app/        アプリ本体（config / db / domain / repository / devices / services / web）
tests/      テスト（機能ごとに分割）
docs/       設計書
docs/impl/  実装ドキュメント
schema.sql  DDL      config.json 設定      main.py エントリポイント
```
