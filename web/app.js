/* NEKOSTUDIO web UI. Plain ES module, no build step. Talks to the REST API under /api. */

/* ================= helpers ================= */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const root = document.documentElement;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }
};
const v = id => $("#" + id).value;
const n = id => Number(v(id));
const enc = encodeURIComponent;

// set a field value, keeping its paired range slider in sync
function setv(id, val) {
  const el = $("#" + id);
  if (!el || val === undefined || val === null) return;
  el.value = val;
  if (el._range) el._range.value = val;
}

async function api(path, { method = "GET", json, form } = {}) {
  const o = { method, headers: {} };
  if (json !== undefined) { o.body = JSON.stringify(json); o.headers["Content-Type"] = "application/json"; }
  if (form) o.body = form;
  const r = await fetch("/api" + path, o);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* not json */ }
  if (!r.ok) {
    const d = data && (data.detail ?? data.error);
    throw new Error(d ? (typeof d === "string" ? d : JSON.stringify(d)) : `HTTP ${r.status}`);
  }
  return data;
}

function toast(title, msg, bad = false) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  t.innerHTML = `<b>${esc(title)}</b>${esc(msg)}`;
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 5000);
}
const fail = (title, e) => toast(title, e.message || String(e), true);

// fill a <select>; keeps the previous value when it still exists
function fill(sel, items, value, label, keep = true) {
  const old = sel.value;
  sel.innerHTML = items.map(i => `<option value="${esc(value(i))}">${esc(label(i))}</option>`).join("");
  if (keep && items.some(i => value(i) === old)) sel.value = old;
}

const finished = s => s === "done" || s === "error" || s === "cancelled";
const isImage = u => /\.(png|jpe?g|webp|gif)(\?|$)/i.test(u || "");
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const t = document.createElement("textarea");
    t.value = text; document.body.append(t); t.select(); document.execCommand("copy"); t.remove();
  }
  toast("Copied", text.length > 60 ? text.slice(0, 60) + " ..." : text);
}

function download(url) {
  const a = document.createElement("a");
  a.href = url; a.download = url.split("/").pop().split("?")[0]; document.body.append(a); a.click(); a.remove();
}

const fileToDataURL = f => new Promise((ok, no) => {
  const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => no(r.error); r.readAsDataURL(f);
});
async function urlToBlob(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.blob();
}

/* ================= state ================= */
const S = {
  status: null, online: false,
  models: { checkpoints: [], loras: [], vaes: [], video: [] },
  settings: {},
  active: null,        // id of the job Esc will cancel
  section: "create"
};

const SECTIONS = ["create", "models", "motion", "lora", "translate", "gallery", "settings"];

/* ================= icons ================= */
const ICONS = {
  create: '<path d="M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z"/>',
  models: '<path d="M12 3v12M7 10l5 5 5-5M4 19h16"/>',
  motion: '<path d="M3 6h14v12H3z"/><path d="M17 10l4-2.5v9L17 14"/>',
  lora: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 8v8M8 10v4M16 10v4"/>',
  translate: '<path d="M4 6h9M8.5 4v2M6 6c0 4 3 7 6 8M12 6c0 3-3 6-6 8"/><path d="M13 20l4-10 4 10M14.5 16.5h5"/>',
  gallery: '<path d="M3 4h18v16H3z"/><path d="M3 15l5-5 5 5 3-3 5 5M15.5 8.5h.01"/>',
  settings: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><path d="M16 5v4M8 15v4"/>'
};
function initRail() {
  $$(".rb").forEach(b => {
    const id = b.dataset.go;
    $(".ic", b).outerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="miter" aria-hidden="true">${ICONS[id]}</svg>`;
    b.onclick = () => go(id);
  });
}

/* ================= navigation ================= */
function go(id) {
  if (!SECTIONS.includes(id)) id = "create";
  S.section = id;
  SECTIONS.forEach(s => { $("#sec-" + s).hidden = s !== id; });
  $$(".rb").forEach(b => b.classList.toggle("on", b.dataset.go === id));
  history.replaceState(null, "", "#" + id);
  if (id === "gallery") loadGallery(true);
  if (id === "models") loadCatalog();
  if (id === "lora") loraEnter();
  if (id === "settings") drawSettings();
  updateGenerate();
}

/* ================= wallpaper (static, cheap) ================= */
const wall = $("#wall"), wctx = wall.getContext("2d");
let W = 0, H = 0, dpr = Math.min(2, devicePixelRatio || 1), pal = {};

function rng(seed) {
  return () => {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
function readPal() {
  const cs = getComputedStyle(root), g = k => cs.getPropertyValue(k).trim();
  pal = { bg1: g("--bg1"), bg2: g("--bg2"), shard: g("--shard"), edge: g("--edge"), shade: g("--shade"), hex: g("--hexc"), light: root.dataset.skin === "silver" };
}
function hexPath(c, x, y, s) {
  c.beginPath();
  for (let i = 0; i < 6; i++) { const a = Math.PI / 6 + i * Math.PI / 3; c[i ? "lineTo" : "moveTo"](x + s * Math.cos(a), y + s * Math.sin(a)); }
  c.closePath();
}
function drawHexes(c, w, h) {
  const r = rng(11), s = 24 * Math.max(.7, Math.min(w, h) / 800), hw = Math.sqrt(3) * s;
  const cx = w * .8, cy = h * .2;
  c.lineWidth = 1;
  for (let row = 0; row * s * 1.5 < h * .7; row++) {
    for (let col = 0; col * hw < w * .55 + hw; col++) {
      const x = w * .45 + col * hw + (row % 2 ? hw / 2 : 0), y = row * s * 1.5;
      const al = .24 - Math.hypot(x - cx, y - cy) / (Math.min(w, h) * .5) * .2;
      if (al <= .02) continue;
      hexPath(c, x, y, s - 2); c.strokeStyle = `rgba(${pal.hex},${al})`; c.stroke();
      if (r() < .08) { c.fillStyle = `rgba(${pal.hex},${al * .6})`; c.fill(); }
    }
  }
}
function drawShards(c, w, h) {
  const r = rng(7), count = 30, px = w * .30, py = h * .70, R = Math.min(w * .42, h * .62), sc = Math.max(.6, Math.min(w, h) / 800);
  c.globalCompositeOperation = pal.light ? "source-over" : "lighter";
  for (let i = 0; i < count; i++) {
    const k = i / (count - 1), ang = -2.95 + k * 2.7 + (r() - .5) * .08;
    const r0 = (.06 + r() * .26) * R, L = (.45 + r() * .55) * (.55 + .65 * k) * R, tw = (5 + r() * 17) * sc, al = .55 + r() * .45;
    const ux = Math.cos(ang), uy = Math.sin(ang), vx = -uy, vy = ux;
    const P = (u, vv) => [px + ux * u + vx * vv, py + uy * u + vy * vv];
    const A = P(r0, -tw), B = P(r0 + L * .92, -tw * .25), C = P(r0 + L, 0), D = P(r0 + L * .3, tw);
    const gr = c.createLinearGradient(...P(r0, 0), ...C);
    gr.addColorStop(0, `rgba(${pal.shard},0)`);
    gr.addColorStop(.55, `rgba(${pal.shard},${.55 * al * (pal.light ? 1 : .8)})`);
    gr.addColorStop(1, `rgba(${pal.shard},${.9 * al})`);
    c.beginPath(); c.moveTo(...A); c.lineTo(...B); c.lineTo(...C); c.lineTo(...D); c.closePath(); c.fillStyle = gr; c.fill();
    c.globalCompositeOperation = "source-over";
    c.beginPath(); c.moveTo(...A); c.lineTo(...C); c.lineTo(...D); c.closePath(); c.fillStyle = `rgba(${pal.shade},${pal.light ? .12 : .22})`; c.fill();
    c.strokeStyle = `rgba(${pal.edge},${pal.light ? .45 : .35 * al})`; c.lineWidth = .8;
    c.beginPath(); c.moveTo(...A); c.lineTo(...B); c.lineTo(...C); c.stroke();
    c.globalCompositeOperation = pal.light ? "source-over" : "lighter";
  }
  c.globalCompositeOperation = "source-over";
}
function drawWall() {
  W = innerWidth; H = innerHeight;
  wall.width = W * dpr; wall.height = H * dpr;
  readPal();
  const c = wctx;
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  const g = c.createLinearGradient(0, H, W * .9, 0);
  g.addColorStop(0, pal.bg1); g.addColorStop(1, pal.bg2);
  c.fillStyle = g; c.fillRect(0, 0, W, H);
  const vg = c.createRadialGradient(W * .5, H * .5, Math.min(W, H) * .2, W * .5, H * .5, Math.max(W, H) * .75);
  vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, pal.light ? "rgba(40,50,65,.18)" : "rgba(0,0,0,.45)");
  c.fillStyle = vg; c.fillRect(0, 0, W, H);
  drawHexes(c, W, H);
  drawShards(c, W, H);
}
let wallTimer = 0;
addEventListener("resize", () => { clearTimeout(wallTimer); wallTimer = setTimeout(drawWall, 150); });

/* ================= appearance (skin / accent / motion) ================= */
const SKINS = [
  { id: "mine", n: "Mine", a: "#050607", b: "#2a2f37", c: "#d4ebff" },
  { id: "amber", n: "Amber", a: "#b84d05", b: "#f8cf96", c: "#ffb04a" },
  { id: "silver", n: "Silver", a: "#aeb5bf", b: "#f6f7f9", c: "#2c5b88" },
  { id: "verdant", n: "Verdant", a: "#062a0c", b: "#79d24f", c: "#b9ff8c" }
];
const ACCENTS = [
  ["Pink", "#ff3d7f"], ["Vermilion", "#ff5a36"], ["Gold", "#ffc23d"], ["Acid", "#c6ff3d"],
  ["Mint", "#3dffb0"], ["Cyan", "#3dd8ff"], ["Blue", "#4d7cff"], ["Violet", "#a66bff"]
];
const look = { skin: store.get("ns.skin", "mine"), accent: store.get("ns.accent", ""), motion: store.get("ns.motion", "1") === "1" };

// Ultimit's rule: dark text on the accent if its luminance is above 0.18
function luminance(hex) {
  const m = /^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(hex);
  if (!m) return 0;
  const [r, g, b] = m.slice(1).map(x => { const c = parseInt(x, 16) / 255; return c <= .03928 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; });
  return .2126 * r + .7152 * g + .0722 * b;
}
function applyLook() {
  if (look.skin === "mine") root.removeAttribute("data-skin"); else root.setAttribute("data-skin", look.skin);
  if (look.accent) {
    root.style.setProperty("--accent", look.accent);
    root.style.setProperty("--on-accent", luminance(look.accent) > .18 ? "#07090b" : "#ffffff");
  } else {
    root.style.removeProperty("--accent"); root.style.removeProperty("--on-accent");
  }
  document.body.classList.toggle("nomotion", !look.motion);
  drawWall();
}
let saveTimer = 0;
function setLook(patch) {
  Object.assign(look, patch);
  store.set("ns.skin", look.skin); store.set("ns.accent", look.accent); store.set("ns.motion", look.motion ? "1" : "0");
  applyLook(); drawSettings();
  // mirror into settings.json (quietly) so it follows the install
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    if (!S.online) return;
    api("/settings", { method: "PUT", json: { ...S.settings, skin: look.skin, accent: look.accent, motion: look.motion } })
      .then(s => { S.settings = s; }).catch(() => {});
  }, 600);
}

/* ================= sliders ================= */
function initSliders() {
  $$(".sl").forEach(el => {
    const { id, label, min, max, step, val } = el.dataset;
    el.className = "field sl";
    el.innerHTML = `<label for="${id}">${label}</label><div class="slr"><input type="range" min="${min}" max="${max}" step="${step}" value="${val}" aria-label="${label}"><input type="number" class="num" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}"></div>`;
    const range = $("input[type=range]", el), num = $("#" + id, el);
    num._range = range;
    range.addEventListener("input", () => { num.value = range.value; num.dispatchEvent(new Event("change", { bubbles: true })); });
    num.addEventListener("input", () => { range.value = num.value; });
  });
}

