const { invoke } = window.__TAURI__.core;
const { open, save } = window.__TAURI__.dialog;
const { listen } = window.__TAURI__.event;

// macOS 用 Overlay 标题栏，需要给红绿灯留出位置
if (/Mac/i.test(navigator.userAgent)) {
  document.documentElement.classList.add("is-mac");
}

const $ = (id) => document.getElementById(id);

// 多语言：取不到 I18N 时直接返回 key，调用方都有中文兜底，不会渲染成空白
const tr = (key, vars) => (window.I18N ? I18N.t(key, vars) : key);

// 顶部栏拖动窗口
const topbar = document.querySelector(".topbar");
topbar.addEventListener("mousedown", (event) => {
  if (event.button !== 0) return;
  if (event.target.closest("button, input, select, textarea")) return;
  window.__TAURI__.window.getCurrentWindow().startDragging();
});
topbar.addEventListener("dblclick", (event) => {
  if (event.target.closest("button, input, select, textarea")) return;
  window.__TAURI__.window.getCurrentWindow().toggleMaximize();
});

/* ---------------- 页面切换 ---------------- */

function showPage(name) {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.page === name);
  });
  document.querySelectorAll(".page").forEach((page) => {
    page.hidden = page.dataset.page !== name;
  });
}
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});

function setStatus(text, kind = "") {
  const node = $("status");
  node.textContent = text;
  node.className = `status ${kind}`;
}

/* 所有会改动文件的操作都提交到后台任务队列，界面只负责提交与清空。 */

let toastTimer = null;
function notifySubmitted() {
  const node = $("submitToast");
  if (!node) return;
  node.innerHTML = `<b>${escapeHtml(tr("status.submitted"))}</b>`;
  node.hidden = false;
  requestAnimationFrame(() => node.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.classList.remove("show");
    setTimeout(() => {
      node.hidden = true;
    }, 200);
  }, 4000);
}

async function submitTask(kind, params, title, source = "gui") {
  await invoke("submit_task", { kind, params, source, title });
  notifySubmitted();
  refreshTaskBadge();
}

const IS_MAC = /Mac/i.test(navigator.userAgent);

/**
 * 选文件：macOS 走系统自带面板，不做扩展名过滤（`.MOV` 这类大写后缀在插件面板里会被卡掉）；
 * 其它平台或系统面板不可用时回退到应用内对话框，同样放开所有文件。
 * 选完能不能用交给 checkMedia 让后端判断，不再维护扩展名白名单。
 */
async function pickFile() {
  if (IS_MAC) {
    try {
      return (await invoke("pick_media_file")) || null;
    } catch (error) {
      console.warn("[pick] 系统面板不可用，回退到应用内对话框：", error);
    }
  }
  return (await open({ multiple: false })) || null;
}

/**
 * 后端检测：ffprobe 看这个文件里有没有音轨 / 画面。
 * kind 为 "audio" 时要求有音轨；"media" 时音视频有其一即可。
 */
async function checkMedia(path, kind) {
  let probe;
  try {
    probe = await invoke("media_probe", { path });
  } catch (error) {
    setStatus(tr("status.bad_file", { error }), "err");
    return false;
  }
  if (kind === "audio" && !probe.audio) {
    setStatus(tr(probe.video ? "status.no_audio_video_only" : "status.no_audio"), "err");
    return false;
  }
  if (kind === "media" && !probe.audio && !probe.video) {
    setStatus(tr("status.no_av"), "err");
    return false;
  }
  return true;
}

function baseName(path) {
  return path.split(/[\\/]/).pop() || path;
}

function stripExt(name) {
  return name.replace(/\.[^.]+$/, "");
}

