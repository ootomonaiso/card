"use strict";
// SSE で受けたサーバ状態を描画するだけの薄いクライアント。
// 操作は POST /api/action。画面遷移の判断はすべてサーバ側。
// 見た目は Material Design 3（style.css のトークン）に沿う。送る action 名・
// payload の読み方は従来どおりで、ここでは描画マークアップのみを MD3 化している。

const appEl = document.getElementById("app");
const el = (t, props = {}, kids = []) => {
  const n = document.createElement(t);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k === "text") n.textContent = v;  // ユーザ入力を安全に表示する（XSS対策）
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of [].concat(kids)) if (kid) n.append(kid);
  return n;
};

// `html:` の文字列へユーザ入力（物品名・氏名・IDm 等）を埋め込むときのHTMLエスケープ。
// サーバ→SSE→innerHTML の経路で <img onerror=...> 等が実行されるのを防ぐ（stored XSS対策）。
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// インラインSVGアイコン（外部フォント/画像は使わない方針）。
const ICON = {
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 20h20L12 3z"/><path d="M12 9v5"/><path d="M12 17.5h.01"/></svg>',
  unlock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg>',
  card: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2.5"/><path d="M2 10h20"/><path d="M6 15h4"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg>',
};
const icon = (name, cls = "") => el("span", { class: cls, html: ICON[name] || "" });

async function action(type, extra = {}) {
  const res = await fetch("/api/action", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, ...extra }),
  });
  try { return await res.json(); } catch { return { ok: true }; }
}

// メンバー登録フォームの下書き（カードタッチでの再描画時に入力を保持）
const draft = { name: "", employee_no: "", role: "user" };
// 初期管理者登録フォームの下書き（setup画面・再タッチでの再描画時に入力を保持）
const setupDraft = { name: "", employee_no: "" };
// 物品追加フォームの下書き（物品管理画面の再描画時に入力を保持）
const itemDraft = { name: "", location: "", category: "" };
// 一覧の行内編集の下書き。他行の操作でSSE再描画が走っても未保存の入力を保持する。
// 画面を離れたとき render() が clear する（stale化を防ぐ）。キーは member_id / item_id。
const memberEdits = new Map(); // member_id -> {name, employee_no}
const itemEdits = new Map();   // item_id -> {name, location, category}

function screenWrap(children, extraClass = "") {
  appEl.replaceChildren(el("div", { class: extraClass ? `screen ${extraClass}` : "screen" }, children));
}

// 管理画面の共通シェル（アプリバー + スクロール本文）。トーンをキオスクと揃える。
function adminWrap(title, backAction, bodyKids, sub) {
  const bar = el("div", { class: "appbar" }, [
    el("button", { class: "text back", onclick: () => action(backAction),
      html: `${ICON.back}<span>戻る</span>` }),
    el("div", { class: "bar-title" }, [
      el("span", { html: title }),
      sub ? el("div", { class: "bar-sub", html: sub }) : null,
    ]),
  ]);
  const body = el("div", { class: "admin-body" }, bodyKids);
  appEl.replaceChildren(el("div", { class: "screen admin" }, [bar, body]));
}

// 物品状況の見た目（色種別・アイコン・補足行）はチップ表示と大表示で共通。
// 見出し文だけが用途で異なるので、それぞれの呼び出し側で与える。
function statusKind(it) {
  if (!it.is_lent) return { kind: "available", ico: "check" };
  if (it.is_overdue) return { kind: "overdue", ico: "alert" };
  return { kind: "borrowed", ico: "clock" };
}
function statusSub(it) {
  const sub = [];
  if (it.is_lent) {
    if (it.borrower_name) sub.push(`利用者: ${esc(it.borrower_name)}`);
    if (it.due_at) sub.push(`返却予定: <span class="num">${esc(it.due_at)}</span>`);
  }
  return sub;
}

// 物品1件ぶんの状況を MD3 ステータスチップにする（待受の一覧表示で使う）。
function itemStatusChip(it) {
  const { kind, ico } = statusKind(it);
  const head = !it.is_lent ? `${esc(it.name)}：貸出できます`
    : it.is_overdue ? `延滞中：${esc(it.name)}` : `貸出中：${esc(it.name)}`;
  const sub = statusSub(it);
  return el("div", { class: `status ${kind}` }, [
    icon(ico, "ico"),
    el("div", { class: "txt" }, [
      el("div", { class: "st-head", html: head }),
      sub.length ? el("div", { class: "st-sub", html: sub.join("　/　") }) : null,
    ]),
  ]);
}