/* ================= image drop zones ================= */
const drops = {};          // id -> data URL (single-image zones)
const dropFiles = {};      // id -> callback for multi-file zones

function setDrop(id, dataUrl) {
  const el = $(`[data-drop="${id}"]`);
  if (dataUrl) drops[id] = dataUrl; else delete drops[id];
  el.innerHTML = dataUrl
    ? `<img src="${dataUrl}" alt="init image"><button class="btn sm" type="button" data-clear>CLEAR</button>`
    : (el.dataset.multi ? "Drop images here or click to upload" : "Drop an image or click");
  const clr = $("[data-clear]", el);
  if (clr) clr.onclick = e => { e.stopPropagation(); setDrop(id, null); };
}
function initDrops() {
  $$(".drop[data-drop]").forEach(el => {
    const id = el.dataset.drop, multi = !!el.dataset.multi;
    const input = document.createElement("input");
    input.type = "file"; input.accept = "image/*"; input.multiple = multi; input.hidden = true;
    el.after(input);
    const take = async files => {
      files = [...files].filter(f => f.type.startsWith("image/"));
      if (!files.length) return;
      if (multi) dropFiles[id]?.(files); else setDrop(id, await fileToDataURL(files[0]));
    };
    el.onclick = () => input.click();
    input.onchange = () => { take(input.files); input.value = ""; };
    el.ondragover = e => { e.preventDefault(); el.classList.add("over"); };
    el.ondragleave = () => el.classList.remove("over");
    el.ondrop = e => { e.preventDefault(); el.classList.remove("over"); take(e.dataTransfer.files); };
  });
}

/* ================= jobs (SSE with polling fallback) ================= */
const watchers = new Map();
const jobs = {};
let es = null;

function dispatch(job) {
  jobs[job.id] = job;
  const fn = watchers.get(job.id);
  if (fn) fn(job);
  if (finished(job.state)) { watchers.delete(job.id); if (S.active === job.id) S.active = null; }
  renderTicker();
}
function connectEvents() {
  if (!window.EventSource) return;
  es = new EventSource("/api/events");
  es.onmessage = e => { try { dispatch(JSON.parse(e.data)); } catch { /* ignore bad frame */ } };
}
// poll tracked jobs whenever the event stream is not delivering
setInterval(() => {
  if (es && es.readyState === 1) return;
  watchers.forEach((_, id) => api(`/jobs/${id}`).then(dispatch).catch(() => {}));
}, 1500);

function paint(p, job) {
  const pct = Math.round((job.progress || 0) * 100);
  const bar = $(`#${p}-bar`), txt = $(`#${p}-pct`);
  if (bar) bar.style.width = pct + "%";
  if (!txt) return;
  if (job.state === "error") txt.textContent = "ERROR " + (job.error || job.message || "");
  else txt.textContent = `${job.state.toUpperCase()} ${pct}%` + (job.total ? ` | ${job.step}/${job.total}` : "") + (job.message ? ` | ${job.message}` : "");
}
// follow a job: ui = { p: bar prefix, update(job), end(job) }
function track(id, ui) {
  S.active = id;
  watchers.set(id, job => {
    paint(ui.p, job);
    ui.update?.(job);
    if (finished(job.state)) {
      if (job.state === "error") toast("Job failed", job.error || job.message || "unknown error", true);
      if (job.state === "cancelled") toast("Cancelled", "Job cancelled");
      ui.end?.(job);
    }
  });
  api(`/jobs/${id}`).then(dispatch).catch(() => {});
}
async function cancelActive() {
  if (!S.active) return;
  try { await api(`/jobs/${S.active}/cancel`, { method: "POST" }); } catch (e) { fail("Cancel", e); }
}

/* ================= status / ticker ================= */
const chip = (text, cls) => `<span class="chip ${cls}">${text}</span>`;

function renderChips() {
  const st = S.status;
  let html = chip("API " + (S.online ? "ONLINE" : "OFFLINE"), S.online ? "ok" : "bad");
  if (st) {
    html += chip(st.gpu ? esc(st.gpu.name).replace(/NVIDIA |GeForce /g, "") : "NO GPU", st.gpu ? "ok" : "warn");
    html += chip("TORCH", st.torch ? "ok" : "warn") + chip("DIFFUSERS", st.diffusers ? "ok" : "warn") + chip("TRAIN", st.train_ready ? "ok" : "dim");
    html += chip(st.busy ? `BUSY +${st.queue || 0}` : "IDLE", st.busy ? "warn" : "dim");
  }
  $("#chips").innerHTML = html;
  $("#ver").textContent = st?.version ? "NEKOSTUDIO " + st.version : "NEKOSTUDIO";
}
function renderTicker() {
  const st = S.status, parts = [];
  if (!S.online) parts.push("<b>BACKEND OFFLINE</b> | retrying");
  else if (st) {
    parts.push(st.gpu ? `GPU <b>${esc(st.gpu.name)}</b>` : "GPU <b>none</b>");
    if (st.gpu) parts.push(`VRAM <b>${Math.round((st.gpu.vram_total_mb - st.gpu.vram_free_mb))}/${st.gpu.vram_total_mb} MB</b>`);
    parts.push(`QUEUE <b>${st.queue || 0}</b>`);
  }
  const j = S.active && jobs[S.active];
  if (j) parts.push(`JOB <b>${esc(j.kind)} ${j.state} ${Math.round((j.progress || 0) * 100)}%</b>`);
  $("#tickm").innerHTML = parts.join(" &nbsp;|&nbsp; ");
}
async function pollStatus() {
  try { S.status = await api("/status"); S.online = true; }
  catch { S.online = false; }
  renderChips(); renderTicker(); updateGenerate(); updateTrainGate();
}
function clock() {
  const d = new Date(), p = x => String(x).padStart(2, "0");
  $("#clock").textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  $("#date").textContent = `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][d.getDay()]}`;
}