function humanSize(bytes) {
  if (!bytes) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function humanDuration(seconds) {
  if (!seconds) return "-";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function buildName(title, artist, pattern) {
  const t = (title || "").trim();
  const a = (artist || "").trim();
  let name;
  switch (pattern) {
    case "title_only":
      name = t;
      break;
    case "artist_only":
      name = a;
      break;
    case "title_artist":
      name = `${t} - ${a}`;
      break;
    default:
      name = `${a} - ${t}`;
  }
  name = name.replace(/^[\s-]+|[\s-]+$/g, "");
  if (!name) return null;
  return name.replace(/[/\\:*?"<>|]/g, "_");
}

/* ---------------- 转写 ---------------- */

const el = {
  drop: $("drop"),
  file: $("file"),
  model: $("model"),
  lang: $("lang"),
  suppress: $("suppress"),
  nocontext: $("nocontext"),
  separate: $("separate"),
  vad: $("vad"),
  run: $("run"),
  bar: $("bar"),
  pct: $("pct"),
  text: $("text"),
  copy: $("copy"),
  saveTxt: $("saveTxt"),
  saveSrt: $("saveSrt"),
  saveLrc: $("saveLrc"),
  advReset: $("advReset"),
  remember: $("remember"),
  mcpEnabled: $("mcpEnabled"),
  coreml: $("coremlEnabled"),
  coremlMissing: $("coremlMissing"),
  debugLog: $("debugLog"),
  settingsPath: $("settingsPath"),
  logsPath: $("logsPath"),
  openLogs: $("openLogs"),
  openTasks: $("openTasks"),
  taskBadge: $("taskBadge"),
  taskConcurrency: $("taskConcurrency"),
  openModels: $("openModels"),
  openLicenses: $("openLicenses"),
  localeSelect: $("localeSelect"),
};

/* ---------------- 界面语言 ---------------- */

// 语言包在 i18n.js 里，这里只负责把设置页的下拉框接上去。
function setupLocaleSelect() {
  const select = el.localeSelect;
  if (!select || !window.I18N) return;

  // 「跟随系统」随界面语言换文案，所以每次语言变化都要重建一遍选项
  const rebuild = () => {
    select.innerHTML = "";
    const system = document.createElement("option");
    system.value = I18N.SYSTEM;
    system.textContent = I18N.t("settings.language_system");
    select.append(system);
    for (const item of I18N.supported) {
      const option = document.createElement("option");
      option.value = item.code;
      option.textContent = item.label;
      select.append(option);
    }
    select.value = I18N.choice();
  };

  rebuild();
  document.addEventListener("localechange", rebuild);
  select.addEventListener("change", async () => {
    await I18N.setLocale(select.value);
  });
}

// 刷新模型下拉：用户目录 + 随包资源目录里的 ggml 模型都会被列出。
async function loadModels(preserve = true) {
  try {
    const models = await invoke("list_models");
    const previous = preserve ? el.model.value : "";
    el.model.innerHTML = models
      .map((name) => `<option value="${name}">${name.replace(".bin", "")}</option>`)
      .join("");
    if (previous && models.includes(previous)) el.model.value = previous;
    if (!models.length) {
      let dir = "";
      try {
        dir = await invoke("models_dir");
      } catch (_) {}
      setStatus(
        dir ? tr("transcribe.no_model", { dir }) : tr("transcribe.no_model_plain"),
        "err"
      );
    }
  } catch (error) {
    setStatus(tr("transcribe.list_failed", { error }), "err");
  }
}

let audioPath = null;
let result = { text: "", srt: "" };

const advFields = {
  prompt: $("advPrompt"),
  carry_prompt: $("advCarry"),
  no_fallback: $("advNoFallback"),
  beam_size: $("advBeam"),
  best_of: $("advBest"),
  no_speech_thold: $("advNth"),
  entropy_thold: $("advEt"),
  logprob_thold: $("advLpt"),
  word_thold: $("advWt"),
  max_len: $("advMl"),
};

const setting = { remember: true, mcpEnabled: true, debugLog: false, coreml: true, ui: {} };

function readAdvanced() {
  const num = (node) => {
    const raw = node.value.trim();
    if (!raw) return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  };
  return {
    prompt: advFields.prompt.value.trim() || null,
    carry_prompt: advFields.carry_prompt.checked,
    no_fallback: advFields.no_fallback.checked,
    beam_size: num(advFields.beam_size),
    best_of: num(advFields.best_of),
    no_speech_thold: num(advFields.no_speech_thold),
    entropy_thold: num(advFields.entropy_thold),
    logprob_thold: num(advFields.logprob_thold),
    word_thold: num(advFields.word_thold),
    max_len: num(advFields.max_len),
  };
}

function collectUi() {
  return {
    model: el.model.value,
    lang: el.lang.value,
    suppress: el.suppress.checked,
    nocontext: el.nocontext.checked,
    separate: el.separate.checked,
    vad: el.vad.checked,
    advanced: readAdvanced(),
  };
}

function applyUi(ui) {
  if (!ui) return;
  if (ui.model && [...el.model.options].some((o) => o.value === ui.model)) {
    el.model.value = ui.model;
  }
  if (ui.lang) el.lang.value = ui.lang;
  for (const key of ["suppress", "nocontext", "separate", "vad"]) {
    if (typeof ui[key] === "boolean") el[key].checked = ui[key];
  }
  const adv = ui.advanced || {};
  for (const [key, node] of Object.entries(advFields)) {
    if (!(key in adv)) continue;
    if (node.type === "checkbox") node.checked = !!adv[key];
    else node.value = adv[key] ?? "";
  }
}

let saveTimer = null;
async function persist() {
  setting.ui = collectUi();
  try {
    await invoke("save_settings", { data: setting });
  } catch (_) {}
}
function scheduleSave() {
  if (!setting.remember) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(persist, 300);
}

/** 加速开关只在当前模型旁边确实有 CoreML 编码器时可点，没有就置灰并提示。 */
async function refreshCoreml() {
  const model = el.model.value;
  let available = false;
  try {
    available = model ? await invoke("coreml_status", { model }) : false;
  } catch (_) {}
  el.coreml.disabled = !available;
  el.coremlMissing.hidden = available;
  el.coreml.checked = available ? setting.coreml : false;
}

el.advReset.addEventListener("click", () => {
  for (const node of Object.values(advFields)) {
    if (node.type === "checkbox") node.checked = false;
    else node.value = "";
  }
  scheduleSave();
});
for (const node of Object.values(advFields)) node.addEventListener("change", scheduleSave);
for (const node of [el.model, el.lang, el.suppress, el.nocontext, el.separate, el.vad]) {
  node.addEventListener("change", scheduleSave);
}
el.model.addEventListener("change", refreshCoreml);
el.coreml.addEventListener("change", () => {
  setting.coreml = el.coreml.checked;
  scheduleSave();
});
el.remember.addEventListener("change", () => {
  setting.remember = el.remember.checked;
  persist();
});

el.mcpEnabled.addEventListener("change", async () => {
  const wanted = el.mcpEnabled.checked;
  try {
    await invoke("mcp_set_enabled", { enabled: wanted });
    setting.mcpEnabled = wanted;
    await invoke("save_settings", { data: setting });
    setStatus(tr(wanted ? "status.mcp_on" : "status.mcp_off"), "ok");
  } catch (error) {
    el.mcpEnabled.checked = !wanted;
    console.error("MCP 开关失败", error);
    setStatus(tr("status.mcp_failed", { error }), "err");
  }
});

el.debugLog.addEventListener("change", async () => {
  const wanted = el.debugLog.checked;
  setting.debugLog = wanted;
  try {
    await invoke("debug_log_set_enabled", { enabled: wanted });
    await invoke("save_settings", { data: setting });
    setStatus(tr(wanted ? "status.debug_on" : "status.debug_off"), "ok");
  } catch (error) {
    el.debugLog.checked = !wanted;
    setting.debugLog = !wanted;
    console.error("调试日志开关失败", error);
    setStatus(tr("status.debug_failed", { error }), "err");
  }
});

el.openLogs.addEventListener("click", async () => {
  try {
    await invoke("open_logs_dir");
  } catch (error) {
    console.error("打开日志目录失败", error);
    setStatus(tr("status.open_logs_failed", { error }), "err");
  }
});

el.openModels.addEventListener("click", async () => {
  try {
    await invoke("open_models_dir");
  } catch (error) {
    console.error("打开模型目录失败", error);
    setStatus(tr("status.open_models_failed", { error }), "err");
  }
});

el.openLicenses.addEventListener("click", async () => {
  try {
    await invoke("open_licenses_dir");
  } catch (error) {
    console.error("打开许可目录失败", error);
    setStatus(tr("status.open_licenses_failed", { error }), "err");
  }
});

// 拖完模型回到窗口时自动刷新列表，无需重启。
window.addEventListener("focus", () => {
  loadModels();
});

el.taskConcurrency.addEventListener("change", async () => {
  let n = Number(el.taskConcurrency.value);
  if (!Number.isFinite(n)) n = 2;
  if (n > 20 && !confirm(tr("status.concurrency_warn", { n }))) {
    el.taskConcurrency.value = await invoke("task_concurrency").catch(() => 2);
    return;
  }
  n = Math.max(1, Math.min(100, Math.round(n)));
  el.taskConcurrency.value = n;
  try {
    await invoke("set_task_concurrency", { n });
    setStatus(tr("status.concurrency_set", { n }), "ok");
  } catch (error) {
    setStatus(tr("status.concurrency_failed", { error }), "err");
  }
});

el.openTasks.addEventListener("click", async () => {
  try {
    await invoke("open_tasks_window");
  } catch (error) {
    console.error("打开任务窗口失败", error);
    setStatus(tr("status.open_tasks_failed", { error }), "err");
  }
});

let activeTasks = 0;
function updateTaskBadge() {
  el.taskBadge.textContent = String(activeTasks);
  el.taskBadge.hidden = activeTasks === 0;
}
async function refreshTaskBadge() {
  try {
    const tasks = await invoke("list_tasks");
    activeTasks = tasks.filter((t) => t.status === "queued" || t.status === "running").length;
    updateTaskBadge();
  } catch (_) {}
}
listen("tasks_changed", refreshTaskBadge);
listen("task_update", refreshTaskBadge);

/* 外观主题：auto 跟随系统，light / dark 手动覆盖 */

const themeSelect = $("themeSelect");

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const current = window.__TAURI__.window.getCurrentWindow();
  // 同步原生窗口外观（macOS 标题栏、滚动条等）；auto 传 null 表示跟随系统
  try {
    current.setTheme(theme === "auto" ? null : theme);
  } catch (_) {}
  // 跟随系统时保留玻璃；手动指定主题时去掉玻璃，改用不透明底板（见 style.css）
  try {
    if (theme === "auto") {
      current.setEffects({ effects: ["underWindowBackground"], state: "active" });
    } else {
      current.clearEffects();
    }
  } catch (_) {}
}

function saveTheme(theme) {
  setting.theme = theme;
  invoke("save_settings", { data: setting }).catch(() => {});
}

themeSelect.addEventListener("change", () => {
  applyTheme(themeSelect.value);
  saveTheme(themeSelect.value);
});

(async () => {
  let theme = "auto";
  try {
    const loaded = await invoke("load_settings");
    if (loaded && typeof loaded === "object" && loaded.theme) theme = loaded.theme;
  } catch (_) {}
  setting.theme = theme;
  themeSelect.value = theme;
  applyTheme(theme);
})();

/* 高级参数浮层：点击按钮在按钮上方展开，再点关闭 */

const advToggle = $("advToggle");
const advPopover = $("advPopover");
const advClose = $("advClose");

function positionAdvPopover() {
  const rect = advToggle.getBoundingClientRect();
  // 按钮在窗口最上沿，上方只有标题栏，放不下面板；因此紧贴按钮下沿展开。
  const right = Math.max(12, window.innerWidth - rect.right);
  const top = Math.max(12, rect.bottom + 8);
  advPopover.style.right = `${right}px`;
  advPopover.style.top = `${top}px`;
  advPopover.style.bottom = "auto";
}

function setAdvOpen(open) {
  if (open) {
    positionAdvPopover();
    advPopover.classList.add("open");
  } else {
    advPopover.classList.remove("open");
  }
  advToggle.classList.toggle("active", open);
}

advToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  setAdvOpen(!advPopover.classList.contains("open"));
});

advClose.addEventListener("click", () => setAdvOpen(false));

document.addEventListener("click", (event) => {
  if (!advPopover.classList.contains("open")) return;
  if (advPopover.contains(event.target) || advToggle.contains(event.target)) return;
  setAdvOpen(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setAdvOpen(false);
});

window.addEventListener("resize", () => {
  if (advPopover.classList.contains("open")) positionAdvPopover();
});

async function pickAudio(path) {
  // 扩展名不再作为判据，交给 ffprobe 看有没有音轨。
  if (!(await checkMedia(path, "audio"))) return;
  audioPath = path;
  el.file.textContent = path;
  el.run.disabled = false;
  setStatus(tr("app.ready"));
}

async function chooseAudio() {
  const picked = await pickFile();
  if (picked) await pickAudio(picked);
}

el.drop.addEventListener("click", chooseAudio);
el.drop.addEventListener("dragover", (event) => {
  event.preventDefault();
  el.drop.classList.add("over");
});
el.drop.addEventListener("dragleave", () => el.drop.classList.remove("over"));
el.drop.addEventListener("drop", async (event) => {
  event.preventDefault();
  el.drop.classList.remove("over");
  const file = event.dataTransfer.files[0];
  if (file && file.path) await pickAudio(file.path);
});
listen("tauri://drag-drop", async (event) => {
  const paths = event.payload?.paths ?? [];
  if (paths.length) await pickAudio(paths[0]);
});

listen("progress", (event) => {
  const { stage, detail, percent } = event.payload ?? {};
  if (typeof percent === "number") {
    el.bar.style.width = `${percent}%`;
    el.pct.textContent = `${percent}%`;
  }
  if (stage === "separate") setStatus(tr("status.separate_progress", { percent: detail ?? 0 }), "busy");
  else if (stage === "transcribe") setStatus(tr("status.transcribing"), "busy");
});

function srtToLrc(srt) {
  return srt
    .trim()
    .split(/\n\n+/)
    .map((block) => {
      const lines = block.split("\n");
      const time = lines.find((line) => line.includes("-->"));
      if (!time) return "";
      const start = time.split("-->")[0].trim();
      const [hh, mm, rest] = start.split(":");
      const ss = rest.replace(",", ".");
      const stamp = hh === "00" ? `${mm}:${ss}` : `${hh}:${mm}:${ss}`;
      const content = lines
        .filter((line) => !line.includes("-->") && !/^\d+$/.test(line.trim()))
        .join(" ")
        .trim();
      return content ? `[${stamp}]${content}` : "";
    })
    .filter(Boolean)
    .join("\n");
}

async function saveAs(ext, content) {
  const base = audioPath ? stripExt(baseName(audioPath)) : "transcript";
  const path = await save({
    defaultPath: `${base}.${ext}`,
    filters: [{ name: ext.toUpperCase(), extensions: [ext] }],
  });
  if (!path) return;
  await invoke("save_text", { path, content });
  setStatus(tr("status.saved", { name: baseName(path) }), "ok");
}

let running = false;
let currentTaskId = null;
el.run.addEventListener("click", async () => {
  if (running && currentTaskId) {
    try {
      await invoke("cancel_task", { id: currentTaskId });
      setStatus(tr("status.stopping"), "busy");
    } catch (error) {
      setStatus(tr("status.cancel_failed", { error }), "err");
    }
    return;
  }
  if (!audioPath) return;
  const adv = readAdvanced();
  const params = {
    input_path: audioPath,
    model: el.model.value,
    language: el.lang.value,
    separate: el.separate.checked,
    vad: el.vad.checked,
    suppress_ns: el.suppress.checked,
    coreml: el.coreml.checked,
    no_context: el.nocontext.checked,
    prompt: adv.prompt || null,
    no_fallback: !!adv.no_fallback,
    beam_size: adv.beam_size,
    best_of: adv.best_of,
    no_speech_thold: adv.no_speech_thold,
    entropy_thold: adv.entropy_thold ?? 2.8,
    logprob_thold: adv.logprob_thold,
    word_thold: adv.word_thold,
    max_len: adv.max_len,
  };
  try {
    await submitTask("transcribe", params, baseName(audioPath));
    resetMainPage();
    setStatus(tr("status.submitted"), "ok");
  } catch (error) {
    setStatus(tr("status.submit_failed", { error }), "err");
  }
});

// 用户自己提交任务后，把主页面还原到初始状态；结果与进度统一去任务窗口看。
function resetMainPage() {
  audioPath = null;
  result = { text: "", srt: "" };
  currentTaskId = null;
  running = false;
  el.file.textContent = tr("common.no_file");
  el.run.disabled = true;
  el.run.textContent = tr("transcribe.run");
  el.text.textContent = tr("transcribe.waiting");
  el.bar.style.width = "0%";
  el.pct.textContent = "0%";
}

el.copy.addEventListener("click", async () => {
  if (!result.text) return;
  await navigator.clipboard.writeText(result.text);
  setStatus(tr("status.copied"), "ok");
});
el.saveTxt.addEventListener("click", () => result.text && saveAs("txt", result.text));
el.saveSrt.addEventListener("click", () => result.srt && saveAs("srt", result.srt));
el.saveLrc.addEventListener("click", () => result.srt && saveAs("lrc", srtToLrc(result.srt)));

/* ---------------- 歌曲编辑（数据 / 标签 / 封面 / 文件名 合一） ---------------- */

let editorPath = null;

const tagFields = {
  title: $("tagTitle"),
  artist: $("tagArtist"),
  album: $("tagAlbum"),
  albumartist: $("tagAlbumArtist"),
  genre: $("tagGenre"),
  date: $("tagDate"),
  tracknumber: $("tagTrack"),
  composer: $("tagComposer"),
};

function cueTime(text) {
  let m = text.trim().match(/^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})$/);
  if (m) return (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) + Number(m[4].padEnd(3, "0")) / 1000;
  m = text.trim().match(/^(\d{1,2}):(\d{2})[,.](\d{1,3})$/);
  if (m) return (+m[1]) * 60 + (+m[2]) + Number(m[3].padEnd(3, "0")) / 1000;
  return null;
}