// 単一物品向けの大きな状況表示（遠目でも状態が分かる）。
function heroStatus(it) {
  const { kind, ico } = statusKind(it);
  const head = !it.is_lent ? "貸出できます"
    : it.is_overdue ? "延滞中（返却待ち）" : "貸出中（返却待ち）";
  const sub = statusSub(it);
  return el("div", { class: `hero-status ${kind}` }, [
    icon(ico, "hero-ico"),
    el("p", { class: "display", html: head }),
    sub.length ? el("p", { class: "body muted", html: sub.join("　/　") }) : null,
  ]);
}

function homeContent(d, withHint) {
  const items = d.items || [];
  const kids = [];
  const title = items.length === 1 ? `${esc(items[0].name)} 貸出` : "物品 貸出";
  kids.push(el("h1", { class: "headline", html: title }));
  if (items.length === 1) {
    kids.push(heroStatus(items[0]));
  } else if (d.groups) {
    // 複数カテゴリがあるときはカテゴリ見出し付きで一覧を分ける。
    for (const g of d.groups) {
      kids.push(el("div", { class: "section-label", html: esc(g.category) }));
      kids.push(el("div", { class: "statuslist" }, g.items.map(itemStatusChip)));
    }
  } else if (items.length > 1) {
    kids.push(el("div", { class: "statuslist" }, items.map(itemStatusChip)));
  }
  if (withHint) kids.push(withHint);
  return kids;
}