/* ================= models + settings load ================= */
async function refreshModels() {
  try { S.models = { checkpoints: [], loras: [], vaes: [], video: [], ...(await api("/models")) }; }
  catch { /* keep the old lists */ }
  const m = S.models;
  fill($("#c-ckpt"), m.checkpoints, c => c.name, c => c.name);
  fill($("#l-base"), m.checkpoints, c => c.name, c => c.name);
  fill($("#q-base"), m.checkpoints, c => c.name, c => c.name);
  if (!Q.baseTouched) { const pick = m.checkpoints.find(c => c.pony) || m.checkpoints[0]; if (pick) $("#q-base").value = pick.name; }
  fill($("#c-vae"), [{ name: "" }, ...m.vaes], x => x.name, x => x.name || "(built-in)");
  fill($("#m-model"), m.video, x => x.id, x => (x.label || x.id) + (x.installed === false ? " (not installed)" : ""));
  S.ready = true;
  renderLoraList(); renderEmpties(); updateQuickGate();
  $$(".lrow select").forEach(sel => fillLoraSelect(sel));
  onCkptChange(false);
  updateGenerate();
}
async function loadSettings() {
  try { S.settings = await api("/settings") || {}; } catch { return; }
  const s = S.settings;
  // localStorage wins; otherwise adopt what the install remembers
  if (!store.get("ns.skin", "") && s.skin) look.skin = s.skin;
  if (!store.get("ns.accent", "") && s.accent) look.accent = s.accent;
  if (s.motion !== undefined && store.get("ns.motion", "") === "") look.motion = !!s.motion;
  applyLook();
  if (!v("c-neg") && s.default_negative) setv("c-neg", s.default_negative);
}

/* ================= CREATE ================= */
const NEG_PRESETS = {
  pony: "score_6, score_5, score_4, ugly, deformed, bad anatomy, bad hands, extra fingers, missing fingers, worst quality, low quality, watermark, text, signature",
  anime: "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, jpeg artifacts, signature, watermark, username, blurry",
  realistic: "cartoon, anime, illustration, painting, drawing, 3d render, deformed, disfigured, bad anatomy, extra limbs, blurry, low quality, watermark, text"
};
const SIZES = ["1024x1024", "832x1216", "1216x832", "896x1152", "1152x896"];
const SAMPLERS = ["euler_a", "euler", "dpmpp_2m", "dpmpp_2m_karras", "dpmpp_sde_karras", "ddim", "unipc"];
const cr = { items: [], sel: -1, lastSeed: null, undo: null };

function curCkpt() { return S.models.checkpoints.find(c => c.name === v("c-ckpt")); }
function onCkptChange(userAction) {
  const ck = curCkpt();
  $("#c-ponychip").hidden = !(ck && ck.pony);
  if (userAction && ck) { $("#c-pony").checked = !!ck.pony; setv("c-clip", ck.pony ? 2 : 1); }
}

function fillLoraSelect(sel, keep) {
  const old = keep ?? sel.value;
  const names = S.models.loras.map(l => l.name);
  if (old && !names.includes(old)) names.unshift(old);   // reused params may name a missing LoRA
  sel.innerHTML = names.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
  if (old) sel.value = old;
}
function addLoraRow(name = "", weight = 0.8) {
  if (!name && !S.models.loras.length) { toast("LoRA", "No LoRAs found in data/models/loras", true); return; }
  const row = document.createElement("div");
  row.className = "lrow";
  row.innerHTML = `<select aria-label="LoRA"></select><input type="range" min="-2" max="2" step="0.05" aria-label="Weight"><input type="number" class="num" min="-2" max="2" step="0.05" aria-label="Weight value"><button class="btn sm x" type="button" aria-label="Remove">&times;</button>`;
  const sel = $("select", row), rng = $("input[type=range]", row), num = $("input[type=number]", row);
  fillLoraSelect(sel, name);
  rng.value = num.value = weight;
  rng.oninput = () => { num.value = rng.value; };
  num.oninput = () => { rng.value = num.value; };
  $(".x", row).onclick = () => row.remove();
  $("#c-loras").append(row);
}
function getLoras() {
  return $$("#c-loras .lrow").map(r => ({ name: $("select", r).value, weight: Number($("input[type=number]", r).value) })).filter(l => l.name);
}

function initCreate() {
  fill($("#c-size"), [...SIZES.map(s => ({ v: s, l: s.replace("x", " x ") })), { v: "custom", l: "custom" }], x => x.v, x => x.l);
  fill($("#c-sampler"), SAMPLERS, x => x, x => x);
  setv("c-neg", NEG_PRESETS.pony);
  $("#c-size").onchange = () => {
    $("#c-custom").hidden = v("c-size") !== "custom";
  };
  $("#c-ckpt").onchange = () => onCkptChange(true);
  $("#c-addlora").onclick = () => addLoraRow();
  $("#c-negpre").onchange = e => { if (NEG_PRESETS[e.target.value]) setv("c-neg", NEG_PRESETS[e.target.value]); e.target.value = ""; updateGenerate(); };
  $("#c-dice").onclick = () => setv("c-seed", -1);
  $("#c-recycle").onclick = () => { if (cr.lastSeed !== null) setv("c-seed", cr.lastSeed); else toast("Seed", "No previous seed yet"); };
  $("#c-topony").onclick = toPony;
  $("#c-undo").onclick = () => {
    if (!cr.undo) return;
    setv("c-prompt", cr.undo.prompt); setv("c-neg", cr.undo.negative);
    cr.undo = null; $("#c-undo").disabled = true; updateGenerate();
  };
  $("#c-go").onclick = generateImage;
  $("#c-cancel").onclick = cancelActive;
  $("#c-save").onclick = () => cr.items[cr.sel] && download(cr.items[cr.sel].url);
  $("#c-reuse").onclick = () => cr.items[cr.sel] && applyParams(cr.items[cr.sel].meta);
  $("#c-tomotion").onclick = () => sendToMotion(cr.items[cr.sel]?.url);
  $("#c-todata").onclick = () => sendToDataset(cr.items[cr.sel]?.url);
  $("#sec-create").addEventListener("input", updateGenerate);
}

// run the prompt through the rule/LLM translator, keep the old text for undo
async function toPony() {
  const text = v("c-prompt").trim();
  if (!text) return;
  try {
    const r = await api("/translate", { method: "POST", json: { text, mode: "auto", source: v("t-source"), rating: v("t-rating") } });
    cr.undo = { prompt: v("c-prompt"), negative: v("c-neg") };
    $("#c-undo").disabled = false;
    setv("c-prompt", r.prompt);
    if (r.negative && !v("c-neg").trim()) setv("c-neg", r.negative);
    if (r.note) toast("Translate", r.note);
    updateGenerate();
  } catch (e) { fail("Translate", e); }
}

function sizeOf(id, customW, customH) {
  const s = v(id);
  if (s === "custom") return [n(customW), n(customH)];
  return s.split("x").map(Number);
}
function imageBody() {
  const [width, height] = sizeOf("c-size", "c-w", "c-h");
  const body = {
    prompt: v("c-prompt"), negative: v("c-neg"), checkpoint: v("c-ckpt"),
    loras: getLoras(), width, height, steps: n("c-steps"), cfg: n("c-cfg"), sampler: v("c-sampler"),
    seed: Math.trunc(n("c-seed")), batch: n("c-batch"), clip_skip: n("c-clip"), pony: $("#c-pony").checked
  };
  if (v("c-vae")) body.vae = v("c-vae");
  if (drops["c-init"]) { body.init_image = drops["c-init"]; body.strength = n("c-str"); }
  return body;
}

// why GENERATE is disabled in a section ("" when it can run)
function whyNot(kind) {
  if (!S.online) return "Backend offline. Start it with ./run.sh (run.bat on Windows).";
  const st = S.status;
  if (st && !st.torch) return "PyTorch is not installed. Run ./setup.sh (setup.bat on Windows).";
  if (st && !st.diffusers) return "diffusers is not installed. Run ./setup.sh (setup.bat on Windows).";
  if (kind === "image") {
    if (!v("c-ckpt")) return "No model yet. Download one in MODELS.";
    if (!v("c-prompt").trim()) return "Enter a prompt.";
  } else {
    if (!v("m-model")) return "No video model is configured.";
    const vm = S.models.video.find(x => x.id === v("m-model"));
    if (vm && vm.in_catalog && vm.installed === false) return "This video model is not downloaded yet. Get it in MODELS.";
    if (!v("m-prompt").trim() && !drops["m-init"]) return "Enter a prompt.";
  }
  return "";
}
function updateGenerate() {
  const busyC = $("#c-cancel").dataset.busy === "1", busyM = $("#m-cancel").dataset.busy === "1";
  const wc = whyNot("image"), wm = whyNot("video");
  $("#c-go").disabled = !!wc || busyC; $("#c-why").textContent = wc;
  $("#m-go").disabled = !!wm || busyM; $("#m-why").textContent = wm;
}
function setBusy(p, on) {
  $(`#${p}-cancel`).dataset.busy = on ? "1" : "";
  $(`#${p}-cancel`).disabled = !on;
  updateGenerate();
}

