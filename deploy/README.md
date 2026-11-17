# deploy — Raspberry Pi 実機セットアップ用ファイル

OS 起動時の自動起動（05 §8）・RC-S380 の権限・DB バックアップをここに集約する。
対象: Raspberry Pi 4 / Raspberry Pi OS Bookworm / Python 3.11。

| ファイル | 用途 | 配置先 |
|----------|------|--------|
| [`lending.service`](lending.service) | Web サーバの systemd 自動起動 | `/etc/systemd/system/` |
| [`kiosk.desktop`](kiosk.desktop) | Chromium キオスクの自動起動（XDG autostart） | `~/.config/autostart/` |
| [`99-pasori.rules`](99-pasori.rules) | RC-S380 を非 root で使う udev ルール | `/etc/udev/rules.d/` |
| [`backup_db.sh`](backup_db.sh) | SQLite のオンラインバックアップ（cron 用） | 任意（cron から呼ぶ） |

## セットアップ手順（概要）

```bash
# 1) 依存
sudo apt install chromium-browser sqlite3
pip install nfcpy gpiozero

# 2) カードリーダー権限（udev）
sudo cp deploy/99-pasori.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG plugdev pi        # 実行ユーザを plugdev へ（再ログイン必要）

# 3) サーバ自動起動（systemd）
sudo cp deploy/lending.service /etc/systemd/system/   # パスは編集して合わせる
sudo systemctl daemon-reload
sudo systemctl enable --now lending

# 4) キオスク自動起動（デスクトップセッション）
mkdir -p ~/.config/autostart
cp deploy/kiosk.desktop ~/.config/autostart/

# 5) バックアップ（cron 例: 毎日 3:00）
crontab -e
#   0 3 * * * /home/pi/card/deploy/backup_db.sh /home/pi/card/lending.sqlite3 /home/pi/backups
```

## バックアップからの復元（リストア）

`backup_db.sh` は `backups/lending-YYYYMMDD.sqlite3` を日付名で作成し、30 日より古い世代を自動削除する。
障害や誤操作から戻すときは以下の手順で復元する。

```sh
# 1) サービスを止める（書き込み中の復元を避ける）
sudo systemctl stop lending.service

# 2) 現物を退避（切り戻し用）。WAL/SHM があれば一緒に退避
mv lending.sqlite3 lending.sqlite3.bak 2>/dev/null || true
rm -f lending.sqlite3-wal lending.sqlite3-shm

# 3) 使いたい世代を書き戻す（例: 2026-11-16 のバックアップ）
cp /home/pi/backups/lending-20261116.sqlite3 lending.sqlite3

# 4) 整合性を確認してからサービス再開
sqlite3 lending.sqlite3 "PRAGMA integrity_check;"   # → ok
sudo systemctl start lending.service
```

> バックアップは `.backup`（オンラインバックアップ API）で取得した単一ファイルのため、`-wal`/`-shm` は不要。
> 復元時に古い `-wal`/`-shm` が残っていると不整合の元になるので必ず消す。管理者が全員ロックアウトした場合は
> `python main.py --add-admin --idm <IDm> --name <氏名> --employee-no <番号>` で管理者を復旧できる（サーバ停止中に実行）。

## 時刻同期（NFR-03）

- **ネットワークあり**: Bookworm 標準の `systemd-timesyncd` で NTP 同期される。
  `timedatectl status` で `NTP service: active` / `System clock synchronized: yes` を確認。
- **ネットワークなし**: I2C RTC モジュール（DS3231 等）を物理3/5ピン（SDA1/SCL1）へ接続し、
  `/boot/firmware/config.txt` に `dtoverlay=i2c-rtc,ds3231` を追記 →
  `sudo apt remove fake-hwclock` → 再起動後 `sudo hwclock -w` で時刻を書き込む。
- どちらを採るかは設置環境（[10] Q8）の回答で確定する。

## CSV の持ち出し（USB メモリ）

管理画面のログ出力は、`config.json` の `csv_export_dirs`（既定 `[".", "/media", "/mnt"]`）
配下の `*.csv` にのみ書き出せる（任意パス書き込み・DB 上書き対策）。USB メモリへ直接出す場合は、
Bookworm デスクトップの自動マウント先（例 `/media/pi/USBMEM/lending_log.csv`）を出力パスに指定する。
別のマウント位置を使う環境では、そのディレクトリを `csv_export_dirs` に追加する。`..` を含むパス・
拡張子が `.csv` でないパス・許可ディレクトリ外・DB ファイル自身は拒否される。
