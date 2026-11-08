"use strict";
// SSE で受けたサーバ状態を描画するだけの薄いクライアント。
// 操作は POST /api/action。画面遷移の判断はすべてサーバ側。

const appEl = document.getElementById("app");
const el = (t, props = {}, kids = []) => {
  const n = document.createElement(t);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of [].concat(kids)) if (kid) n.append(kid);
  return n;
};

async function action(type, extra = {}) {
  const res = await fetch("/api/action", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, ...extra }),
  });
  try { return await res.json(); } catch { return { ok: true }; }
}

// メンバー登録フォームの下書き（カードタッチでの再描画時に入力を保持）
const draft = { name: "", employee_no: "", role: "user" };

function screenWrap(children) {
  appEl.replaceChildren(el("div", { class: "screen" }, children));
}

const RENDER = {
  // 要タッチ設定時の待受。画面のどこを触っても開始（standbyへ）
  attract(d) {
    const kids = [el("h1", { html: `${d.item_name || "物品"} 貸出` })];
    if (d.is_lent) {
      const cls = d.is_overdue ? "h2 danger" : "h2 warn";
      kids.push(el("p", { class: cls, html: d.is_overdue ? "▲ 延滞中" : "▲ 貸出中" }));
      if (d.due_at) kids.push(el("p", { class: "body muted", html: `返却予定: ${d.due_at}` }));
    } else {
      kids.push(el("p", { class: "h2 ok", html: "● 貸出できます" }));
    }
    kids.push(el("p", { class: "big accent", html: "画面にタッチしてはじめる" }));
    const scr = el("div", { class: "screen", onclick: () => action("start") }, kids);
    scr.style.cursor = "pointer";
    appEl.replaceChildren(scr);
  },

  standby(d) {
    const kids = [el("h1", { html: `${d.item_name || "物品"} 貸出` })];
    if (!d.is_lent) {
      kids.push(el("p", { class: "h2 ok", html: "● 貸出できます" }));
    } else {
      const cls = d.is_overdue ? "h2 danger" : "h2 warn";
      kids.push(el("p", { class: cls, html: d.is_overdue ? "▲ 延滞中（返却待ち）" : "▲ 貸出中（返却待ち）" }));
      const lines = [];
      if (d.borrower_name) lines.push(`利用者: ${d.borrower_name}`);
      if (d.due_at) lines.push(`返却予定: ${d.due_at}`);
      kids.push(el("p", { class: "body muted", html: lines.join("　/　") }));
    }
    kids.push(el("p", { class: "h2 accent", html: "社員証をタッチしてください" }));
    screenWrap(kids);
  },

  borrow_time(d) {
    const grid = el("div", { class: "grid" },
      d.choices.map(c => el("button", { onclick: () => action("choose_duration", { minutes: c.min }), html: c.label })));
    screenWrap([
      el("p", { class: "h2", html: "貸出時間を選んでください" }),
      grid,
      el("button", { class: "sub", onclick: () => action("cancel"), html: "キャンセル" }),
    ]);
  },

  unlock(d) {
    const msg = d.mode === "borrow" ? "鍵を取り出し、扉を閉めてください" : "鍵を戻し、扉を閉めてください";
    screenWrap([
      el("p", { class: "big ok", html: "🔓 解錠しました" }),
      el("p", { class: "h2", html: msg }),
      d.due_at ? el("p", { class: "body muted", html: `返却予定: ${d.due_at}` }) : null,
      el("p", { class: "body muted", html: "（数秒後に待機画面へ戻ります）" }),
    ]);
  },

  return_confirm(d) {
    screenWrap([
      el("p", { class: "big", html: "返却しますか？" }),
      el("p", { class: "body", html: `貸出日時: ${d.borrowed_at}<br>返却予定: ${d.due_at}` }),
      el("div", { class: "row" }, [
        el("button", { class: "ok", onclick: () => action("confirm_return"), html: "返却する" }),
        el("button", { class: "sub", onclick: () => action("cancel"), html: "やめる" }),
      ]),
    ]);
  },

  error(d) {
    screenWrap([
      el("p", { class: "big danger", html: "✕ エラー" }),
      el("p", { class: "h2", html: d.reason || "" }),
      el("p", { class: "body muted", html: "数秒後に待機画面へ戻ります" }),
    ]);
  },

  admin_menu(d) {
    screenWrap([
      el("p", { class: "big", html: "管理メニュー" }),
      el("p", { class: "body muted", html: d.admin_name ? `管理者: ${d.admin_name}` : "" }),
      el("button", { onclick: () => action("open_member_admin"), html: "メンバー管理" }),
      el("button", { onclick: () => action("open_report"), html: "ログ出力（CSV）" }),
      el("button", { onclick: () => action("admin_self_borrow"), html: "自分で借りる" }),
      el("button", { class: "sub", onclick: () => action("cancel"), html: "終了（待機へ）" }),
    ]);
  },

  member_admin(d) {
    const name = el("input", { value: draft.name, oninput: e => draft.name = e.target.value });
    const emp = el("input", { value: draft.employee_no, oninput: e => draft.employee_no = e.target.value });
    const roleSel = el("select", { onchange: e => draft.role = e.target.value },
      ["user", "admin"].map(r => el("option", { value: r, ...(draft.role === r ? { selected: "" } : {}) }, el("span", { html: r }))));
    roleSel.value = draft.role;

    const toast = el("p", { class: "toast muted" });
    const save = async () => {
      const r = await action("register_member", { name: draft.name, employee_no: draft.employee_no, role: draft.role });
      toast.className = "toast " + (r.ok ? "ok" : "danger");
      toast.innerHTML = r.message || "";
      if (r.ok) { draft.name = ""; draft.employee_no = ""; draft.role = "user"; }
    };

    const card = el("div", { class: "card" }, [
      el("div", { class: "field" }, [el("label", { html: "IDm" }),
        el("span", { html: d.captured_idm || "（社員証をタッチ）", class: d.captured_idm ? "" : "muted" })]),
      el("div", { class: "field" }, [el("label", { html: "氏名" }), name]),
      el("div", { class: "field" }, [el("label", { html: "社員番号" }), emp]),
      el("div", { class: "field" }, [el("label", { html: "ロール" }), roleSel]),
      el("button", { class: "ok small", onclick: save, html: "保存" }),
      toast,
    ]);

    const list = el("div", { class: "mlist" }, d.members.map(m => {
      const label = `${m.name}（${m.employee_no} / ${m.role} / ${m.is_active ? "有効" : "無効"}）`;
      const btn = m.is_active
        ? el("button", { class: "warn", onclick: () => action("set_member_active", { member_id: m.member_id, active: false }), html: "無効化" })
        : el("button", { class: "ok small", onclick: () => action("set_member_active", { member_id: m.member_id, active: true }), html: "有効化" });
      return el("div", { class: "item" }, [el("span", { html: label, class: m.is_active ? "" : "muted" }), btn]);
    }));

    screenWrap([
      el("p", { class: "h2", html: "メンバー管理" }), card, list,
      el("button", { class: "sub small", onclick: () => action("admin_menu"), html: "戻る" }),
    ]);
  },

  report(d) {
    const start = el("input", { value: d.start });
    const end = el("input", { value: d.end });
    const path = el("input", { value: d.path });
    const toast = el("p", { class: "toast" });
    const run = async () => {
      const r = await action("export_report", { start: start.value, end: end.value, path: path.value });
      toast.className = "toast " + (r.ok ? "ok" : "danger");
      toast.innerHTML = r.message || "";
    };
    screenWrap([
      el("p", { class: "h2", html: "ログ出力（CSV）" }),
      el("div", { class: "card" }, [
        el("div", { class: "field" }, [el("label", { html: "開始日" }), start]),
        el("div", { class: "field" }, [el("label", { html: "終了日" }), end]),
        el("div", { class: "field" }, [el("label", { html: "出力先" }), path]),
        el("button", { class: "ok small", onclick: run, html: "CSVを書き出す" }),
        toast,
      ]),
      el("button", { class: "sub small", onclick: () => action("admin_menu"), html: "戻る" }),
    ]);
  },
};

function render(state) {
  const fn = RENDER[state.screen];
  if (fn) fn(state.data || {});
}

// ---- SSE 接続（切断時は自動再接続）----
function connect() {
  const es = new EventSource("/events");
  es.onmessage = (e) => { try { render(JSON.parse(e.data)); } catch {} };
  es.onerror = () => { es.close(); setTimeout(connect, 1000); };
}
connect();

// ---- 開発用：疑似カードタッチバー（モックモードのみ）----
fetch("/api/meta").then(r => r.json()).then(meta => {
  if (!meta.mock) return;
  const bar = document.getElementById("devbar");
  bar.hidden = false;
  const input = el("input", { placeholder: "IDm", size: 16 });
  const touch = (idm) => action("dev_card", { idm });
  bar.append(el("span", { class: "tag", html: "疑似タッチ:" }), input,
    el("button", { onclick: () => touch(input.value.trim()), html: "タッチ" }));
  for (const m of (meta.dev_members || []))
    bar.append(el("button", { onclick: () => touch(m.idm), html: m.name }));
  input.addEventListener("keydown", e => { if (e.key === "Enter") touch(input.value.trim()); });
});