async function generateImage() {
  if ($("#c-go").disabled) return;
  try {
    const { job_id } = await api("/generate/image", { method: "POST", json: imageBody() });
    cr.items = []; cr.sel = -1; renderThumbs();
    setBusy("c", true);
    track(job_id, {
      p: "c",
      update: job => { if (job.results?.length) setResults(job.results); },
      end: job => { if (job.results?.length) setResults(job.results); setBusy("c", false); }
    });
  } catch (e) { fail("Generate", e); }
}
function setResults(results) {
  const had = cr.items.length;
  cr.items = results;
  if (cr.sel < 0 || results.length > had) selectResult(results.length - 1);
  renderThumbs();
  const seed = results[0]?.meta?.seed;
  if (seed !== undefined) cr.lastSeed = seed;
}
function selectResult(i) {
  cr.sel = i;
  const it = cr.items[i];
  $("#c-stage").innerHTML = it ? `<img src="${esc(it.url)}" alt="result">` : '<div class="ph">No image yet</div>';
  ["c-save", "c-reuse", "c-tomotion", "c-todata"].forEach(id => { $("#" + id).disabled = !it; });
  renderThumbs();
}
function renderThumbs() {
  const box = $("#c-thumbs");
  box.innerHTML = "";
  cr.items.forEach((it, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = i === cr.sel ? "sel" : "";
    b.style.backgroundImage = `url("${it.thumb || it.url}")`;
    b.setAttribute("aria-label", "Result " + (i + 1));
    b.onclick = () => selectResult(i);
    box.append(b);
  });
}

// fill the CREATE form from a saved meta object (gallery / REUSE PARAMS)
function applyParams(meta) {
  if (!meta) return;
  go("create");
  setv("c-prompt", meta.prompt); setv("c-neg", meta.negative);
  if (meta.checkpoint && S.models.checkpoints.some(c => c.name === meta.checkpoint)) { setv("c-ckpt", meta.checkpoint); onCkptChange(false); }
  if (meta.vae !== undefined && $$("#c-vae option").some(o => o.value === meta.vae)) setv("c-vae", meta.vae);
  if (meta.width && meta.height) {
    const key = `${meta.width}x${meta.height}`;
    if (SIZES.includes(key)) { setv("c-size", key); $("#c-custom").hidden = true; }
    else { setv("c-size", "custom"); $("#c-custom").hidden = false; setv("c-w", meta.width); setv("c-h", meta.height); }
  }
  setv("c-steps", meta.steps); setv("c-cfg", meta.cfg);
  if (SAMPLERS.includes(meta.sampler)) setv("c-sampler", meta.sampler);
  setv("c-seed", meta.seed); setv("c-batch", meta.batch); setv("c-clip", meta.clip_skip);
  if (meta.pony !== undefined) $("#c-pony").checked = !!meta.pony;
  $("#c-loras").innerHTML = "";
  (meta.loras || []).forEach(l => addLoraRow(l.name, l.weight));
  updateGenerate();
  toast("Params", "Settings restored");
}

async function sendToMotion(url) {
  if (!url) return;
  try { setDrop("m-init", await fileToDataURL(await urlToBlob(url))); go("motion"); toast("Motion", "Image set as init frame"); }
  catch (e) { fail("To motion", e); }
}

/* ---- send an image to a dataset (dialog) ---- */
async function sendToDataset(url) {
  if (!url) return;
  let list = [];
  try { list = await api("/datasets") || []; } catch (e) { fail("Datasets", e); return; }
  fill($("#dlg-sel"), [{ name: "" }, ...list], d => d.name, d => d.name || "(choose)", false);
  $("#dlg-new").value = "";
  const dlg = $("#dlg");
  dlg.returnValue = "";
  dlg.onclose = async () => {
    if (dlg.returnValue !== "ok") return;
    const name = $("#dlg-new").value.trim() || v("dlg-sel");
    if (!name) return;
    try {
      if (!list.some(d => d.name === name)) await api("/datasets", { method: "POST", json: { name } });
      const blob = await urlToBlob(url);
      await uploadFiles(name, [new File([blob], url.split("/").pop().split("?")[0], { type: blob.type })]);
      toast("Dataset", `Added to ${name}`);
    } catch (e) { fail("Dataset", e); }
  };
  dlg.showModal();
}

/* ================= MODELS (catalog downloads + import) ================= */
const D = { items: [], free: null, loaded: false, watching: new Set() };
const gbText = g => g >= 1 ? `${g.toFixed(1)} GB` : `${Math.round(g * 1000)} MB`;
const entry = id => D.items.find(e => e.id === id);

async function loadCatalog() {
  try { const r = await api("/catalog"); D.items = r.items || []; D.free = r.disk_free_gb; D.loaded = true; }
  catch { return; }
  D.items.forEach(e => { if (e.job_id) watchDl(e, e.job_id); });
  renderModels(); renderEmpties();
}

// the DOWNLOAD button / progress bar / INSTALLED chip of one entry
function dlBox(e) {
  let inner;
  if (e.installed) inner = '<small class="chip ok">INSTALLED</small>';
  else if (e.job_id) {
    const pct = Math.round((e._pct || 0) * 100);
    inner = `<div class="meter"><i class="dlbar" style="width:${pct}%"></i></div><div class="dlrow"><span class="dltxt">${esc(e._txt || "starting ...")}</span><button class="btn sm" data-dl-cancel="${esc(e.id)}" type="button">CANCEL</button></div>`;
  } else inner = `<button class="btn pri sm" data-dl-start="${esc(e.id)}" type="button">DOWNLOAD</button>`;
  return `<div class="dlbox" data-dl="${esc(e.id)}">${inner}</div>`;
}
function rebox(e) {
  $$(`.dlbox[data-dl="${e.id}"]`).forEach(b => { b.outerHTML = dlBox(e); });
}
function modelCard(e) {
  const tag = e.kind === "checkpoint" || e.kind === "video" ? e.family : e.kind;
  return `<div class="card mc${e.recommended ? " rec" : ""}"><div class="mch"><b>${esc(e.label)}</b><small class="chip dim">${esc(tag.toUpperCase())}</small>${e.recommended ? '<small class="chip ok">RECOMMENDED</small>' : ""}</div>`
    + `<span>${esc(e.note)}</span><div class="mcs">${gbText(e.size_gb)}</div>${dlBox(e)}</div>`;
}
function renderModels() {
  const groups = { "d-ckpt": e => e.kind === "checkpoint", "d-video": e => e.kind === "video", "d-extra": e => ["vae", "tagger", "tags", "llm"].includes(e.kind) };
  for (const [id, f] of Object.entries(groups)) $("#" + id).innerHTML = D.items.filter(f).map(modelCard).join("");
  const fr = $("#d-free");
  fr.textContent = D.free == null ? "" : `${D.free} GB FREE`;
  fr.className = "chip " + (D.free != null && D.free < 15 ? "warn" : "dim");
}

// follow one catalog download; progress updates touch only the bar and text
function watchDl(e, jobId) {
  e.job_id = jobId;
  if (D.watching.has(jobId)) return;
  D.watching.add(jobId);
  watchers.set(jobId, async job => {
    e._pct = job.progress; e._txt = job.message;
    $$(`.dlbox[data-dl="${e.id}"] .dlbar`).forEach(b => { b.style.width = Math.round((job.progress || 0) * 100) + "%"; });
    $$(`.dlbox[data-dl="${e.id}"] .dltxt`).forEach(t => { t.textContent = job.message || ""; });
    if (!finished(job.state)) return;
    D.watching.delete(jobId); e.job_id = null; e._pct = 0; e._txt = "";
    rebox(e);
    if (job.state === "done") toast("Download", `${e.label} is installed`);
    else if (job.state === "error") toast("Download failed", job.error || job.message || "unknown error", true);
    else toast("Cancelled", "Start it again later and it resumes where it stopped");
    await refreshModels(); await loadCatalog();
  });
  api(`/jobs/${jobId}`).then(dispatch).catch(() => {});
}
async function startDl(id) {
  const e = entry(id);
  if (!e) return;
  try {
    const { job_id } = await api(`/catalog/${enc(id)}/download`, { method: "POST" });
    watchDl(e, job_id); rebox(e);
  } catch (err) { fail("Download", err); }
}
async function cancelDl(id) {
  const e = entry(id);
  if (!e || !e.job_id) return;
  try { await api(`/jobs/${e.job_id}/cancel`, { method: "POST" }); } catch (err) { fail("Cancel", err); }
}

