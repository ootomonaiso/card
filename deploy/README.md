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

## 時刻同期（NFR-03）

- **ネットワークあり**: Bookworm 標準の `systemd-timesyncd` で NTP 同期される。
  `timedatectl status` で `NTP service: active` / `System clock synchronized: yes` を確認。
- **ネットワークなし**: I2C RTC モジュール（DS3231 等）を物理3/5ピン（SDA1/SCL1）へ接続し、
  `/boot/firmware/config.txt` に `dtoverlay=i2c-rtc,ds3231` を追記 →
  `sudo apt remove fake-hwclock` → 再起動後 `sudo hwclock -w` で時刻を書き込む。
- どちらを採るかは設置環境（[10] Q8）の回答で確定する。

## CSV の持ち出し（USB メモリ）

管理画面のログ出力は任意のパスへ書き出せる。USB メモリへ直接出す場合は、
Bookworm デスクトップの自動マウント先（例 `/media/pi/USBMEM/lending_log.csv`）を
出力パスに指定する。