const RENDER = {
  // 要タッチ設定時の待受。画面のどこを触っても開始（standbyへ）
  attract(d) {
    const hint = el("p", { class: "hint pulse", html: "画面にタッチしてはじめる" });
    const scr = el("div", { class: "screen", onclick: () => action("start") }, homeContent(d, hint));
    scr.style.cursor = "pointer";
    appEl.replaceChildren(scr);
  },

  standby(d) {
    const hint = el("p", { class: "hint" }, [icon("card", "ico"), el("span", { html: "　社員証をタッチしてください" })]);
    hint.style.display = "inline-flex";
    hint.style.alignItems = "center";
    screenWrap(homeContent(d, hint));
  },

  // 空き物品が複数あるときの物品選択（貸出）
  borrow_item(d) {
    const itemBtn = it => el("button", {
      class: "tonal",
      onclick: () => action("choose_item", { item_id: it.item_id }),
      html: it.location ? `${esc(it.name)}<br><small>${esc(it.location)}</small>` : esc(it.name),
    });
    const kids = [el("p", { class: "title", html: "借りる物品を選んでください" })];
    if (d.groups) {
      for (const g of d.groups) {
        kids.push(el("div", { class: "section-label", html: esc(g.category) }));
        kids.push(el("div", { class: "grid" }, g.items.map(itemBtn)));
      }
    } else {
      kids.push(el("div", { class: "grid" }, (d.items || []).map(itemBtn)));
    }
    kids.push(el("button", { class: "text", onclick: () => action("cancel"), html: "キャンセル" }));
    screenWrap(kids);
  },

  // 本人の未返却が複数あるときの返却物品選択
  return_select(d) {
    const list = el("div", { class: "grid" }, (d.loans || []).map(ln =>
      el("button", {
        class: "tonal",
        onclick: () => action("choose_return", { loan_id: ln.loan_id }),
        html: `${esc(ln.item_name)}<br><small>返却予定: <span class="num">${esc(ln.due_at)}</span></small>`,
      })));
    screenWrap([
      el("p", { class: "title", html: "返却する物品を選んでください" }),
      list,
      el("div", { class: "row" }, [
        el("button", { class: "outlined", onclick: () => action("goto_borrow"), html: "借りる" }),
        el("button", { class: "text", onclick: () => action("cancel"), html: "やめる" }),
      ]),
    ]);
  },

  borrow_time(d) {
    const grid = el("div", { class: "grid" },
      d.choices.map(c => el("button", { class: "tonal", onclick: () => action("choose_duration", { minutes: c.min }), html: c.label })));

    const customToast = el("p", { class: "toast muted" });
    const customInput = el("input", {
      type: "number", inputmode: "numeric",
      min: String(d.custom_min), max: String(d.custom_max),
      placeholder: `${d.custom_min}〜${d.custom_max}`,
    });
    const submitCustom = () => {
      const n = parseInt(customInput.value, 10);
      if (!Number.isInteger(n) || n < d.custom_min || n > d.custom_max) {
        customToast.className = "toast danger";
        customToast.textContent = `${d.custom_min}〜${d.custom_max} の整数（分）を入力してください`;
        return;
      }
      action("choose_duration", { minutes: n });
    };
    const customRow = el("div", { class: "card" }, [
      el("div", { class: "field" }, [el("label", { html: "カスタム（分）" }), customInput]),
      el("button", { class: "small", onclick: submitCustom, html: "この時間で借りる" }),
      customToast,
    ]);

    screenWrap([
      el("p", { class: "title", html: d.item_name ? `${esc(d.item_name)} の貸出時間を選んでください` : "貸出時間を選んでください" }),
      grid,
      customRow,
      el("button", { class: "text", onclick: () => action("cancel"), html: "キャンセル" }),
    ]);
  },

  borrow_confirm(d) {
    screenWrap([
      el("p", { class: "display", html: "借りますか？" }),
      d.item_name ? el("p", { class: "title", text: d.item_name }) : null,
      el("p", { class: "body muted", html: `返却予定: <span class="num">${esc(d.due_at)}</span>` }),
      el("div", { class: "row" }, [
        el("button", { class: "ok", onclick: () => action("confirm_borrow"), html: "開錠する" }),
        el("button", { class: "text", onclick: () => action("cancel"), html: "やめる" }),
      ]),
    ]);
  },

  unlock(d) {
    const msg = d.mode === "borrow" ? "鍵を取り出し、扉を閉めてください" : "鍵を戻し、扉を閉めてください";
    screenWrap([
      el("div", { class: "unlock-banner" }, [
        icon("unlock", "unlock-ico"),
        el("p", { class: "display", html: "解錠しました" }),
        el("p", { class: "title", html: "扉が開いています" }),
      ]),
      d.item_name ? el("p", { class: "title", text: d.item_name }) : null,
      el("p", { class: "body", html: msg }),
      d.due_at ? el("p", { class: "body muted", html: `返却予定: <span class="num">${esc(d.due_at)}</span>` }) : null,
      el("p", { class: "body muted", html: "（数秒後に待機画面へ戻ります）" }),
    ]);
  },

  return_confirm(d) {
    const holdSeconds = d.hold_seconds || 0;
    let okBtn;
    if (holdSeconds > 0) {
      // 誤操作防止のため、タップ＆リリースではなく holdSeconds 秒の長押しで確定する。
      // タイマー自体（誤操作防止の要件）は常に有効にし、見た目のプログレスバーは
      // reduced-motion 環境では滑らかな連続アニメーションにせず、離散的な見た目にする。
      const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const fill = el("span", { class: "hold-fill" });
      const label = el("span", { class: "hold-label", html: `返却する（${holdSeconds}秒長押し）` });
      okBtn = el("button", { class: "ok hold-btn" }, [label, fill]);
      let raf = null, start = 0, active = false;
      const reset = () => {
        active = false;
        if (raf) cancelAnimationFrame(raf);
        fill.style.width = "0%";
      };
      const tick = () => {
        if (!active) return;
        const elapsed = (performance.now() - start) / 1000;
        const pct = Math.min(100, (elapsed / holdSeconds) * 100);
        fill.style.width = reducedMotion ? `${Math.floor(pct / 20) * 20}%` : `${pct}%`;
        if (elapsed >= holdSeconds) {
          active = false;
          action("confirm_return");
          return;
        }
        raf = requestAnimationFrame(tick);
      };
      const startHold = (e) => {
        if (active) return;
        e.preventDefault();
        active = true;
        start = performance.now();
        raf = requestAnimationFrame(tick);
      };
      const endHold = () => reset();
      okBtn.addEventListener("pointerdown", startHold);
      okBtn.addEventListener("pointerup", endHold);
      okBtn.addEventListener("pointerleave", endHold);
      okBtn.addEventListener("pointercancel", endHold);
      // キーボード操作（Enter/Space長押し）でも同じ確定ジェスチャーが効くようにする
      // （ポインタイベントのみだとキーボード/スイッチアクセス利用者が操作できなくなる）。
      okBtn.addEventListener("keydown", (e) => {
        if ((e.key === "Enter" || e.key === " ") && !e.repeat) startHold(e);
      });
      okBtn.addEventListener("keyup", (e) => {
        if (e.key === "Enter" || e.key === " ") endHold();
      });
    } else {
      okBtn = el("button", { class: "ok", onclick: () => action("confirm_return"), html: "返却する" });
    }
    screenWrap([
      el("p", { class: "display", html: "返却しますか？" }),
      d.item_name ? el("p", { class: "title", text: d.item_name }) : null,
      el("p", { class: "body muted", html: `貸出日時: <span class="num">${esc(d.borrowed_at)}</span><br>返却予定: <span class="num">${esc(d.due_at)}</span>` }),
      el("div", { class: "row" }, [
        okBtn,
        el("button", { class: "outlined", onclick: () => action("goto_borrow"), html: "借りる" }),
        el("button", { class: "text", onclick: () => action("cancel"), html: "やめる" }),
      ]),
    ]);
  },

  error(d) {
    // context はサーバ側の軽量な表示ヒント（正式なエラーコードではない）。
    // 未知/未指定の値は何も補足しない（後方互換）。
    const ERROR_CONTEXT_COPY = {
      auth: "社員証が登録されているか確認してください。",
      no_items: "物品の返却を待つか、係員にご相談ください。",
      single_item: "もう一度やり直してください。",
      multi_item: "一覧が更新されています。もう一度選び直してください。",
      hardware: "ハードウェアの異常です。係員にご連絡ください。",
    };
    const sub = ERROR_CONTEXT_COPY[d.context];
    screenWrap([
      icon("alert", "hero-ico danger"),
      el("p", { class: "display danger", html: "エラー" }),
      el("p", { class: "title", text: d.reason || "" }),
      sub ? el("p", { class: "body", text: sub }) : null,
      el("p", { class: "body muted", html: "数秒後に待機画面へ戻ります" }),
    ]);
  },

  // 有効な管理者が1人もいないときだけ出る、初期管理者登録画面
  setup(d) {
    const name = el("input", { value: setupDraft.name, oninput: e => setupDraft.name = e.target.value });
    const emp = el("input", { value: setupDraft.employee_no, oninput: e => setupDraft.employee_no = e.target.value });
    const toast = el("p", { class: "toast muted" });
    const save = async () => {
      const r = await action("register_initial_admin", { name: name.value, employee_no: emp.value });
      toast.className = "toast " + (r.ok ? "ok" : "danger");
      toast.textContent = r.message || "";
      if (r.ok) { setupDraft.name = ""; setupDraft.employee_no = ""; }
    };
    screenWrap([
      el("p", { class: "headline", html: "初期管理者登録" }),
      el("p", { class: "body muted", html: "管理者が未登録のため、最初の管理者を登録してください" }),
      el("div", { class: "card" }, [
        el("div", { class: "field" }, [el("label", { html: "IDm" }),
          el("span", { text: d.idm || "（社員証をタッチ）", class: d.idm ? "" : "muted" })]),
        el("div", { class: "field" }, [el("label", { html: "氏名" }), name]),
        el("div", { class: "field" }, [el("label", { html: "社員番号" }), emp]),
        el("button", { class: "small", onclick: save, html: "管理者として登録" }),
        toast,
      ]),
      el("button", { class: "text", onclick: () => action("cancel"), html: "キャンセル" }),
    ]);
  },

  admin_menu(d) {
    const kids = [];
    // 管理者自身が借りている物品があれば、ここから返却できる
    if (d.can_return) {
      const cnt = d.return_count && d.return_count > 1 ? `（${d.return_count}件）` : "";
      kids.push(el("button", { class: "ok", onclick: () => action("admin_return"), html: `返却する${cnt}` }));
    }
    kids.push(
      el("button", { class: "tonal", onclick: () => action("open_member_admin"), html: "メンバー管理" }),
      el("button", { class: "tonal", onclick: () => action("open_item_admin"), html: "物品管理" }),
      el("button", { class: "tonal", onclick: () => action("open_report"), html: "ログ出力（CSV）" }),
      el("button", { class: "tonal", onclick: () => action("admin_self_borrow"), html: "自分で借りる" }),
      el("button", { class: "text", onclick: () => action("cancel"), html: "終了（待機へ）" }),
    );
    const menu = el("div", { class: "row", }, kids);
    menu.style.flexDirection = "column";
    menu.style.width = "min(520px, 90%)";
    for (const b of kids) b.style.width = "100%";
    // カムスイッチ（施錠検知）が有効なときだけ現在の施錠状態を表示する
    const lockLine = d.lock_state
      ? el("p", {
          class: d.lock_state === "locked" ? "body ok" : "body danger",
          html: d.lock_state === "locked" ? "施錠状態: 施錠されています" : "施錠状態: 未施錠です",
        })
      : null;
    screenWrap([
      el("p", { class: "headline", html: "管理メニュー" }),
      el("p", { class: "body muted", html: d.admin_name ? `管理者: ${esc(d.admin_name)}` : "" }),
      lockLine,
      menu,
    ]);
  },

  item_admin(d) {
    const name = el("input", { value: itemDraft.name, oninput: e => itemDraft.name = e.target.value });
    const loc = el("input", { value: itemDraft.location, oninput: e => itemDraft.location = e.target.value });
    const cat = el("input", { value: itemDraft.category, oninput: e => itemDraft.category = e.target.value });
    const toast = el("p", { class: "toast muted" });
    const add = async () => {
      const r = await action("add_item", { name: name.value, location: loc.value, category: cat.value });
      toast.className = "toast " + (r.ok ? "ok" : "danger");
      toast.textContent = r.message || "";
      if (r.ok) { itemDraft.name = ""; itemDraft.location = ""; itemDraft.category = ""; }
    };
    const card = el("div", { class: "card" }, [
      el("div", { class: "field" }, [el("label", { html: "物品名" }), name]),
      el("div", { class: "field" }, [el("label", { html: "保管場所" }), loc]),
      el("div", { class: "field" }, [el("label", { html: "ジャンル（カテゴリ）" }), cat]),
      el("button", { class: "small", onclick: add, html: "物品を追加" }),
      toast,
    ]);

    const listToast = el("p", { class: "toast muted" });
    const showListResult = (r) => {
      listToast.className = "toast " + (r.ok ? "ok" : "danger");
      listToast.textContent = r.message || "";
    };

    const list = el("div", { class: "mlist" }, (d.items || []).map(it => {
      const ed = itemEdits.get(it.item_id);
      const editName = el("input", { value: ed ? ed.name : it.name, size: 10 });
      const editLoc = el("input", { value: ed ? ed.location : it.location, size: 10 });
      const editCat = el("input", { value: ed ? ed.category : it.category, size: 10, placeholder: "ジャンル" });
      const remember = () => itemEdits.set(it.item_id, { name: editName.value, location: editLoc.value, category: editCat.value });
      editName.addEventListener("input", remember);
      editLoc.addEventListener("input", remember);
      editCat.addEventListener("input", remember);
      const editSave = () => action("update_item", {
        item_id: it.item_id, name: editName.value, location: editLoc.value, category: editCat.value,
      }).then(r => { if (r.ok) itemEdits.delete(it.item_id); showListResult(r); });

      const activeBtn = it.is_active
        ? el("button", { class: "warn small", onclick: () => action("set_item_active", { item_id: it.item_id, active: false }).then(showListResult), html: "無効化" })
        : el("button", { class: "ok small", onclick: () => action("set_item_active", { item_id: it.item_id, active: true }).then(showListResult), html: "有効化" });

      const state = `${it.is_active ? "有効" : "無効"}${it.is_lent ? " / 貸出中" : ""}`;
      return el("div", { class: "item" }, [
        el("span", { html: state, class: "state" }),
        editName, editLoc, editCat,
        el("button", { class: "tonal small", onclick: editSave, html: "保存" }),
        activeBtn,
      ]);
    }));

    adminWrap("物品管理", "admin_menu", [
      el("div", { class: "section-label", html: "物品を追加" }),
      card, listToast,
      el("div", { class: "section-label", html: "登録済み物品" }),
      list,
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
      toast.textContent = r.message || "";
      if (r.ok) { draft.name = ""; draft.employee_no = ""; draft.role = "user"; }
    };

    const card = el("div", { class: "card" }, [
      el("div", { class: "field" }, [el("label", { html: "IDm" }),
        el("span", { text: d.captured_idm || "（社員証をタッチ）", class: d.captured_idm ? "" : "muted" })]),
      el("div", { class: "field" }, [el("label", { html: "氏名" }), name]),
      el("div", { class: "field" }, [el("label", { html: "社員番号" }), emp]),
      el("div", { class: "field" }, [el("label", { html: "ロール" }), roleSel]),
      el("button", { class: "small", onclick: save, html: "保存" }),
      toast,
    ]);

    const listToast = el("p", { class: "toast muted", text: d.reissue_message || "" });
    const showListResult = (r) => {
      listToast.className = "toast " + (r.ok ? "ok" : "danger");
      listToast.textContent = r.message || "";
    };

    const list = el("div", { class: "mlist" }, d.members.map(m => {
      const ed = memberEdits.get(m.member_id);
      const editName = el("input", { value: ed ? ed.name : m.name, size: 8 });
      const editEmp = el("input", { value: ed ? ed.employee_no : m.employee_no, size: 8 });
      const remember = () => memberEdits.set(m.member_id, { name: editName.value, employee_no: editEmp.value });
      editName.addEventListener("input", remember);
      editEmp.addEventListener("input", remember);
      const editSave = () => action("update_member", {
        member_id: m.member_id, name: editName.value, employee_no: editEmp.value,
      }).then(r => { if (r.ok) memberEdits.delete(m.member_id); showListResult(r); });

      const activeBtn = m.is_active
        ? el("button", { class: "warn small", onclick: () => action("set_member_active", { member_id: m.member_id, active: false }).then(showListResult), html: "無効化" })
        : el("button", { class: "ok small", onclick: () => action("set_member_active", { member_id: m.member_id, active: true }).then(showListResult), html: "有効化" });

      const roleBtn = el("button", {
        class: "tonal small",
        onclick: () => action("set_member_role", {
          member_id: m.member_id, role: m.role === "admin" ? "user" : "admin",
        }).then(showListResult),
        html: m.role === "admin" ? "一般へ変更" : "管理者へ変更",
      });

      const reissueBtn = d.reissue_target_id === m.member_id
        ? el("button", { class: "warn small", onclick: () => action("cancel_card_reissue"), html: "カード待ち中（キャンセル）" })
        : el("button", { class: "tonal small", onclick: () => action("start_card_reissue", { member_id: m.member_id }), html: "カード再発行" });

      return el("div", { class: "item" }, [
        el("span", { html: `${m.role} / ${m.is_active ? "有効" : "無効"}`, class: "state" }),
        editName, editEmp,
        el("button", { class: "tonal small", onclick: editSave, html: "保存" }),
        roleBtn, activeBtn, reissueBtn,
      ]);
    }));

    adminWrap("メンバー管理", "admin_menu", [
      el("div", { class: "section-label", html: "メンバーを登録" }),
      card, listToast,
      el("div", { class: "section-label", html: "登録済みメンバー" }),
      list,
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
      toast.textContent = r.message || "";
    };
    adminWrap("ログ出力（CSV）", "admin_menu", [
      el("div", { class: "card" }, [
        el("div", { class: "field" }, [el("label", { html: "開始日" }), start]),
        el("div", { class: "field" }, [el("label", { html: "終了日" }), end]),
        el("div", { class: "field" }, [el("label", { html: "出力先" }), path]),
        el("button", { class: "small", onclick: run, html: "CSVを書き出す" }),
        toast,
      ]),
    ]);
  },
};

function render(state) {
  const fn = RENDER[state.screen];
  // 一覧の行内編集の下書きは、その管理画面を離れたら破棄する（次セッションへ持ち越さない）。
  if (state.screen !== "member_admin") memberEdits.clear();
  if (state.screen !== "item_admin") itemEdits.clear();
  if (fn) fn(state.data || {});
}

// ---- SSE 接続（切断時は自動再接続）----
function connect() {
  const es = new EventSource("/events");
  es.onmessage = (e) => { try { render(JSON.parse(e.data)); } catch {} };
  es.onerror = () => { es.close(); setTimeout(connect, 1000); };
}
connect();

// ---- テーマ（管理者がconfig.jsonで設定。エンドユーザー向けトグルはない）----
// ---- 開発用：疑似カードタッチバー（モックモードのみ）----
fetch("/api/meta").then(r => r.json()).then(meta => {
  if (meta.theme) document.documentElement.setAttribute("data-theme", meta.theme);
  if (!meta.mock) return;
  const bar = document.getElementById("devbar");
  bar.hidden = false;
  const input = el("input", { placeholder: "IDm", size: 16 });
  const touch = (idm) => action("dev_card", { idm });
  bar.append(el("span", { class: "tag", html: "疑似タッチ:" }), input,
    el("button", { onclick: () => touch(input.value.trim()), html: "タッチ" }));
  for (const m of (meta.dev_members || []))
    bar.append(el("button", { onclick: () => touch(m.idm), text: m.name }));
  input.addEventListener("keydown", e => { if (e.key === "Enter") touch(input.value.trim()); });
});