// big "No model yet" card in CREATE / MOTION
function renderEmpties() {
  if (!S.ready || !D.loaded) return;
  const fill1 = (el, kind, need, title, text) => {
    const e = D.items.find(x => x.kind === kind && x.recommended);
    el.hidden = !(need && e);
    if (el.hidden) { el.innerHTML = ""; el.dataset.for = ""; return; }
    if (el.dataset.for === e.id && el.dataset.inst === String(e.installed)) return;   // keep a running progress bar alone
    el.dataset.for = e.id; el.dataset.inst = String(e.installed);
    el.innerHTML = `<h3>${esc(title)}</h3><p>${esc(text)} <b>${esc(e.label)}</b> (${gbText(e.size_gb)}) is the one we suggest.</p>${dlBox(e)}<div class="acts"><button class="btn sm" data-go-models type="button">SEE ALL MODELS</button></div>`;
  };
  fill1($("#c-empty"), "checkpoint", !S.models.checkpoints.length, "No model yet", "You need a model before you can make pictures. One click and it downloads in the background while you look around.");
  fill1($("#m-empty"), "video", !S.models.video.some(x => x.installed !== false), "No video model yet", "Motion needs a video model.");
}

/* import: links and .safetensors files */
function watchImport(jobId, p) {
  watchers.set(jobId, async job => {
    paint(p, job);
    if (!finished(job.state)) return;
    if (job.state === "done") toast("Import", job.message);
    else if (job.state === "error") toast("Import failed", job.error || job.message || "unknown error", true);
    else toast("Cancelled", "Import cancelled");
    await refreshModels(); await loadCatalog();
  });
  api(`/jobs/${jobId}`).then(dispatch).catch(() => {});
}
async function importUrl(input, kind, p) {
  const url = input.value.trim();
  if (!url) return;
  try {
    const { job_id } = await api("/import/url", { method: "POST", json: { url, kind } });
    input.value = ""; watchImport(job_id, p);
  } catch (e) { fail("Import", e); }
}
function initFileDrop(el, getKind, p) {
  const input = document.createElement("input");
  input.type = "file"; input.accept = ".safetensors"; input.multiple = true; input.hidden = true;
  el.after(input);
  const take = async files => {
    for (const f of [...files]) {
      if (!/\.safetensors$/i.test(f.name)) { toast("Import", `${f.name}: only .safetensors files are accepted`, true); continue; }
      $(`#${p}-pct`).textContent = `UPLOADING ${f.name} ...`; $(`#${p}-bar`).style.width = "100%";
      const form = new FormData();
      form.append("file", f, f.name); form.append("kind", getKind());
      try {
        const r = await api("/import/file", { method: "POST", form });
        toast("Import", `${r.name} added`);
      } catch (e) { fail("Import", e); }
    }
    $(`#${p}-pct`).textContent = ""; $(`#${p}-bar`).style.width = "0";
    await refreshModels(); await loadCatalog();
  };
  el.onclick = () => input.click();
  input.onchange = () => { take(input.files); input.value = ""; };
  el.ondragover = e => { e.preventDefault(); el.classList.add("over"); };
  el.ondragleave = () => el.classList.remove("over");
  el.ondrop = e => { e.preventDefault(); el.classList.remove("over"); take(e.dataTransfer.files); };
}

function initModels() {
  $("#d-import").onclick = () => importUrl($("#d-url"), v("d-kind"), "di");
  $("#d-url").onkeydown = e => { if (e.key === "Enter") importUrl($("#d-url"), v("d-kind"), "di"); };
  initFileDrop($("#d-drop"), () => v("d-kind"), "di");
  initFileDrop($("#li-drop"), () => "lora", "li");
  $("#li-go").onclick = () => importUrl($("#li-url"), "lora", "li");
  $("#li-url").onkeydown = e => { if (e.key === "Enter") importUrl($("#li-url"), "lora", "li"); };
  document.addEventListener("click", async ev => {
    const t = ev.target;
    const st = t.closest?.("[data-dl-start]"), ca = t.closest?.("[data-dl-cancel]"), gm = t.closest?.("[data-go-models]"), de = t.closest?.("[data-lora-del]");
    if (st) startDl(st.dataset.dlStart);
    else if (ca) cancelDl(ca.dataset.dlCancel);
    else if (gm) go("models");
    else if (de) {
      const name = de.dataset.loraDel;
      if (!confirm(`Delete LoRA "${name}"?`)) return;
      try { await api("/models/lora/" + name.split("/").map(enc).join("/"), { method: "DELETE" }); await refreshModels(); }
      catch (e) { fail("Delete", e); }
    }
  });
}

function renderLoraList() {
  const list = S.models.loras;
  $("#li-count").textContent = list.length + " installed";
  $("#li-list").innerHTML = list.length ? list.map(l => `<div class="lirow"><span title="${esc(l.name)}">${esc(l.name)}</span><button class="btn sm" data-lora-del="${esc(l.name)}" type="button">DELETE</button></div>`).join("")
    : '<div class="note" style="padding:10px 6px">No LoRAs yet. Train one above or import one.</div>';
}

/* ================= MOTION ================= */
const mo = { url: null };

function initMotion() {
  $("#m-dice").onclick = () => setv("m-seed", -1);
  $("#m-go").onclick = generateVideo;
  $("#m-cancel").onclick = cancelActive;
  $("#m-save").onclick = () => mo.url && download(mo.url);
  $("#sec-motion").addEventListener("input", updateGenerate);
}
async function generateVideo() {
  if ($("#m-go").disabled) return;
  const [width, height] = v("m-size").split("x").map(Number);
  const body = {
    prompt: v("m-prompt"), negative: v("m-neg"), model: v("m-model"), width, height,
    frames: n("m-frames"), fps: n("m-fps"), steps: n("m-steps"), cfg: n("m-cfg"), seed: Math.trunc(n("m-seed"))
  };
  if (drops["m-init"]) body.init_image = drops["m-init"];
  try {
    const { job_id } = await api("/generate/video", { method: "POST", json: body });
    setBusy("m", true);
    track(job_id, { p: "m", end: job => { showVideo(job.results?.[0]); setBusy("m", false); } });
  } catch (e) { fail("Generate", e); }
}
function showVideo(res) {
  if (!res) return;
  mo.url = res.url;
  $("#m-stage").innerHTML = `<video src="${esc(res.url)}" poster="${esc(res.thumb || "")}" loop autoplay muted controls playsinline></video>`;
  $("#m-save").disabled = false;
}

/* ================= LORA wizard (behind EDIT TAGS / ADVANCED) ================= */
const PRESETS = {
  character: { dim: 16, alpha: 16, lr: "2e-4", epochs: 10, repeats: 10 },
  style: { dim: 32, alpha: 16, lr: "1.5e-4", epochs: 12, repeats: 5 },
  concept: { dim: 16, alpha: 16, lr: "2e-4", epochs: 10, repeats: 8 }
};
const L = { ds: null, items: [], list: [], step: 1, preset: "character", loss: [], lastMsg: "" };

const dsUrl = (name, rest = "") => `/datasets/${enc(name)}${rest}`;

function initLora() {
  $$("#l-steps button").forEach(b => { b.onclick = () => loraStep(+b.dataset.step); });
  $("#l-create").onclick = createDataset;
  $("#l-newname").onkeydown = e => { if (e.key === "Enter") createDataset(); };
  dropFiles["l-files"] = files => { if (!L.ds) return toast("Dataset", "Select or create a dataset first", true); doUpload(files); };
  $("#l-next1").onclick = () => loraStep(2);
  $("#l-back2").onclick = () => loraStep(1);
  $("#l-next2").onclick = () => loraStep(3);
  $("#l-back3").onclick = () => loraStep(2);
  $("#l-auto").onclick = autoCaption;
  $("#l-tagadd").onclick = () => bulkTag(true);
  $("#l-tagdel").onclick = () => bulkTag(false);
  $("#l-trigger").oninput = () => { if (L.ds) store.set("ns.trigger." + L.ds, v("l-trigger")); };
  $$("#l-presets .card").forEach(c => { c.onclick = () => setPreset(c.dataset.preset); });
  $("#l-adv").onchange = () => { $("#l-advbox").hidden = !$("#l-adv").checked; };
  $("#l-base").onchange = setDefaultRes;
  $("#l-train").onclick = startTraining;
  $("#l-stop").onclick = cancelActive;
  $("#l-cmdcopy").onclick = () => copyText($("#l-cmd").textContent);
  $("#sec-lora").addEventListener("input", updateTrainGate);
  $("#l-cmd").textContent = /win/i.test(navigator.platform || navigator.userAgent) ? "setup.bat" : "./setup.sh";
  setPreset("character");
}
function loraEnter() { loadDatasets(); renderLoraList(); updateTrainGate(); }

function loraStep(s) {
  if (s > 1 && !L.ds) { toast("Dataset", "Select or create a dataset first", true); s = 1; }
  L.step = s;
  [1, 2, 3].forEach(i => { $("#l-s" + i).hidden = i !== s; });
  $$("#l-steps button").forEach(b => b.classList.toggle("on", +b.dataset.step === s));
  if (s === 2) renderCards();
  if (s === 3) setDefaultRes();
  updateTrainGate();
}