function lrcStamp(seconds) {
  const mm = Math.floor(seconds / 60).toString().padStart(2, "0");
  const ss = Math.floor(seconds % 60).toString().padStart(2, "0");
  const cs = Math.round((seconds % 1) * 100).toString().padStart(2, "0");
  return `[${mm}:${ss}.${cs}]`;
}

// SRT / VTT 的时间轴转成 LRC 行，LRC 与纯文本原样保留。
function normalizeLyrics(text, ext) {
  if (ext !== "srt" && ext !== "vtt") return text.trimEnd();
  const out = [];
  let stamp = "";
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || /^(WEBVTT|NOTE|Kind:|Language:)/i.test(line) || /^\d+$/.test(line)) continue;
    if (line.includes("-->")) {
      const start = cueTime(line.split("-->")[0]);
      if (start !== null) stamp = lrcStamp(start);
      continue;
    }
    out.push(stamp + line.replace(/<\/?[^>]+>/g, ""));
    stamp = "";
  }
  return out.join("\n");
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderInfo(info) {
  const tags = info.tags || {};
  const rows = [
    [tr("editor.info_format"), info.format_long || info.format || "-"],
    [tr("editor.info_duration"), humanDuration(info.duration)],
    [tr("editor.info_size"), humanSize(info.size)],
    [tr("editor.info_bitrate"), info.bit_rate ? `${Math.round(info.bit_rate / 1000)} kbps` : "-"],
    [tr("editor.info_codec"), info.codec || "-"],
    [tr("editor.info_samplerate"), info.sample_rate ? `${info.sample_rate} Hz` : "-"],
    [tr("editor.info_channels"), info.channels || "-"],
    [tr("editor.info_cover"), info.has_cover ? tr("editor.info_yes") : tr("editor.info_no")],
  ];
  $("infoGrid").innerHTML = rows
    .map(([k, v]) => `<div class="kv"><span class="k">${k}</span><span class="v">${escapeHtml(String(v))}</span></div>`)
    .join("");
}

