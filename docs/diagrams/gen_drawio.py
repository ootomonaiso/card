# -*- coding: utf-8 -*-
"""
セキュアカメラ貸出システム 図面ジェネレータ

【非推奨 / DEPRECATED】
UML 図は各設計書（docs/*.md）内の Mermaid が正、回路図は docs/diagrams/*.svg に移行した。
手置きレイアウトの draw.io 書き出しは読みづらく保守コストも高いため、本スクリプトと
出力 `全図面.drawio` は段階的に廃止する。詳細は docs/diagrams/README.md を参照。

（以下は旧実装。参考のため残置）
docs/ 内の Mermaid 図を draw.io (.drawio) のマルチページファイルに起こす。
出力: docs/diagrams/全図面.drawio （各図＝1ページ/タブ）
"""
import html as _html
import os

COUNTER = [1]
PAGES = []


def esc(s):
    return _html.escape(str(s), quote=True)


def newid():
    COUNTER[0] += 1
    return f"c{COUNTER[0]}"


def page(name):
    p = {"name": name, "cells": []}
    PAGES.append(p)
    return p


def node(p, value, x, y, w, h, style):
    cid = newid()
    p["cells"].append(
        f'<mxCell id="{cid}" value="{esc(value)}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
    )
    return cid


def edge(p, src, tgt, label="", style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;orthogonalLoop=1;strokeColor=#b0b0b0;fontColor=#e0e0e0;"):
    cid = newid()
    p["cells"].append(
        f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" edge="1" parent="1" source="{src}" target="{tgt}">'
        f'<mxGeometry relative="1" as="geometry"/></mxCell>'
    )
    return cid


def pedge(p, x1, y1, x2, y2, label="", style="html=1;endArrow=block;rounded=0;strokeColor=#b0b0b0;fontColor=#e0e0e0;"):
    cid = newid()
    p["cells"].append(
        f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" edge="1" parent="1">'
        f'<mxGeometry relative="1" as="geometry">'
        f'<mxPoint x="{x1}" y="{y1}" as="sourcePoint"/>'
        f'<mxPoint x="{x2}" y="{y2}" as="targetPoint"/>'
        f'</mxGeometry></mxCell>'
    )
    return cid


# ---- styles (dark theme) ----
# 暗い背景（BG_COLOR）に映えるよう、各シェイプは濃い塗り＋明るい枠線＋明るい文字で統一。
BG_COLOR = "#1e1e1e"
_FC = "fontColor=#e6e6e6;"   # 標準の明るい文字色

S_TERM = "rounded=1;whiteSpace=wrap;html=1;arcSize=50;fillColor=#1f3d23;strokeColor=#6cbf6c;fontColor=#d6edd6;"
S_PROC = "rounded=0;whiteSpace=wrap;html=1;fillColor=#1c3147;strokeColor=#5a9bd4;fontColor=#d4e6f7;"
S_PROC2 = "rounded=0;whiteSpace=wrap;html=1;fillColor=#33254a;strokeColor=#a885c4;fontColor=#e4d7f2;"
S_DEC = "rhombus;whiteSpace=wrap;html=1;fillColor=#4a3f1c;strokeColor=#d6b656;fontColor=#f2e6bd;"
S_ERR = "rounded=0;whiteSpace=wrap;html=1;fillColor=#4a2121;strokeColor=#d17a7a;fontColor=#f4d2d2;"
S_UC = "ellipse;whiteSpace=wrap;html=1;fillColor=#1c3147;strokeColor=#5a9bd4;fontColor=#d4e6f7;"
S_ACTOR = "shape=umlActor;verticalLabelPosition=bottom;labelPosition=center;html=1;outlineConnect=0;strokeColor=#d0d0d0;fontColor=#e6e6e6;"
S_CONT = "rounded=0;whiteSpace=wrap;html=1;fillColor=none;verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;fontStyle=1;dashed=0;strokeColor=#8a8a8a;fontColor=#d6d6d6;"
S_NODE = "rounded=0;whiteSpace=wrap;html=1;fillColor=#2d2d2d;strokeColor=#9e9e9e;fontColor=#e6e6e6;"
S_STATE = "rounded=1;whiteSpace=wrap;html=1;arcSize=20;fillColor=#1c3147;strokeColor=#5a9bd4;fontColor=#d4e6f7;"
S_INIT = "ellipse;whiteSpace=wrap;html=1;fillColor=#eeeeee;strokeColor=#eeeeee;"
S_NOTE = "shape=note;whiteSpace=wrap;html=1;fillColor=#4a3f1c;strokeColor=#d6b656;fontColor=#f2e6bd;size=14;"
S_FRAME = "rounded=0;html=1;fillColor=none;dashed=1;strokeColor=#8a8a8a;verticalAlign=top;align=left;spacingLeft=6;spacingTop=2;fontStyle=2;fontColor=#aaaaaa;"
S_LL = "shape=umlLifeline;perimeter=lifelinePerimeter;whiteSpace=wrap;html=1;container=0;collapsible=0;recursiveResize=0;size=30;fillColor=none;strokeColor=#9e9e9e;fontColor=#e6e6e6;"
S_ENT = "rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacingLeft=6;spacingTop=4;fillColor=#262626;strokeColor=#bbbbbb;fontColor=#e6e6e6;"
_E = "strokeColor=#b0b0b0;fontColor=#e0e0e0;"
E_SEQ = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;" + _E
E_MSG = "html=1;endArrow=block;rounded=0;" + _E
E_RET = "html=1;endArrow=open;dashed=1;rounded=0;endSize=8;" + _E
E_ER = "html=1;rounded=0;startArrow=ERone;startFill=0;endArrow=ERmany;endFill=0;edgeStyle=entityRelationEdgeStyle;" + _E


# ============================================================
# シーケンス図ヘルパ（2パス：先に高さ算出→ライフライン→メッセージ）
# ============================================================
def build_seq(p, participants, steps):
    gap, w = 200, 110
    xs = [40 + i * gap for i in range(len(participants))]
    centers = [x + w / 2 for x in xs]
    idx = {name: i for i, (name, _) in enumerate(participants)}

    y = 70
    drawn, frames, fstack = [], [], []
    for st in steps:
        t = st[0]
        if t == "msg":
            _, a, b, label, ret = st
            drawn.append(("msg", centers[idx[a]], centers[idx[b]], y, label, ret))
            y += 48
        elif t == "note":
            _, a, label = st
            drawn.append(("note", centers[idx[a]], y, label))
            y += 56
        elif t == "fs":
            fstack.append((y - 8, st[1]))
            y += 26
        elif t == "fe":
            sy, label = fstack.pop()
            frames.append((sy, y + 6, label))
            y += 14
    height = y + 20

    # ライフライン
    for i, (name, actor) in enumerate(participants):
        style = S_LL + ("participant=umlActor;" if actor else "")
        node(p, name, xs[i], 20, w, height, style)
    # フレーム（背面）
    right = xs[-1] + w
    for sy, ey, label in frames:
        node(p, label, 20, sy, right - 10, ey - sy, S_FRAME)
    # メッセージ（前面）
    for d in drawn:
        if d[0] == "msg":
            _, cx1, cx2, yy, label, ret = d
            style = E_RET if ret else E_MSG
            pedge(p, cx1, yy, cx2, yy, label, style)
        else:
            _, cx, yy, label = d
            node(p, label, cx - 80, yy, 160, 44, S_NOTE)


# ============================================================
# 03-1 業務フロー As-Is
# ============================================================
p = page("03-1 業務フロー As-Is")
cx = 240
a = node(p, "開始", cx, 40, 160, 40, S_TERM)
b = node(p, "帳票に記入する", cx, 110, 160, 40, S_PROC)
c = node(p, "管理者を探す", cx, 180, 160, 40, S_PROC)
d = node(p, "管理者はいるか", cx, 250, 160, 70, S_DEC)
wait = node(p, "待つ・後で出直す", 480, 265, 160, 40, S_PROC)
e = node(p, "管理者が帳票をチェックする", cx, 360, 160, 40, S_PROC)
f = node(p, "棚を開けてカメラを取り出す", cx, 430, 160, 40, S_PROC)
g = node(p, "カメラを使う", cx, 500, 160, 40, S_PROC)
h = node(p, "カメラを棚に戻す", cx, 570, 160, 40, S_PROC)
z = node(p, "終了", cx, 640, 160, 40, S_TERM)
edge(p, a, b); edge(p, b, c); edge(p, c, d)
edge(p, d, wait, "いない"); edge(p, wait, c)
edge(p, d, e, "いる"); edge(p, e, f); edge(p, f, g); edge(p, g, h); edge(p, h, z)

# ============================================================
# 03-2 業務フロー To-Be
# ============================================================
p = page("03-2 業務フロー To-Be")
cx = 260
a = node(p, "開始", cx, 30, 170, 40, S_TERM)
touch = node(p, "社員証をタッチする", cx, 95, 170, 40, S_PROC)
reg = node(p, "登録済みか", cx, 160, 170, 70, S_DEC)
errend = node(p, "エラーを表示して終了", 520, 175, 170, 40, S_ERR)
lent = node(p, "鍵は貸出中か", cx, 265, 170, 70, S_DEC)
lentend = node(p, "貸出中の表示を確認して終了", 520, 280, 170, 40, S_ERR)
sel = node(p, "貸出時間を選ぶ", cx, 370, 170, 40, S_PROC)
rec = node(p, "システムが保管庫を解錠し、貸出ログを記録する", cx, 435, 170, 50, S_PROC2)
take = node(p, "鍵を取り出し、保管庫を手で施錠する", cx, 505, 170, 50, S_PROC)
use = node(p, "棚を開けてカメラを使う", cx, 575, 170, 40, S_PROC)
back = node(p, "カメラを棚に戻し、棚を施錠する", cx, 635, 170, 50, S_PROC)
rtouch = node(p, "社員証をタッチして返却を押す", cx, 705, 170, 50, S_PROC)
rrec = node(p, "システムが保管庫を解錠し、返却日時を記録する", cx, 775, 170, 50, S_PROC2)
rback = node(p, "鍵を戻し、保管庫を手で施錠する", cx, 845, 170, 50, S_PROC)
z = node(p, "終了", cx, 915, 170, 40, S_TERM)
edge(p, a, touch); edge(p, touch, reg)
edge(p, reg, errend, "未登録"); edge(p, reg, lent, "登録済み")
edge(p, lent, lentend, "貸出中"); edge(p, lent, sel, "空き")
for s, t in [(sel, rec), (rec, take), (take, use), (use, back), (back, rtouch),
             (rtouch, rrec), (rrec, rback), (rback, z)]:
    edge(p, s, t)

# ============================================================
# 03-4 アクティビティ図（貸出・担当分担）
# ============================================================
p = page("03-4 アクティビティ（貸出）")
node(p, "利用者", 40, 40, 300, 360, S_CONT)
node(p, "システム", 380, 40, 360, 360, S_CONT)
u1 = node(p, "社員証をタッチ", 110, 90, 160, 40, S_PROC)
u2 = node(p, "貸出時間を選ぶ", 110, 200, 160, 40, S_PROC)
u3 = node(p, "鍵を取り出す", 110, 280, 160, 40, S_PROC)
u4 = node(p, "保管庫を手で施錠", 110, 340, 160, 40, S_PROC)
s1 = node(p, "IDmで認証", 430, 90, 160, 40, S_PROC2)
s2 = node(p, "登録済み・空き?", 430, 150, 160, 60, S_DEC)
s3 = node(p, "エラー/貸出中表示", 610, 160, 110, 40, S_ERR)
s4 = node(p, "貸出ログ登録", 430, 240, 160, 40, S_PROC2)
s5 = node(p, "解錠信号・数秒", 430, 300, 160, 40, S_PROC2)
edge(p, u1, s1); edge(p, s1, s2)
edge(p, s2, s3, "No"); edge(p, s2, s4, "Yes")
edge(p, s4, u2); edge(p, u2, s5); edge(p, s5, u3); edge(p, u3, u4)

# ============================================================
# 04 ユースケース図
# ============================================================
p = page("04 ユースケース図")
node(p, "貸出システム", 220, 30, 360, 560, S_CONT)
u = node(p, "利用者", 40, 230, 40, 80, S_ACTOR)
m = node(p, "管理者", 700, 230, 40, 80, S_ACTOR)
uc1 = node(p, "社員証で認証する", 300, 60, 200, 50, S_UC)
uc2 = node(p, "鍵を借りる", 300, 140, 200, 50, S_UC)
uc3 = node(p, "鍵を返す", 300, 220, 200, 50, S_UC)
uc4 = node(p, "貸出状況を確認する", 300, 300, 200, 50, S_UC)
uc5 = node(p, "メンバーを登録・削除する", 300, 380, 200, 50, S_UC)
uc6 = node(p, "貸借ログを閲覧・出力する", 300, 460, 200, 50, S_UC)
uc7 = node(p, "保管庫を解錠する", 300, 530, 200, 50, S_UC)
lock = node(p, "電磁ロック", 650, 530, 120, 40, S_NODE)
assoc = "html=1;endArrow=none;rounded=0;strokeColor=#b0b0b0;fontColor=#e0e0e0;"
inc = "html=1;endArrow=open;dashed=1;rounded=0;endSize=8;strokeColor=#b0b0b0;fontColor=#e0e0e0;"
for a2 in (uc2, uc3, uc4):
    edge(p, u, a2, "", assoc)
for a2 in (uc5, uc6, uc2):
    edge(p, m, a2, "", assoc)
edge(p, uc2, uc1, "«include»", inc); edge(p, uc3, uc1, "«include»", inc)
edge(p, uc2, uc7, "«include»", inc); edge(p, uc3, uc7, "«include»", inc)
edge(p, uc7, lock, "", assoc)

# ============================================================
# 05-1 システム構成図
# ============================================================
p = page("05-1 システム構成図")
node(p, "設置ユニット", 40, 20, 820, 460, S_CONT)
cr = node(p, "カードリーダー\nRC-S380", 80, 70, 150, 60, S_NODE)
ts = node(p, "タッチスクリーン\nRaspberry Pi用", 80, 170, 150, 60, S_NODE)
node(p, "Raspberry Pi", 320, 60, 240, 170, S_CONT)
app = node(p, "貸出アプリ", 360, 100, 160, 40, S_PROC)
db = node(p, "SQLite", 360, 160, 160, 40, "shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#1c3147;strokeColor=#5a9bd4;fontColor=#d4e6f7;")
drv = node(p, "ロック駆動回路\nリレー or MOSFET + ダイオード", 320, 290, 240, 60, S_NODE)
lk = node(p, "電磁ソレノイドロック\nLE-53", 620, 290, 180, 60, S_NODE)
psu = node(p, "ロック用電源", 320, 400, 160, 40, S_NODE)
net = node(p, "ネットワーク", 630, 70, 150, 40, "shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#2d2d2d;strokeColor=#9e9e9e;fontColor=#e6e6e6;")
usbm = node(p, "USBメモリ等", 630, 160, 150, 40, S_NODE)
edge(p, app, db, "", assoc)
edge(p, cr, app, "USB"); edge(p, ts, app, "表示・タッチ入力")
edge(p, app, drv, "GPIO"); edge(p, psu, drv, ""); edge(p, drv, lk, "")
edge(p, app, net, "NTP時刻同期", inc); edge(p, app, usbm, "CSV出力", inc)

# ============================================================
# 05-2 レイヤ構成
# ============================================================
p = page("05-2 レイヤ構成")
cx = 220
ui = node(p, "UI層: 待機/貸出/返却/管理 画面", cx, 40, 260, 50, S_PROC)
ap = node(p, "アプリケーション層: 認証・貸出・返却・ログ・メンバー管理", cx, 130, 260, 50, S_PROC)
dom = node(p, "ドメイン層: メンバー/物品/貸借ログのルール", cx, 220, 260, 50, S_PROC)
dev = node(p, "デバイス層: カード読取・解錠制御", 560, 130, 220, 50, S_PROC2)
data = node(p, "データ層: SQLiteアクセス", cx, 310, 260, 50, S_PROC2)
card = node(p, "nfcpy / RC-S380", 560, 220, 220, 40, S_NODE)
lock2 = node(p, "GPIO / 駆動回路 / LE-53", 560, 300, 220, 40, S_NODE)
edge(p, ui, ap); edge(p, ap, dom); edge(p, ap, dev); edge(p, dom, data)
edge(p, dev, card); edge(p, dev, lock2)

# ============================================================
# 05-3 時刻同期フロー
# ============================================================
p = page("05-3 時刻同期フロー")
q = node(p, "ネットワークあり?", 240, 40, 180, 70, S_DEC)
ntp = node(p, "NTPで同期\nsystemd-timesyncd 等", 120, 160, 180, 50, S_PROC)
rtc = node(p, "RTCモジュール搭載\nI2C接続", 380, 160, 180, 50, S_PROC)
use = node(p, "ログ日時に使用", 240, 270, 180, 40, S_TERM)
edge(p, q, ntp, "あり"); edge(p, q, rtc, "なし")
edge(p, ntp, use); edge(p, rtc, use)

# ============================================================
# 06 ER図
# ============================================================
p = page("06 ER図")
member = node(p, ("<b>MEMBER（メンバー）</b><br>"
                  "member_id PK<br>card_idm UK（社員証IDm）<br>employee_no（社員番号）<br>"
                  "name（氏名）<br>role（user/admin）<br>is_active<br>created_at"),
              40, 60, 240, 170, S_ENT)
item = node(p, ("<b>ITEM（物品）</b><br>"
                "item_id PK<br>name（セキュアカメラ）<br>location（保管場所）<br>is_active"),
            40, 330, 240, 110, S_ENT)
loan = node(p, ("<b>LOAN（貸借ログ）</b><br>"
                "loan_id PK<br>member_id FK<br>item_id FK<br>borrowed_at（貸出日時）<br>"
                "duration_min（15/30/60/120/240/480）<br>due_at（返却予定）<br>"
                "returned_at（未返却はNULL）"),
            480, 180, 280, 170, S_ENT)
edge(p, member, loan, "borrows", E_ER)
edge(p, item, loan, "is_lent", E_ER)

# ============================================================
# 07 画面遷移図
# ============================================================
p = page("07 画面遷移図")
s01 = node(p, "S01 待機画面\n保管中/貸出中の表示", 40, 220, 180, 50, S_STATE)
s02 = node(p, "認証", 300, 225, 140, 60, S_DEC)
s06 = node(p, "S06 エラー画面", 300, 40, 160, 40, S_ERR)
s03 = node(p, "S03 貸出時間選択", 540, 120, 160, 40, S_STATE)
s05 = node(p, "S05 返却確認", 540, 300, 160, 40, S_STATE)
a01 = node(p, "A01 管理メニュー", 300, 420, 160, 40, S_PROC2)
s04 = node(p, "S04 解錠中\n鍵を取り出してください", 760, 120, 180, 50, S_STATE)
s07 = node(p, "S07 解錠中\n鍵を戻してください", 760, 300, 180, 50, S_STATE)
a02 = node(p, "A02 メンバー管理", 540, 420, 160, 40, S_PROC2)
a03 = node(p, "A03 ログ出力", 540, 480, 160, 40, S_PROC2)
edge(p, s01, s02, "社員証タッチ")
edge(p, s02, s06, "未登録"); edge(p, s02, s03, "登録済み・空き")
edge(p, s02, s05, "本人が貸出中"); edge(p, s02, a01, "管理者")
edge(p, s03, s04, "時間を選ぶ"); edge(p, s05, s07, "返却する")
edge(p, s04, s01); edge(p, s07, s01); edge(p, s06, s01)
edge(p, a01, a02); edge(p, a01, a03); edge(p, a01, s03)

# ============================================================
# 08-1 シーケンス（貸出）
# ============================================================
p = page("08-1 シーケンス（貸出）")
build_seq(p,
    [("利用者", True), ("カードリーダー", False), ("Raspberry Pi（アプリ）", False), ("DB", False), ("電磁ロック", False)],
    [("msg", "利用者", "カードリーダー", "社員証をタッチ", False),
     ("msg", "カードリーダー", "Raspberry Pi（アプリ）", "IDm", False),
     ("msg", "Raspberry Pi（アプリ）", "DB", "メンバー照合", False),
     ("fs", "alt  [未登録]"),
     ("msg", "DB", "Raspberry Pi（アプリ）", "該当なし", True),
     ("msg", "Raspberry Pi（アプリ）", "利用者", "エラー表示", True),
     ("fe",),
     ("fs", "alt  [登録済み]"),
     ("msg", "DB", "Raspberry Pi（アプリ）", "氏名・社員番号", True),
     ("msg", "Raspberry Pi（アプリ）", "DB", "貸出中か確認", False),
     ("fs", "alt  [貸出中]"),
     ("msg", "Raspberry Pi（アプリ）", "利用者", "貸出中の表示（氏名・返却予定）", True),
     ("fe",),
     ("fs", "alt  [空き]"),
     ("msg", "Raspberry Pi（アプリ）", "利用者", "貸出時間の選択画面", True),
     ("msg", "利用者", "Raspberry Pi（アプリ）", "貸出時間を選ぶ", False),
     ("msg", "Raspberry Pi（アプリ）", "DB", "貸出ログ登録（貸出日時・返却予定）", False),
     ("msg", "Raspberry Pi（アプリ）", "電磁ロック", "解錠信号（数秒）", False),
     ("msg", "Raspberry Pi（アプリ）", "利用者", "鍵を取り出してください", True),
     ("msg", "利用者", "電磁ロック", "鍵を取り出し、手で施錠", False),
     ("fe",),
     ("fe",)])

# ============================================================
# 08-2 シーケンス（返却）
# ============================================================
p = page("08-2 シーケンス（返却）")
build_seq(p,
    [("利用者", True), ("カードリーダー", False), ("Raspberry Pi（アプリ）", False), ("DB", False), ("電磁ロック", False)],
    [("note", "利用者", "待機画面から開始"),
     ("msg", "利用者", "カードリーダー", "社員証をタッチ", False),
     ("msg", "カードリーダー", "Raspberry Pi（アプリ）", "IDm", False),
     ("msg", "Raspberry Pi（アプリ）", "DB", "貸出中のログを検索", False),
     ("fs", "alt  [本人の貸出ではない]"),
     ("msg", "Raspberry Pi（アプリ）", "利用者", "エラー表示", True),
     ("fe",),
     ("fs", "alt  [本人の貸出]"),
     ("msg", "Raspberry Pi（アプリ）", "利用者", "返却確認画面", True),
     ("msg", "利用者", "Raspberry Pi（アプリ）", "「返却する」を押す", False),
     ("msg", "Raspberry Pi（アプリ）", "DB", "返却日時を記録", False),
     ("msg", "Raspberry Pi（アプリ）", "電磁ロック", "解錠信号（数秒）", False),
     ("msg", "Raspberry Pi（アプリ）", "利用者", "鍵を戻してください", True),
     ("msg", "利用者", "電磁ロック", "鍵を戻し、手で施錠", False),
     ("fe",)])

# ============================================================
# 08-3 シーケンス（解錠制御 UC7）
# ============================================================
p = page("08-3 シーケンス（解錠制御）")
build_seq(p,
    [("アプリ", False), ("GPIO", False), ("駆動回路", False), ("ソレノイド(LE-53)", False)],
    [("msg", "アプリ", "GPIO", "出力 ON", False),
     ("msg", "GPIO", "駆動回路", "駆動信号", False),
     ("msg", "駆動回路", "ソレノイド(LE-53)", "通電（解錠）", False),
     ("note", "アプリ", "規定秒数待機"),
     ("msg", "アプリ", "GPIO", "出力 OFF", False),
     ("msg", "GPIO", "駆動回路", "停止", False),
     ("msg", "駆動回路", "ソレノイド(LE-53)", "通電停止（発熱防止）", False)])

# ============================================================
# 08-4 シーケンス（メンバー登録 UC5）
# ============================================================
p = page("08-4 シーケンス（メンバー登録）")
build_seq(p,
    [("管理者", True), ("アプリ", False), ("カードリーダー", False), ("DB", False)],
    [("msg", "管理者", "アプリ", "管理メニュー→メンバー管理", False),
     ("msg", "管理者", "カードリーダー", "新規社員証をタッチ", False),
     ("msg", "カードリーダー", "アプリ", "IDm", False),
     ("msg", "アプリ", "管理者", "氏名・社員番号・ロール入力画面", True),
     ("msg", "管理者", "アプリ", "入力して保存", False),
     ("msg", "アプリ", "DB", "MEMBER登録（is_active=1）", False),
     ("msg", "DB", "アプリ", "完了", True),
     ("msg", "アプリ", "管理者", "登録完了表示", True)])

# ============================================================
# 08-5 状態遷移図（物品）
# ============================================================
p = page("08-5 状態遷移（物品）")
init = node(p, "", 60, 40, 20, 20, S_INIT)
keep = node(p, "保管中", 40, 120, 120, 50, S_STATE)
lent = node(p, "貸出中", 40, 260, 120, 50, S_STATE)
over = node(p, "延滞", 320, 260, 120, 50, S_ERR)
edge(p, init, keep)
edge(p, keep, lent, "登録者がタッチして貸出")
edge(p, lent, keep, "本人がタッチして返却")
edge(p, lent, over, "返却予定時刻を過ぎる")
edge(p, over, keep, "本人がタッチして返却")

# ============================================================
# 08-6 UIステートマシン
# ============================================================
p = page("08-6 UIステートマシン")
init = node(p, "", 60, 40, 20, 20, S_INIT)
wait = node(p, "待機", 40, 110, 120, 44, S_STATE)
auth = node(p, "認証中", 40, 220, 120, 44, S_STATE)
err = node(p, "エラー", 260, 110, 120, 44, S_ERR)
sel = node(p, "時間選択", 260, 300, 120, 44, S_STATE)
ret = node(p, "返却確認", 460, 300, 120, 44, S_STATE)
adm = node(p, "管理メニュー", 260, 220, 120, 44, S_PROC2)
ul1 = node(p, "解錠(貸出)", 260, 390, 120, 44, S_STATE)
ul2 = node(p, "解錠(返却)", 460, 390, 120, 44, S_STATE)
edge(p, init, wait)
edge(p, wait, auth, "タッチ")
edge(p, auth, err, "未登録")
edge(p, auth, sel, "登録・空き")
edge(p, auth, ret, "本人が貸出中")
edge(p, auth, adm, "管理者")
edge(p, sel, ul1, "時間選択")
edge(p, ret, ul2, "返却する")
edge(p, ul1, wait); edge(p, ul2, wait)
edge(p, err, wait, "タイムアウト")
edge(p, adm, wait, "戻る/タイムアウト")

# ============================================================
# 09-1 HW接続構成図
# ============================================================
p = page("09-1 HW接続構成図")
node(p, "設置ユニット", 40, 20, 860, 440, S_CONT)
node(p, "Raspberry Pi", 340, 70, 220, 230, S_CONT)
gpio = node(p, "GPIO 出力ピン", 370, 110, 160, 40, S_PROC)
usbp = node(p, "USBポート", 370, 170, 160, 40, S_PROC)
i2cp = node(p, "I2C", 370, 230, 160, 40, S_PROC)
cr = node(p, "カードリーダー\nRC-S380", 80, 110, 160, 50, S_NODE)
ts = node(p, "タッチスクリーン", 80, 230, 160, 50, S_NODE)
drv = node(p, "ロック駆動回路\nリレー or MOSFET+ダイオード", 630, 100, 220, 60, S_NODE)
lk = node(p, "ソレノイドロック\nLE-53（DC5V/2W・通電時解錠）", 630, 200, 220, 60, S_NODE)
psu = node(p, "ロック用電源", 630, 300, 160, 40, S_NODE)
rtc = node(p, "RTCモジュール（任意）", 80, 340, 180, 40, S_NODE)
edge(p, cr, usbp, "USB"); edge(p, ts, gpio, "表示/タッチ")
edge(p, gpio, drv, "駆動信号"); edge(p, psu, drv, "電源"); edge(p, drv, lk, "通電")
edge(p, rtc, i2cp, "I2C")

# ============================================================
# 09-2 解錠制御シーケンス（HW）
# ============================================================
p = page("09-2 解錠制御シーケンス")
build_seq(p,
    [("アプリ", False), ("GPIO", False), ("駆動回路", False), ("ソレノイド", False)],
    [("msg", "アプリ", "GPIO", "HIGH（ON）", False),
     ("msg", "GPIO", "駆動回路", "駆動", False),
     ("msg", "駆動回路", "ソレノイド", "通電 → 解錠", False),
     ("note", "アプリ", "数秒待機（設定値）"),
     ("msg", "アプリ", "GPIO", "LOW（OFF）", False),
     ("msg", "駆動回路", "ソレノイド", "通電停止", False)])

# ============================================================
# 09-3 駆動回路図（MOSFET方式）
# ============================================================
p = page("09-3 駆動回路（MOSFET方式）")
gpio = node(p, "GPIO", 40, 60, 100, 40, S_PROC)
rg = node(p, "ゲート抵抗", 200, 60, 120, 40, S_NODE)
q = node(p, "N-ch MOSFET", 380, 60, 140, 40, S_NODE)
v = node(p, "ロック電源 +", 380, 180, 140, 40, S_TERM)
sol = node(p, "ソレノイド LE-53\n(DC5V / 2W)", 560, 120, 160, 50, S_NODE)
d1 = node(p, "還流ダイオード（並列）", 560, 200, 160, 40, S_ERR)
gnd = node(p, "共通GND", 380, 300, 140, 40, S_TERM)
edge(p, gpio, rg); edge(p, rg, q)
edge(p, v, sol); edge(p, sol, q, "ドレイン")
edge(p, sol, d1, "並列", inc); edge(p, v, d1, "", inc)
edge(p, q, gnd, "ソース")

# ============================================================
# ファイル出力
# ============================================================
def render():
    out = ['<mxfile host="app.diagrams.net" type="device">']
    for i, pg in enumerate(PAGES):
        cells = "\n        ".join(pg["cells"])
        out.append(
            f'  <diagram id="pg{i}" name="{esc(pg["name"])}">\n'
            f'    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" '
            f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="1169" pageHeight="826" math="0" shadow="0" '
            f'background="{BG_COLOR}">\n'
            f'      <root>\n'
            f'        <mxCell id="0"/>\n'
            f'        <mxCell id="1" parent="0"/>\n'
            f'        {cells}\n'
            f'      </root>\n'
            f'    </mxGraphModel>\n'
            f'  </diagram>'
        )
    out.append("</mxfile>")
    return "\n".join(out)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "全図面.drawio")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(render())
    print(f"wrote {path}  ({len(PAGES)} pages)")