async function loadDatasets() {
  const box = $("#l-dslist");
  try {
    const list = await api("/datasets") || [];
    $("#l-dscount").textContent = list.length + " total";
    L.list = list;
    $("#q-ds").innerHTML = list.map(d => `<option value="${esc(d.name)}"></option>`).join("");
    box.innerHTML = list.length ? "" : '<div class="note" style="padding:10px 6px">No datasets yet. Create one below.</div>';
    list.forEach(d => {
      const r = document.createElement("button");
      r.type = "button"; r.className = "row" + (d.name === L.ds ? " sel" : "");
      r.style.gridTemplateColumns = "minmax(0,1fr) auto auto";
      r.innerHTML = `<span>${esc(d.name)}</span><span class="chip dim">${d.images} IMG</span><span class="chip ${d.captioned >= d.images && d.images ? "ok" : "warn"}">${d.captioned} CAP</span>`;
      r.onclick = () => selectDataset(d.name);
      box.append(r);
    });
  } catch (e) { box.innerHTML = `<div class="note" style="padding:10px 6px">Could not load datasets: ${esc(e.message)}</div>`; }
}
async function createDataset() {
  const name = v("l-newname").trim().replace(/[^\w.-]+/g, "_");
  if (!name) return;
  try { await api("/datasets", { method: "POST", json: { name } }); setv("l-newname", ""); await selectDataset(name); }
  catch (e) { fail("Dataset", e); }
}
async function selectDataset(name) {
  L.ds = name;
  if (v("q-name") !== name) { setv("q-name", name); $("#q-trig").textContent = name; }
  try {
    const d = await api(dsUrl(name));
    L.items = d.items || [];
    setv("l-trigger", store.get("ns.trigger." + name, d.trigger || ""));
  } catch (e) { L.items = []; fail("Dataset", e); }
  if (!v("l-name")) setv("l-name", name);
  renderDatasetInfo();
  loadDatasets();
}
function renderDatasetInfo() {
  const c = L.items.length;
  renderQuick();
  $("#l-count").textContent = L.ds ? `${L.ds} | ${c} images` : "";
  $("#l-next1").disabled = !L.ds || c === 0;
  $("#l-warn").textContent = !L.ds ? "Select or create a dataset." : c < 10 ? `Only ${c} images. 10 or more gives much better results.` : c > 200 ? `${c} images is a lot. Training will be slow, 200 or fewer is plenty.` : "";
  const cap = L.items.filter(i => (i.caption || "").trim()).length;
  $("#l-capstat").textContent = L.ds ? `${cap}/${c} captioned` : "";
  updateTrainGate();
}
async function uploadFiles(name, files) {
  const form = new FormData();
  files.forEach(f => form.append("files[]", f, f.name));
  return api(dsUrl(name, "/upload"), { method: "POST", form });
}
async function doUpload(files) {
  try {
    const r = await uploadFiles(L.ds, files);
    toast("Upload", `${r?.added ?? files.length} images added`);
    await selectDataset(L.ds);
  } catch (e) { fail("Upload", e); }
}

function renderCards() {
  const box = $("#l-cards");
  box.innerHTML = "";
  L.items.forEach(it => {
    const card = document.createElement("div");
    card.className = "dcard";
    card.innerHTML = `<img loading="lazy" src="${esc(it.url)}" alt=""><textarea aria-label="Caption for ${esc(it.file)}">${esc(it.caption)}</textarea><button class="x" type="button" title="Delete image">&times;</button>`;
    const ta = $("textarea", card);
    ta.onchange = () => saveCaption(it, ta.value);
    $(".x", card).onclick = async () => {
      try { await api(dsUrl(L.ds, `/item/${enc(it.file)}`), { method: "DELETE" }); L.items = L.items.filter(x => x !== it); card.remove(); renderDatasetInfo(); }
      catch (e) { fail("Delete", e); }
    };
    box.append(card);
  });
  renderDatasetInfo();
}
async function saveCaption(it, caption) {
  it.caption = caption;
  try { await api(dsUrl(L.ds, "/caption"), { method: "PUT", json: { file: it.file, caption } }); renderDatasetInfo(); }
  catch (e) { fail("Caption", e); }
}
const splitTags = s => (s || "").split(",").map(t => t.trim()).filter(Boolean);

// add or remove one tag on every caption
async function bulkTag(add) {
  const tag = v("l-tag").trim();
  if (!tag || !L.items.length) return;
  let changed = 0;
  for (const it of L.items) {
    const tags = splitTags(it.caption), has = tags.includes(tag);
    if (add === has) continue;
    await saveCaption(it, (add ? [...tags, tag] : tags.filter(t => t !== tag)).join(", "));
    changed++;
  }
  renderCards();
  toast("Captions", `${add ? "Added to" : "Removed from"} ${changed} captions`);
}
async function autoCaption() {
  const body = { threshold: n("l-thresh"), overwrite: $("#l-over").checked };
  if (v("l-trigger").trim()) body.trigger = v("l-trigger").trim();
  try {
    const { job_id } = await api(dsUrl(L.ds, "/autocaption"), { method: "POST", json: body });
    $("#l-auto").disabled = true;
    track(job_id, { p: "k", end: async () => { $("#l-auto").disabled = false; await selectDataset(L.ds); renderCards(); } });
  } catch (e) { fail("Auto-caption", e); }
}

function setPreset(name) {
  L.preset = name;
  $$("#l-presets .card").forEach(c => c.classList.toggle("sel", c.dataset.preset === name));
  const p = PRESETS[name];
  ["dim", "alpha", "lr", "epochs", "repeats"].forEach(k => setv("l-" + k, p[k]));
}
function setDefaultRes() {
  const ck = S.models.checkpoints.find(c => c.name === v("l-base"));
  setv("l-res", ck && ck.kind === "sd15" ? 512 : 1024);
}
function updateTrainGate() {
  const st = S.status, ready = !st || st.train_ready;     // unknown status: do not nag
  $("#l-setup").hidden = ready;
  $("#l-ready").textContent = !st ? "" : st.train_ready ? "TRAINER READY" : "TRAINER NOT SET UP";
  $("#l-ready").className = "chip " + (st && st.train_ready ? "ok" : "warn");
  let why = "";
  if (!S.online) why = "Backend offline.";
  else if (st && !st.train_ready) why = "Training environment missing. Run the setup command above.";
  else if (!L.ds) why = "Choose a dataset in step 1.";
  else if (!v("l-name").trim()) why = "Give the LoRA a name.";
  else if (!v("l-base")) why = "No base checkpoint found.";
  $("#l-why").textContent = why;
  const busy = $("#l-stop").dataset.busy === "1";
  $("#l-train").disabled = !!why || busy;
  updateQuickGate();
}

async function startTraining() {
  if ($("#l-train").disabled) return;
  const body = {
    dataset: L.ds, name: v("l-name").trim().replace(/[^\w.-]+/g, "_"), base_checkpoint: v("l-base"),
    preset: L.preset, trigger: v("l-trigger").trim()
  };
  if ($("#l-adv").checked) {
    body.overrides = { dim: n("l-dim"), alpha: n("l-alpha"), lr: Number(v("l-lr")), epochs: n("l-epochs"), repeats: n("l-repeats"), resolution: n("l-res") };
  }
  try {
    const { job_id } = await api("/train", { method: "POST", json: body });
    L.loss = []; L.lastMsg = "";
    $("#l-samples").innerHTML = ""; $("#l-done").textContent = ""; drawSpark();
    $("#l-stop").dataset.busy = "1"; $("#l-stop").disabled = false; updateTrainGate();
    track(job_id, {
      p: "t", update: trainUpdate,
      end: async job => {
        trainUpdate(job);
        $("#l-stop").dataset.busy = ""; $("#l-stop").disabled = true; updateTrainGate();
        if (job.state === "done") {
          $("#l-done").textContent = `LoRA "${body.name}" is ready and listed in CREATE.`;
          toast("Training", "LoRA finished");
          await refreshModels();
        }
      }
    });
  } catch (e) { fail("Train", e); }
}
function trainUpdate(job) {
  // message looks like "epoch 3/10 loss 0.123"
  if (job.message && job.message !== L.lastMsg) {
    L.lastMsg = job.message;
    const m = /loss[:\s]+([\d.]+(?:e-?\d+)?)/i.exec(job.message);
    if (m) { L.loss.push(Number(m[1])); drawSpark(); $("#l-lossnow").textContent = m[1]; }
  }
  const imgs = (job.results || []).filter(r => isImage(r.url));
  $("#l-samples").innerHTML = imgs.map(r => `<img src="${esc(r.thumb || r.url)}" alt="sample">`).join("");
}
function drawSpark() {
  const d = L.loss;
  const line = $("#l-spark polyline");
  if (d.length < 2) { line.setAttribute("points", ""); return; }
  const lo = Math.min(...d), hi = Math.max(...d), span = hi - lo || 1;
  line.setAttribute("points", d.map((y, i) => `${(i / (d.length - 1) * 300).toFixed(1)},${(55 - (y - lo) / span * 50).toFixed(1)}`).join(" "));
}