async function refreshCover() {
  const img = $("coverImg");
  const empty = $("coverEmpty");
  img.hidden = true;
  img.removeAttribute("src");
  empty.hidden = false;
  empty.textContent = tr("status.cover_none");
  if (!editorPath) return;
  try {
    const dataUrl = await invoke("media_read_cover", { path: editorPath });
    if (dataUrl) {
      img.src = dataUrl;
      img.hidden = false;
      empty.hidden = true;
    }
    $("coverRemove").disabled = !dataUrl;
  } catch (error) {
    empty.textContent = tr("status.cover_read_failed", { error });
  }
}

async function refreshEditor() {
  if (!editorPath) return;
  try {
    const info = await invoke("media_info", { path: editorPath });
    renderInfo(info);
    const tags = info.tags || {};
    for (const [key, node] of Object.entries(tagFields)) node.value = tags[key] || "";
    $("lyricsText").value = tags.lyrics || "";
    $("renameInput").value = stripExt(baseName(editorPath));
    await refreshCover();
  } catch (error) {
    $("infoGrid").innerHTML = `<p class="adv-tip">${escapeHtml(tr("editor.read_failed", { error }))}</p>`;
    setStatus(tr("editor.read_failed", { error }), "err");
  }
}

$("editorPick").addEventListener("click", async () => {
  const picked = await pickFile();
  if (!picked) return;
  if (!(await checkMedia(picked, "audio"))) return;
  editorPath = picked;
  $("editorPath").textContent = picked;
  $("tagsSave").disabled = false;
  for (const id of ["lyricsText", "lyricsImport", "lyricsClear", "lyricsSave"]) $(id).disabled = false;
  $("renameDo").disabled = false;
  $("renameFromTag").disabled = false;
  $("editorReload").disabled = false;
  await refreshEditor();
  setStatus(tr("status.loaded"), "ok");
});

$("editorReload").addEventListener("click", async () => {
  if (!editorPath) return;
  await refreshEditor();
  setStatus(tr("status.reloaded"), "ok");
});

// 提交后把编辑页还原到初始状态，结果去任务窗口看。
function resetEditorPage() {
  editorPath = null;
  $("editorPath").textContent = tr("common.no_file");
  for (const node of Object.values(tagFields)) node.value = "";
  $("lyricsText").value = "";
  $("renameInput").value = "";
  $("infoGrid").innerHTML = `<p class="adv-tip">${escapeHtml(tr("editor.raw_empty"))}</p>`;
  $("coverImg").hidden = true;
  $("coverImg").removeAttribute("src");
  $("coverEmpty").hidden = false;
  $("coverEmpty").textContent = tr("editor.cover_empty");
  $("tagsSave").disabled = true;
  $("coverRemove").disabled = true;
  $("renameDo").disabled = true;
  $("renameFromTag").disabled = true;
  $("editorReload").disabled = true;
  for (const id of ["lyricsText", "lyricsImport", "lyricsClear", "lyricsSave"]) $(id).disabled = true;
}

async function saveTags() {
  if (!editorPath) return;
  const tags = {};
  for (const [key, node] of Object.entries(tagFields)) tags[key] = node.value.trim();
  tags.lyrics = $("lyricsText").value.trimEnd();
  try {
    await submitTask("tags", { path: editorPath, tags }, baseName(editorPath));
    resetEditorPage();
    setStatus(tr("status.submitted"), "ok");
  } catch (error) {
    setStatus(tr("status.submit_failed", { error }), "err");
  }
}

$("tagsSave").addEventListener("click", saveTags);
$("lyricsSave").addEventListener("click", saveTags);
$("lyricsClear").addEventListener("click", () => {
  $("lyricsText").value = "";
  setStatus(tr("status.lyrics_cleared"), "ok");
});

$("lyricsImport").addEventListener("click", async () => {
  if (!editorPath) return;
  const picked = await open({
    multiple: false,
    filters: [{ name: tr("editor.lyrics_file"), extensions: ["lrc", "srt", "vtt", "txt"] }],
  });
  if (!picked) return;
  try {
    const text = await invoke("media_read_text", { path: picked });
    const ext = (picked.split(".").pop() || "").toLowerCase();
    $("lyricsText").value = normalizeLyrics(text, ext);
    setStatus(tr("status.lyrics_imported", { ext: ext.toUpperCase() }), "ok");
  } catch (error) {
    setStatus(tr("status.import_failed", { error }), "err");
  }
});

$("coverChoose").addEventListener("click", async () => {
  if (!editorPath) {
    setStatus(tr("status.pick_song_first"), "err");
    return;
  }
  const image = await open({
    multiple: false,
    filters: [{ name: tr("editor.image_file"), extensions: ["jpg", "jpeg", "png", "bmp", "webp"] }],
  });
  if (!image) return;
  const path = editorPath;
  try {
    await submitTask("cover", { action: "set", path, image }, baseName(path));
    resetEditorPage();
    setStatus(tr("status.submitted"), "ok");
  } catch (error) {
    setStatus(tr("status.submit_failed", { error }), "err");
  }
});

$("coverRemove").addEventListener("click", async () => {
  if (!editorPath) return;
  const path = editorPath;
  try {
    await submitTask("cover", { action: "remove", path }, baseName(path));
    resetEditorPage();
    setStatus(tr("status.submitted"), "ok");
  } catch (error) {
    setStatus(tr("status.submit_failed", { error }), "err");
  }
});

$("renameFromTag").addEventListener("click", async () => {
  if (!editorPath) return;
  try {
    const info = await invoke("media_info", { path: editorPath });
    const tags = info.tags || {};
    const name = buildName(tags.title, tags.artist, "artist_title");
    if (!name) {
      setStatus(tr("editor.no_tag_for_fill"), "err");
      return;
    }
    $("renameInput").value = name;
  } catch (error) {
    setStatus(tr("status.read_tags_failed", { error }), "err");
  }
});

$("renameDo").addEventListener("click", async () => {
  if (!editorPath) return;
  const name = $("renameInput").value.trim();
  if (!name) return;
  const path = editorPath;
  try {
    await submitTask("rename", { path, filename: name }, baseName(path));
    resetEditorPage();
    setStatus(tr("status.submitted"), "ok");
  } catch (error) {
    setStatus(tr("status.submit_failed", { error }), "err");
  }
});

/* ---------------- 批量重命名 ---------------- */

let batchItems = [];
function renderBatch() {
  if (!batchItems.length) {
    $("batchList").innerHTML = `<p class="adv-tip">${escapeHtml(tr("batch.none_found"))}</p>`;
    $("batchDo").disabled = true;
    return;
  }
  const pattern = $("batchPattern").value;
  $("batchList").innerHTML = batchItems
    .map((item) => {
      const tags = item.info?.tags || {};
      const target = buildName(tags.title, tags.artist, pattern);
      const next = target
        ? `${target}${item.name.match(/\.[^.]+$/)?.[0] || ""}`
        : tr("batch.skip_no_tag");
      return `<div class="batch-row"><span class="old">${escapeHtml(item.name)}</span><span class="arrow">→</span><span class="new">${escapeHtml(next)}</span></div>`;
    })
    .join("");
  $("batchDo").disabled = false;
}

$("batchPick").addEventListener("click", async () => {
  const dir = await open({ directory: true, multiple: false });
  if (!dir) return;
  $("batchPath").textContent = dir;
  setStatus(tr("status.scanning"), "busy");
  try {
    batchItems = await invoke("media_scan_folder", { dir });
    renderBatch();
    setStatus(tr("status.scan_found", { n: batchItems.length }), "ok");
  } catch (error) {
    setStatus(tr("status.scan_failed", { error }), "err");
  }
});

$("batchPattern").addEventListener("change", renderBatch);

function resetBatchPage() {
  batchItems = [];
  $("batchPath").textContent = tr("common.no_folder");
  $("batchPattern").value = "artist_title";
  $("batchList").innerHTML = `<p class="adv-tip">${escapeHtml(tr("batch.empty"))}</p>`;
  $("batchDo").disabled = true;
}

$("batchDo").addEventListener("click", async () => {
  if (!batchItems.length) return;
  const dir = $("batchPath").textContent;
  const pattern = $("batchPattern").value;
  const title = tr("batch.task_title", { name: baseName(dir), n: batchItems.length });
  try {
    await submitTask("batch_rename", { dir, pattern }, title);
    resetBatchPage();
    setStatus(tr("status.submitted"), "ok");
  } catch (error) {
    setStatus(tr("status.submit_failed", { error }), "err");
  }
});

/* ---------------- 格式转换 ---------------- */

let convertInput = null;
let convertAudioFile = null; // 「替换音轨」导入的音频
let convertOutputFile = null; // 「另存为…」指定的完整路径，优先级最高
let convertOutDir = null; // 输出文件夹，文件名自动生成
let ffcaps = null;
let convertPresets = [];

const numOf = (id) => {
  const raw = $(id).value.trim();
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
};
const intOf = (id) => {
  const value = numOf(id);
  return value === null ? null : Math.round(value);
};
const textOf = (id) => $(id).value.trim() || null;

function setOptions(id, options) {
  $(id).innerHTML = options
    .map((o) => {
      // 带 key 的选项写出 data-i18n，切换语言时由 I18N.apply 重新翻译
      const attr = o.key ? ` data-i18n="${escapeHtml(o.key)}"` : "";
      return `<option value="${escapeHtml(String(o.value))}"${attr}>${escapeHtml(o.label)}</option>`;
    })
    .join("");
}