/* ================= LORA: simple one-screen flow ================= */
const Q = { type: "character", baseTouched: false, result: null };
const qName = () => v("q-name").trim().replace(/[^\w-]+/g, "_");

function initQuick() {
  $$("#q-types .card").forEach(c => { c.onclick = () => { Q.type = c.dataset.type; $$("#q-types .card").forEach(x => x.classList.toggle("sel", x === c)); }; });
  $("#q-name").oninput = () => { $("#q-trig").textContent = qName() || "-"; renderQuick(); updateQuickGate(); };
  $("#q-name").onchange = qLoadDataset;
  $("#q-base").onchange = () => { Q.baseTouched = true; updateQuickGate(); };
  dropFiles["q-files"] = qUpload;
  $("#q-train").onclick = startQuick;
  $("#q-stop").onclick = cancelActive;
  $("#q-try").onclick = tryLora;
  $("#l-more").onclick = () => {
    const wz = $("#l-wizard");
    wz.hidden = !wz.hidden;
    $("#l-more").setAttribute("aria-expanded", String(!wz.hidden));
    if (!wz.hidden) {
      if (!v("l-name") && qName()) setv("l-name", qName());
      loadDatasets(); loraStep(L.ds ? 2 : 1);
    }
  };
}
async function qLoadDataset() {
  const name = qName();
  if (!name) return;
  if ((L.list || []).some(d => d.name === name)) await selectDataset(name);
  else { L.ds = null; L.items = []; renderDatasetInfo(); }
}
async function qUpload(files) {
  const name = qName();
  if (!/^[A-Za-z0-9][\w-]*$/.test(name)) return toast("LoRA", "Give your LoRA a name first (letters, digits, - and _)", true);
  try {
    await api("/datasets", { method: "POST", json: { name } });
    const r = await uploadFiles(name, files);
    toast("Pictures", `${r?.added ?? files.length} added`);
    await selectDataset(name);
    if (!v("l-trigger")) setv("l-trigger", name);
  } catch (e) { fail("Upload", e); }
}
// thumbnails + count of the dataset that belongs to the typed name
function renderQuick() {
  const name = qName(), mine = L.ds === name, items = mine ? L.items : [], c = items.length;
  $("#q-thumbs").innerHTML = items.map(it => `<div><img loading="lazy" src="${esc(it.url)}" alt=""><button class="x" type="button" data-file="${esc(it.file)}" title="Remove" aria-label="Remove">&times;</button></div>`).join("");
  $$("#q-thumbs .x").forEach(b => {
    b.onclick = async () => {
      try { await api(dsUrl(L.ds, `/item/${enc(b.dataset.file)}`), { method: "DELETE" }); L.items = L.items.filter(i => i.file !== b.dataset.file); renderDatasetInfo(); loadDatasets(); }
      catch (e) { fail("Delete", e); }
    };
  });
  $("#q-count").textContent = c ? `${c} picture${c === 1 ? "" : "s"}` : "";
  $("#q-warn").textContent = !name || !c ? "" : c < 10 ? `Only ${c}. Use at least 10; 15 to 40 works best.` : c < 15 ? "Good start. 15 to 40 pictures works best." : c > 200 ? `${c} pictures is a lot and will train slowly. 15 to 40 is plenty.` : "";
}
function updateQuickGate() {
  const st = S.status, name = qName(), c = L.ds === name ? L.items.length : 0;
  let why = "";
  if (!S.online) why = "Backend offline.";
  else if (st && !st.train_ready) why = "Training environment missing. Run the setup command above.";
  else if (!name) why = "Give your LoRA a name.";
  else if (!/^[A-Za-z0-9]/.test(name)) why = "The name must start with a letter or digit.";
  else if (!c) why = "Add some pictures first.";
  else if (!v("q-base")) why = "No base model yet. Download one in MODELS.";
  $("#q-why").textContent = why;
  $("#q-train").disabled = !!why || $("#q-stop").dataset.busy === "1";
}
async function startQuick() {
  if ($("#q-train").disabled) return;
  const name = qName();
  try {
    const { job_id } = await api("/lora/quick", { method: "POST", json: { name, type: Q.type, base_checkpoint: v("q-base") } });
    Q.result = null; $("#q-done").hidden = true; $("#q-samples").innerHTML = "";
    $("#q-stop").dataset.busy = "1"; $("#q-stop").disabled = false; updateQuickGate();
    track(job_id, {
      p: "q",
      update: job => {
        if (job.state !== "error") $("#q-pct").textContent = `${job.state.toUpperCase()} ${Math.round((job.progress || 0) * 100)}%${job.message ? " | " + job.message : ""}`;
        $("#q-samples").innerHTML = (job.results || []).filter(r => isImage(r.url)).map(r => `<img src="${esc(r.thumb || r.url)}" alt="sample">`).join("");
      },
      end: async job => {
        $("#q-stop").dataset.busy = ""; $("#q-stop").disabled = true; updateQuickGate();
        if (job.state !== "done") return;
        await refreshModels();
        const res = (job.results || []).find(r => r.meta?.kind === "lora");
        Q.result = { file: res?.meta.name || name + ".safetensors", trigger: res?.meta.trigger || name, base: v("q-base") };
        $("#q-donetxt").textContent = `"${name}" is ready.`;
        $("#q-done").hidden = false;
        toast("LoRA ready", `${name} finished training`);
      }
    });
  } catch (e) { fail("Train", e); }
}
// jump to CREATE with the new LoRA at 0.8 and its trigger word in the prompt
function tryLora() {
  const r = Q.result;
  if (!r) return;
  go("create");
  if (r.base && S.models.checkpoints.some(c => c.name === r.base)) { setv("c-ckpt", r.base); onCkptChange(true); }
  if (!getLoras().some(l => l.name === r.file)) addLoraRow(r.file, 0.8);
  const p = v("c-prompt");
  if (!p.toLowerCase().includes(r.trigger.toLowerCase())) setv("c-prompt", r.trigger + (p.trim() ? ", " + p : ""));
  updateGenerate();
}

/* ================= TRANSLATE ================= */
const tr = { mode: "auto", tags: [], status: null };