// 编码器/容器的描述常常很长，下拉里截断显示，完整信息仍在值里
function shortLabel(text, limit = 34) {
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function encoderOptions(kind, extras) {
  const list = (ffcaps?.encoders || [])
    .filter((e) => e.kind === kind && !e.experimental)
    .map((e) => ({
      value: e.name,
      label: e.description ? `${e.name} · ${shortLabel(e.description)}` : e.name,
    }));
  return [...extras, ...list];
}

const CONVERT_SELECT_IDS = [
  "convertVideoStream",
  "convertAudioStream",
  "convertSubtitles",
  "convertVideo",
  "convertVpreset",
  "convertTune",
  "convertProfile",
  "convertLevel",
  "convertPixFmt",
  "convertAudio",
  "convertBitrate",
  "convertFormat",
  "convertFormatAdvanced",
];

const CONVERT_TEXT_IDS = [
  "convertCrf",
  "convertVideoBitrate",
  "convertMaxrate",
  "convertBufsize",
  "convertFps",
  "convertWidth",
  "convertHeight",
  "convertVf",
  "convertSampleRate",
  "convertChannels",
  "convertAf",
  "convertStart",
  "convertDuration",
  "convertMetadata",
  "convertExtra",
];

const CONVERT_CHECK_IDS = ["convertNoVideo", "convertFaststart", "convertTwoPass"];

const PRESET_FIELDS = {
  video_stream: "convertVideoStream",
  audio_stream: "convertAudioStream",
  subtitles: "convertSubtitles",
  no_video: "convertNoVideo",
  faststart: "convertFaststart",
  two_pass: "convertTwoPass",
  video_codec: "convertVideo",
  preset: "convertVpreset",
  tune: "convertTune",
  profile: "convertProfile",
  level: "convertLevel",
  pix_fmt: "convertPixFmt",
  crf: "convertCrf",
  video_bitrate: "convertVideoBitrate",
  maxrate: "convertMaxrate",
  bufsize: "convertBufsize",
  fps: "convertFps",
  width: "convertWidth",
  height: "convertHeight",
  video_filters: "convertVf",
  audio_codec: "convertAudio",
  audio_bitrate: "convertBitrate",
  sample_rate: "convertSampleRate",
  channels: "convertChannels",
  audio_filters: "convertAf",
  format: "convertFormat",
  start: "convertStart",
  duration: "convertDuration",
};

function resetConvertForm() {
  for (const id of CONVERT_SELECT_IDS) $(id).selectedIndex = 0;
  for (const id of CONVERT_TEXT_IDS) $(id).value = "";
  for (const id of CONVERT_CHECK_IDS) $(id).checked = false;
  $("convertOverwrite").checked = true;
  $("convertReplaceAudio").checked = false;
  $("convertAudioPath").textContent = tr("convert.replace_audio_none");
  convertAudioFile = null;
}

function applyConvertPreset(preset) {
  resetConvertForm();
  if (!preset) return;
  for (const [key, value] of Object.entries(preset.args || {})) {
    const id = PRESET_FIELDS[key];
    if (!id) continue;
    const node = $(id);
    if (!node) continue;
    if (node.type === "checkbox") node.checked = !!value;
    else node.value = value ?? "";
  }
  syncConvertControls();
  refreshOutputLabel();
  setStatus(tr("status.preset_applied", { name: preset.name }), "ok");
}

/* 主界面的帧率/分辨率/画质下拉只是快捷方式：
   真正的值存在高级参数里，改哪边都同步到另一边。 */

const FPS_CHOICES = ["24", "25", "30", "50", "60", "120"];
const RES_CHOICES = {
  "2160p": 2160,
  "1440p": 1440,
  "1080p": 1080,
  "720p": 720,
  "480p": 480,
  "360p": 360,
};
const QUALITY_CHOICES = { high: 18, balanced: 23, small: 28 };
// 选这些容器通常意味着"只要音频"，顺手把视频轨去掉并配上对应编码
const AUDIO_ONLY_FORMATS = {
  mp3: "libmp3lame",
  wav: "pcm_s16le",
  flac: "flac",
  ipod: "aac",
  ogg: "libvorbis",
};

function syncConvertControls(skipId) {
  // 注意：textOf 在输入框为空时返回 null（不是 ""），判空要用 falsy，
  // 否则「保持原样」会被误判成「自定义」。
  if (skipId !== "convertFpsPreset") {
    const fps = textOf("convertFps");
    $("convertFpsPreset").value = !fps ? "" : FPS_CHOICES.includes(fps) ? fps : "custom";
  }
  if (skipId !== "convertResPreset") {
    const width = textOf("convertWidth");
    const height = textOf("convertHeight");
    $("convertResPreset").value =
      !width && !height ? "" : !width && RES_CHOICES[`${height}p`] ? `${height}p` : "custom";
  }
  if (skipId !== "convertQuality") {
    const crf = textOf("convertCrf");
    const match = Object.entries(QUALITY_CHOICES).find(([, value]) => String(value) === crf);
    $("convertQuality").value = !crf ? "" : match ? match[0] : "custom";
  }
}

function applyAudioOnlyFormat() {
  const format = textOf("convertFormat");
  if (!format) return;
  const codec = AUDIO_ONLY_FORMATS[format];
  $("convertNoVideo").checked = Boolean(codec);
  if (codec) $("convertAudio").value = codec;
  // GIF 装不了音轨，选了就没必要带着音频去撞报错
  else if (format === "gif") $("convertAudio").value = "none";
}

function onConvertControlChange(event) {
  const id = event.target.id;
  const value = event.target.value;
  let skip = null;
  if (id === "convertFpsPreset") {
    if (value === "custom") {
      skip = id;
      openConvertAdv();
    } else {
      $("convertFps").value = value;
    }
  } else if (id === "convertResPreset") {
    if (value === "custom") {
      skip = id;
      openConvertAdv();
    } else if (value === "") {
      $("convertWidth").value = "";
      $("convertHeight").value = "";
    } else {
      $("convertWidth").value = "";
      $("convertHeight").value = String(RES_CHOICES[value]);
    }
  } else if (id === "convertQuality") {
    if (value === "custom") {
      skip = id;
      openConvertAdv();
    } else {
      $("convertCrf").value = value === "" ? "" : String(QUALITY_CHOICES[value]);
    }
  } else if (id === "convertFormat") {
    applyAudioOnlyFormat();
  }
  syncConvertControls(skip);
  refreshOutputLabel();
}

/* 高级参数浮层：与转写页同一套交互（点按钮在下方展开，点空白或 Esc 关闭） */

function setupPopover(toggleId, popoverId, closeId) {
  const toggle = $(toggleId);
  const popover = $(popoverId);
  const close = closeId ? $(closeId) : null;

  const place = () => {
    const rect = toggle.getBoundingClientRect();
    popover.style.right = `${Math.max(12, window.innerWidth - rect.right)}px`;
    popover.style.top = `${Math.max(12, rect.bottom + 8)}px`;
    popover.style.bottom = "auto";
  };

  const set = (open) => {
    if (open) place();
    popover.classList.toggle("open", open);
    toggle.classList.toggle("active", open);
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    set(!popover.classList.contains("open"));
  });
  if (close) close.addEventListener("click", () => set(false));
  document.addEventListener("click", (event) => {
    if (!popover.classList.contains("open")) return;
    if (popover.contains(event.target) || toggle.contains(event.target)) return;
    set(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") set(false);
  });
  window.addEventListener("resize", () => {
    if (popover.classList.contains("open")) place();
  });
  return set;
}

const openConvertAdvPopover = setupPopover(
  "convertAdvToggle",
  "convertAdvPopover",
  "convertAdvClose"
);
const openConvertAdv = () => openConvertAdvPopover(true);

async function loadFfmpegSupport() {
  let caps = null;
  let presets = [];
  try {
    [caps, presets] = await Promise.all([
      invoke("ffmpeg_capabilities"),
      invoke("convert_presets"),
    ]);
  } catch (error) {
    $("convertCapsTip").textContent = tr("convert.caps_failed", { error });
    return;
  }

  if (caps && !caps.error) {
    ffcaps = caps;
    setOptions("convertVideo", encoderOptions("video", [
      { value: "", key: "common.keep", label: tr("common.keep") },
      { value: "copy", key: "common.copy_stream", label: tr("common.copy_stream") },
    ]));
    setOptions("convertAudio", encoderOptions("audio", [
      { value: "", key: "common.keep", label: tr("common.keep") },
      { value: "copy", key: "common.copy_stream", label: tr("common.copy_stream") },
      { value: "none", key: "convert.remove_audio", label: tr("convert.remove_audio") },
    ]));
    // 主界面只放常见容器，完整列表留给高级参数
    const curatedFormats = [
      ["mp4", "MP4"],
      ["mov", "MOV"],
      ["ipod", "M4A"],
      ["matroska", "MKV"],
      ["webm", "WebM"],
      ["avi", "AVI"],
      ["mpegts", `TS · ${tr("convert.fmt_ts")}`],
      ["mp3", "MP3"],
      ["wav", "WAV"],
      ["flac", "FLAC"],
      ["ogg", "OGG"],
      ["gif", "GIF"],
    ];
    const muxers = (caps.formats || []).filter((f) => f.mux);
    const available = new Set(muxers.map((f) => f.names[0]));
    const common = available.size
      ? curatedFormats.filter(([value]) => available.has(value))
      : curatedFormats;
    setOptions("convertFormat", [
      { value: "", key: "convert.keep_ext", label: tr("convert.keep_ext") },
      ...common.map(([value, label]) => ({ value, label })),
    ]);
    setOptions("convertFormatAdvanced", [
      { value: "", key: "convert.same_as_target", label: tr("convert.same_as_target") },
      ...muxers.map((f) => ({
        value: f.names[0],
        label: `${f.names.join(" / ")} · ${shortLabel(f.description || "")}`.trim(),
      })),
    ]);
    setOptions("convertPixFmt", [
      { value: "", key: "common.auto", label: tr("common.auto") },
      ...(caps.pixel_formats || []).map((name) => ({ value: name, label: name })),
    ]);
    setOptions("convertVpreset", [
      { value: "", key: "convert.q_encoder", label: tr("convert.q_encoder") },
      ...(caps.presets || []).map((name) => ({ value: name, label: name })),
    ]);
    setOptions("convertTune", [
      { value: "", key: "common.none", label: tr("common.none") },
      ...(caps.tunes || []).map((name) => ({ value: name, label: name })),
    ]);
    setOptions("convertProfile", [
      { value: "", key: "common.auto", label: tr("common.auto") },
      ...(caps.profiles || []).map((name) => ({ value: name, label: name })),
    ]);
    setOptions("convertLevel", [
      { value: "", key: "common.auto", label: tr("common.auto") },
      ...(caps.levels || []).map((name) => ({ value: name, label: name })),
    ]);
    const videoCount = (caps.encoders || []).filter((e) => e.kind === "video").length;
    const audioCount = (caps.encoders || []).filter((e) => e.kind === "audio").length;
    $("convertCapsTip").textContent = [
      caps.version || "ffmpeg",
      tr("convert.caps_counts", {
        video: videoCount,
        audio: audioCount,
        formats: (caps.formats || []).length,
        filters: (caps.filters || []).length,
        pix: (caps.pixel_formats || []).length,
        hwaccels: (caps.hwaccels || []).join(" / ") || tr("common.none"),
      }),
    ].join("｜");
  } else {
    $("convertCapsTip").textContent = tr("convert.caps_failed_fallback", {
      error: caps?.error || tr("convert.caps_unknown"),
    });
    setStatus(tr("convert.caps_failed_plain"), "err");
  }

  convertPresets = Array.isArray(presets) ? presets : [];
  $("convertPreset").innerHTML =
    `<option value="" data-i18n="convert.preset_none">${escapeHtml(tr("convert.preset_none"))}</option>` +
    convertPresets
      .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`)
      .join("");
}

async function loadConvertStreams(path) {
  try {
    const info = await invoke("media_info", { path });
    const streams = info.streams || [];
    const build = (type) => [
      { value: "", key: "common.auto", label: tr("common.auto") },
      ...streams
        .filter((s) => s.type === type && !s.attached_pic)
        .map((s) => {
          const bits = [`#${s.index}`, s.codec || "?"];
          if (s.channels) bits.push(`${s.channels}ch`);
          if (s.width && s.height) bits.push(`${s.width}x${s.height}`);
          if (s.language) bits.push(s.language);
          return { value: `0:${s.index}`, label: bits.join(" ") };
        }),
    ];
    setOptions("convertVideoStream", build("video"));
    setOptions("convertAudioStream", build("audio"));
    if (info.duration) {
      $("convertDuration").placeholder = tr("convert.duration_ph_auto", {
        time: humanDuration(info.duration),
      });
    }
  } catch (error) {
    setStatus(tr("status.streams_failed", { error }), "err");
  }
}

$("convertPreset").addEventListener("change", () => {
  const chosen = convertPresets.find((p) => p.id === $("convertPreset").value);
  applyConvertPreset(chosen || null);
});

/* 输出命名：扩展名跟着容器/编码走，避免往 mp4 里塞 mp3 这种不合法的组合 */

const FORMAT_EXT = {
  mp4: "mp4",
  mov: "mov",
  ipod: "m4a",
  matroska: "mkv",
  webm: "webm",
  avi: "avi",
  mpegts: "ts",
  mpeg: "mpg",
  flv: "flv",
  "3gp": "3gp",
  mp3: "mp3",
  wav: "wav",
  flac: "flac",
  ogg: "ogg",
  opus: "opus",
  aac: "aac",
  ac3: "ac3",
  gif: "gif",
  image2: "png",
  webp: "webp",
};

const AUDIO_EXT = {
  libmp3lame: "mp3",
  mp3: "mp3",
  aac: "m4a",
  libfdk_aac: "m4a",
  alac: "m4a",
  pcm_s16le: "wav",
  pcm_s24le: "wav",
  pcm_s32le: "wav",
  pcm_f32le: "wav",
  pcm_u8: "wav",
  flac: "flac",
  libopus: "opus",
  opus: "opus",
  libvorbis: "ogg",
  vorbis: "ogg",
  ac3: "ac3",
  eac3: "eac3",
  mp2: "mp2",
  libtwolame: "mp2",
};

const VIDEO_EXT = {
  gif: "gif",
  libwebp: "webp",
  libwebp_anim: "webp",
  png: "png",
  mjpeg: "mjpg",
};

function inputExtension(path) {
  const match = /\.[^.\\/]+$/.exec(path || "");
  return match ? match[0].slice(1).toLowerCase() : "mp4";
}

function targetExtension() {
  const format = textOf("convertFormatAdvanced") || textOf("convertFormat");
  if (format) return FORMAT_EXT[format] || format;
  if ($("convertNoVideo").checked) {
    const audio = textOf("convertAudio");
    return (audio && AUDIO_EXT[audio]) || inputExtension(convertInput);
  }
  const video = textOf("convertVideo");
  return (video && VIDEO_EXT[video]) || inputExtension(convertInput);
}

function autoOutputName() {
  const base = convertInput ? stripExt(baseName(convertInput)) : "output";
  return `${base}-converted.${targetExtension()}`;
}

// 源文件所在目录：不选输出位置时就落在这里。
function sourceFolder(path) {
  if (!path) return null;
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return cut > 0 ? path.slice(0, cut) : null;
}

function effectiveOutDir() {
  return convertOutDir || sourceFolder(convertInput);
}

function updateRunState() {
  $("convertRun").disabled = !convertInput;
}

function refreshOutputLabel() {
  let text;
  if (convertOutputFile) {
    text = convertOutputFile;
  } else if (!convertInput) {
    text = convertOutDir || tr("convert.outdir_unsaved");
  } else {
    const dir = effectiveOutDir();
    const name = autoOutputName();
    if (!dir) {
      text = name;
    } else if (convertOutDir) {
      text = `${dir} / ${name}`;
    } else {
      text = tr("convert.outdir_hint", { dir, name });
    }
  }
  $("convertOut").textContent = text;
  updateRunState();
}

// 切换语言后，动态拼出来的文案（输出预览、批量列表）跟着重画
document.addEventListener("localechange", () => {
  refreshOutputLabel();
  if (batchItems.length) renderBatch();
});