function initTranslate() {
  $$("#t-mode button").forEach(b => {
    b.onclick = () => { tr.mode = b.dataset.v; $$("#t-mode button").forEach(x => x.classList.toggle("on", x === b)); };
  });
  $("#t-go").onclick = runTranslate;
  loadTrStatus();
  $("#t-dl").addEventListener("click", ev => { if (ev.target.closest("[data-tr-dl]")) downloadTranslator(); });
  $("#t-copy").onclick = () => copyText(v("t-prompt"));
  $("#t-use").onclick = () => {
    if (!v("t-prompt").trim()) return;
    setv("c-prompt", v("t-prompt"));
    if (v("t-neg").trim()) setv("c-neg", v("t-neg"));
    go("create");
  };
}
// is the local translator (model + tag lists) installed? offer a one-click download when it is not
async function loadTrStatus() {
  try { tr.status = await api("/translate/status"); } catch { return; }
  renderTrCard();
}
function renderTrCard() {
  const st = tr.status, box = $("#t-dl");
  if (!st || tr.dlBusy) return;
  const need = st.missing || [];
  box.hidden = !need.length;
  if (!need.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<h3>Better translations</h3><p>Download the local translator (${esc(need.map(e => e.label).join(", "))}) to get real booru tags. It runs on the CPU, so it never competes with image generation.</p>`
    + `<div class="acts"><button class="btn pri" data-tr-dl type="button">DOWNLOAD TRANSLATOR (${gbText(st.missing_gb)})</button></div>`;
}
// the three files go through the single download lane, one after another
async function downloadTranslator() {
  const st = tr.status;
  if (!st || !st.missing.length) return;
  tr.dlBusy = true;
  const box = $("#t-dl");
  box.innerHTML = '<h3>Downloading translator</h3><div class="meter"><i id="t-dlbar" style="width:0%"></i></div><div class="mono mute" id="t-dltxt" style="font-size:11px">starting ...</div>';
  try {
    const jobs = [];
    for (const m of st.missing) {
      const { job_id } = await api(`/catalog/${enc(m.id)}/download`, { method: "POST" });
      jobs.push({ id: job_id, label: m.label });
    }
    const states = {};
    await new Promise(res => {
      jobs.forEach(j => watchers.set(j.id, job => {
        states[j.id] = job;
        const cur = jobs.find(x => !finished((states[x.id] || {}).state)) || jobs[jobs.length - 1];
        const cj = states[cur.id] || job;
        $("#t-dlbar") && ($("#t-dlbar").style.width = Math.round((cj.progress || 0) * 100) + "%");
        $("#t-dltxt") && ($("#t-dltxt").textContent = `${cur.label}: ${cj.message || ""}`);
        if (jobs.every(x => finished((states[x.id] || {}).state))) res();
        return true;
      }));
      jobs.forEach(j => api(`/jobs/${j.id}`).then(dispatch).catch(() => {}));
    });
    const bad = Object.values(states).find(j => j.state === "error");
    if (bad) toast("Download failed", bad.error || bad.message || "unknown error", true);
    else toast("Translator", "Installed");
  } catch (e) { fail("Download", e); }
  tr.dlBusy = false;
  await loadTrStatus(); await loadCatalog();
}
const trFixed = fx => (fx || []).map(f => `${esc(f.from)} \u2192 ${esc(f.to)}`).join(" | ") || "-";

async function runTranslate() {
  const text = v("t-text").trim();
  if (!text) return;
  $("#t-go").disabled = true;
  try {
    const r = await api("/translate", { method: "POST", json: { text, mode: tr.mode, source: v("t-source"), rating: v("t-rating") } });
    setv("t-prompt", r.prompt || ""); setv("t-neg", r.negative || "");
    tr.tags = r.tags || [];
    $("#t-dropped").textContent = (r.dropped || []).join(" | ") || "-";
    $("#t-fixed").innerHTML = trFixed(r.fixed);
    $("#t-engine").textContent = r.engine ? `engine: ${r.engine}` : "";
    $("#t-note").textContent = r.note || "";
    renderTags();
  } catch (e) { fail("Translate", e); }
  $("#t-go").disabled = false;
}
function renderTags() {
  const box = $("#t-tags");
  box.innerHTML = "";
  tr.tags.forEach(t => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = t;
    b.onclick = () => {
      tr.tags = tr.tags.filter(x => x !== t);
      setv("t-prompt", splitTags(v("t-prompt")).filter(x => x !== t).join(", "));
      renderTags();
    };
    box.append(b);
  });
}

/* ================= GALLERY ================= */
const G = { kind: "image", offset: 0, total: 0, items: [], busy: false };
const PAGE = 60;

function initGallery() {
  $$("#g-tabs button").forEach(b => {
    b.onclick = () => { G.kind = b.dataset.v; $$("#g-tabs button").forEach(x => x.classList.toggle("on", x === b)); closeFly(); loadGallery(true); };
  });
  $("#g-more").onclick = () => loadGallery(false);
}
async function loadGallery(reset) {
  if (G.busy) return;
  G.busy = true;
  if (reset) { G.offset = 0; G.items = []; $("#g-grid").innerHTML = ""; }
  try {
    const r = await api(`/gallery?kind=${G.kind}&offset=${G.offset}&limit=${PAGE}`);
    G.total = r.total ?? 0;
    G.items.push(...(r.items || []));
    G.offset = G.items.length;
    r.items.forEach(addTile);
    $("#g-sub").textContent = `${G.total} ${G.kind}s`;
  } catch (e) { $("#g-sub").textContent = "unavailable"; if (reset) toast("Gallery", e.message, true); }
  $("#g-more").hidden = G.items.length >= G.total;
  $("#g-empty").hidden = G.items.length > 0;
  G.busy = false;
}
function addTile(it) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "gt"; b.dataset.id = it.id;
  b.style.backgroundImage = `url("${it.thumb || it.url}")`;
  if (it.kind === "video") b.innerHTML = '<span class="chip dim">VIDEO</span>';
  b.onclick = () => openFly(it);
  $("#g-grid").append(b);
}
function openFly(it) {
  const fly = $("#g-fly"), m = it.meta || {};
  const rows = Object.entries(m).map(([k, val]) => `<dt>${esc(k)}</dt><dd>${esc(typeof val === "object" ? JSON.stringify(val) : val)}</dd>`).join("");
  fly.innerHTML = `<div class="hrow"><span class="lbl">${esc(it.kind)} | ${esc(it.created || "")}</span><button class="btn sm" id="f-close" type="button" style="margin-left:auto">CLOSE</button></div>
    <div class="stage">${it.kind === "video" ? `<video src="${esc(it.url)}" loop autoplay muted controls playsinline></video>` : `<img src="${esc(it.url)}" alt="">`}</div>
    <div class="acts"><button class="btn pri" id="f-reuse" type="button">REUSE</button><button class="btn" id="f-dl" type="button">DOWNLOAD</button><button class="btn" id="f-del" type="button">DELETE</button></div>
    <dl class="kv">${rows}</dl>`;
  fly.hidden = false;
  $("#f-close").onclick = closeFly;
  $("#f-dl").onclick = () => download(it.url);
  $("#f-reuse").onclick = () => {
    if (it.kind === "video") { go("motion"); setv("m-prompt", m.prompt); setv("m-neg", m.negative); setv("m-seed", m.seed); setv("m-steps", m.steps); setv("m-cfg", m.cfg); }
    else applyParams(m);
    closeFly();
  };
  $("#f-del").onclick = async () => {
    if (!confirm("Delete this file permanently?")) return;
    try {
      await api(`/gallery/${enc(it.id)}`, { method: "DELETE" });
      G.items = G.items.filter(x => x !== it); G.offset = G.items.length; G.total--;
      $(`.gt[data-id="${CSS.escape(it.id)}"]`)?.remove();
      closeFly();
      $("#g-empty").hidden = G.items.length > 0;
    } catch (e) { fail("Delete", e); }
  };
}
function closeFly() { $("#g-fly").hidden = true; $("#g-fly").innerHTML = ""; }

/* ================= SETTINGS ================= */
function drawSettings() {
  const sk = $("#s-skins");
  sk.innerHTML = SKINS.map(s => `<button class="skin${s.id === look.skin ? " sel" : ""}" data-id="${s.id}" type="button"><div class="pv" style="background:linear-gradient(120deg,${s.a},${s.b})"><i style="background:${s.c}"></i></div><div class="nm">${s.n}</div></button>`).join("");
  $$("button", sk).forEach(b => { b.onclick = () => setLook({ skin: b.dataset.id }); });

  const acc = $("#s-acc");
  acc.innerHTML = '<button class="sw rst' + (look.accent ? "" : " sel") + '" data-c="" type="button" title="Use the skin accent">SKIN</button>'
    + ACCENTS.map(([nm, c]) => `<button class="sw${look.accent.toLowerCase() === c ? " sel" : ""}" data-c="${c}" title="${nm}" aria-label="${nm}" style="background:${c}" type="button"></button>`).join("")
    + `<input type="color" id="s-custom" value="${look.accent || "#ff3d7f"}" aria-label="Custom accent">`;
  $$("button", acc).forEach(b => { b.onclick = () => setLook({ accent: b.dataset.c }); });
  $("#s-custom").onchange = e => setLook({ accent: e.target.value });

  $("#s-motion").checked = look.motion;
  $("#s-motion").onchange = e => setLook({ motion: e.target.checked });
}
// fill the system fields from the loaded settings (only when entering the page)
function fillSettingsForm() {
  const s = S.settings, llm = s.llm || {};
  setv("s-url", llm.base_url ?? ""); setv("s-model", llm.model ?? ""); setv("s-key", llm.api_key ?? "");
  setv("s-gpul", s.llm_gpu_layers ?? 0);
  setv("s-civ", s.civitai_token ?? ""); setv("s-vram", s.vram_mode || "auto"); setv("s-defneg", s.default_negative ?? "");
  const paths = s.paths && typeof s.paths === "object" ? Object.entries(s.paths) : [["data", "./data (or $NEKOSTUDIO_HOME)"]];
  $("#s-paths").innerHTML = paths.map(([k, val]) => `<dt>${esc(k)}</dt><dd class="mono">${esc(val)}</dd>`).join("");
}
async function saveSettings() {
  const next = {
    ...S.settings,
    llm: { ...(S.settings.llm || {}), base_url: v("s-url"), model: v("s-model"), api_key: v("s-key") },
    llm_gpu_layers: Math.trunc(n("s-gpul")), civitai_token: v("s-civ"), vram_mode: v("s-vram"), default_negative: v("s-defneg"),
    skin: look.skin, accent: look.accent, motion: look.motion
  };
  try { S.settings = await api("/settings", { method: "PUT", json: next }); fillSettingsForm(); toast("Settings", "Saved"); }
  catch (e) { fail("Settings", e); }
}
function initSettings() {
  $("#s-save").onclick = saveSettings;
  drawSettings();
}

/* ================= keyboard ================= */
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    if (S.section === "create") generateImage();
    else if (S.section === "motion") generateVideo();
    else if (S.section === "translate") runTranslate();
    else if (S.section === "lora") { if (!$("#l-wizard").hidden && L.step === 3) startTraining(); else startQuick(); }
  } else if (e.key === "Escape") {
    if ($("#dlg").open) return;                        // the dialog handles its own Esc
    if (!$("#g-fly").hidden) closeFly(); else cancelActive();
  }
});

/* ================= start ================= */
async function start() {
  applyLook();
  initRail(); initSliders(); initDrops();
  initCreate(); initMotion(); initModels(); initLora(); initQuick(); initTranslate(); initGallery(); initSettings();
  clock(); setInterval(clock, 1000);
  go(location.hash.slice(1) || "create");
  connectEvents();
  await pollStatus();
  setInterval(pollStatus, 5000);
  await Promise.all([refreshModels(), loadSettings(), loadCatalog()]);
  fillSettingsForm();
}
start();