// 页面内任何控件变化：同步主界面下拉与高级参数，并刷新输出文件名预览
document
  .querySelector('.page[data-page="convert"]')
  .addEventListener("change", onConvertControlChange);

$("convertPick").addEventListener("click", async () => {
  const picked = await pickFile();
  if (!picked) return;
  if (!(await checkMedia(picked, "media"))) return;
  convertInput = picked;
  $("convertPath").textContent = picked;
  refreshOutputLabel();
  await loadConvertStreams(picked);
});

$("convertReplaceAudio").addEventListener("change", () => {
  if (!$("convertReplaceAudio").checked) {
    convertAudioFile = null;
    $("convertAudioPath").textContent = tr("convert.replace_audio_none");
  }
});

$("convertPickAudio").addEventListener("click", async () => {
  const picked = await pickFile();
  if (!picked) return;
  if (!(await checkMedia(picked, "audio"))) return;
  convertAudioFile = picked;
  // 选到文件就自动启用，省得还要先勾一次「启用」。
  $("convertReplaceAudio").checked = true;
  $("convertAudioPath").textContent = picked;
});

$("convertChooseDir").addEventListener("click", async () => {  const dir = await open({ directory: true, multiple: false });
  if (!dir) return;
  convertOutDir = dir;
  convertOutputFile = null;
  refreshOutputLabel();
});

$("convertChooseOut").addEventListener("click", async () => {
  const base = convertInput ? stripExt(baseName(convertInput)) : "output";
  const path = await save({ defaultPath: `${base}-converted.${targetExtension()}` });
  if (!path) return;
  convertOutputFile = path;
  refreshOutputLabel();
});

function collectConvertArgs(output) {
  const metadata = {};
  for (const line of $("convertMetadata").value.split("\n")) {
    const index = line.indexOf("=");
    if (index > 0) metadata[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  const extra = $("convertExtra")
    .value.split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return {
    input: convertInput,
    output,
    format: textOf("convertFormatAdvanced") || textOf("convertFormat"),
    video_stream: textOf("convertVideoStream"),
    audio_stream: textOf("convertAudioStream"),
    replace_audio: $("convertReplaceAudio").checked ? convertAudioFile : null,
    subtitles: textOf("convertSubtitles"),
    no_video: $("convertNoVideo").checked,
    start: numOf("convertStart"),
    duration: numOf("convertDuration"),
    video_codec: textOf("convertVideo"),
    preset: textOf("convertVpreset"),
    tune: textOf("convertTune"),
    profile: textOf("convertProfile"),
    level: textOf("convertLevel"),
    pix_fmt: textOf("convertPixFmt"),
    crf: intOf("convertCrf"),
    video_bitrate: textOf("convertVideoBitrate"),
    maxrate: textOf("convertMaxrate"),
    bufsize: textOf("convertBufsize"),
    fps: textOf("convertFps"),
    width: intOf("convertWidth"),
    height: intOf("convertHeight"),
    video_filters: textOf("convertVf"),
    audio_codec: textOf("convertAudio"),
    audio_bitrate: textOf("convertBitrate"),
    sample_rate: intOf("convertSampleRate"),
    channels: intOf("convertChannels"),
    audio_filters: textOf("convertAf"),
    faststart: $("convertFaststart").checked,
    two_pass: $("convertTwoPass").checked,
    overwrite: $("convertOverwrite").checked,
    metadata: Object.keys(metadata).length ? metadata : null,
    extra_args: extra.length ? extra : null,
  };
}

// 提交后把转换页还原到初始状态，进度与结果去任务窗口看。
function resetConvertPage() {
  convertInput = null;
  convertOutputFile = null;
  convertOutDir = null;
  $("convertPath").textContent = tr("common.no_file");
  $("convertPreset").selectedIndex = 0;
  resetConvertForm();
  syncConvertControls();
  for (const id of ["convertVideoStream", "convertAudioStream"]) {
    setOptions(id, [{ value: "", key: "common.auto", label: tr("common.auto") }]);
  }
  $("convertBar").style.width = "0%";
  $("convertPct").textContent = "0%";
  refreshOutputLabel();
}

$("convertRun").addEventListener("click", async () => {
  if (!convertInput) {
    setStatus(tr("convert.pick_src_first"), "err");
    return;
  }
  if ($("convertReplaceAudio").checked) {
    if (!convertAudioFile) {
      setStatus(tr("convert.replace_audio_required"), "err");
      return;
    }
    if (textOf("convertAudio") === "none") {
      setStatus(tr("convert.replace_audio_conflict"), "err");
      return;
    }
  }
  // 目标路径优先用「另存为…」指定的；否则在输出文件夹里自动命名并避开重名；
  // 没选输出文件夹就落到源文件同目录。
  let output = convertOutputFile;
  if (!output) {
    const dir = effectiveOutDir();
    if (!dir) {
      setStatus(tr("convert.no_outdir"), "err");
      return;
    }
    try {
      output = await invoke("unique_output_path", {
        dir,
        filename: autoOutputName(),
      });
    } catch (error) {
      setStatus(tr("convert.outdir_failed", { error }), "err");
      return;
    }
  }
  const title = `${baseName(convertInput)} → ${baseName(output)}`;
  try {
    await submitTask("convert", collectConvertArgs(output), title);
    resetConvertPage();
    setStatus(tr("status.submitted"), "ok");
  } catch (error) {
    setStatus(tr("status.submit_failed", { error }), "err");
  }
});

/* ---------------- 初始化 ---------------- */

(async function init() {
  if (window.I18N) {
    try {
      await I18N.init();
    } catch (error) {
      console.warn("[i18n] 初始化失败，界面保持中文：", error);
    }
    setupLocaleSelect();
  }

  try {
    const loaded = await invoke("load_settings");
    if (loaded && typeof loaded === "object") {
      setting.remember = loaded.remember !== false;
      setting.mcpEnabled = loaded.mcpEnabled !== false;
      setting.coreml = loaded.coreml !== false;
      setting.debugLog = loaded.debugLog === true;
      setting.ui = loaded.ui || {};
    }
    el.remember.checked = setting.remember;
    el.mcpEnabled.checked = setting.mcpEnabled;
    el.coreml.checked = setting.coreml;
    el.debugLog.checked = setting.debugLog;
    el.settingsPath.textContent = await invoke("settings_path");
  } catch (_) {
    el.remember.checked = true;
    el.mcpEnabled.checked = true;
    el.coreml.checked = true;
    el.debugLog.checked = false;
  }
  // 以实际监听状态为准：启动时端口被占用等失败也要在开关上看得出来。
  try {
    el.mcpEnabled.checked = await invoke("mcp_enabled");
    setting.mcpEnabled = el.mcpEnabled.checked;
  } catch (_) {}
  try {
    el.debugLog.checked = await invoke("debug_log_enabled");
    setting.debugLog = el.debugLog.checked;
  } catch (_) {}
  try {
    el.logsPath.textContent = await invoke("logs_dir");
  } catch (_) {}

  await loadModels(false);
  await refreshCoreml();

  if (setting.remember) applyUi(setting.ui);

  refreshTaskBadge();
  try {
    el.taskConcurrency.value = await invoke("task_concurrency");
  } catch (_) {}
  loadFfmpegSupport();
})();
