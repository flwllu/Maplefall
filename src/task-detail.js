const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const { save } = window.__TAURI__.dialog;

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const id = params.get("id") || "";
let task = null;
let showTime = true;

const t = (key, vars) => (window.I18N ? I18N.t(key, vars) : key);

function statusText(status) {
  const key = `task.status_${status}`;
  const text = t(key);
  return text === key ? status : text;
}

function fmtTime(ms) {
  if (!ms) return "—";
  return new Date(Number(ms)).toLocaleString(window.I18N ? I18N.locale() : "zh-CN", { hour12: false });
}

// SRT 时间轴转 LRC 行（每行前面带 [mm:ss.xx] 时间），与主界面一致。
function srtToLrc(srt) {
  return (srt || "")
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

function displayText() {
  if (!task?.result) {
    if (task?.error) return task.error;
    return task?.status === "running"
      ? t("task.running_progress", { percent: task.progress ?? 0 })
      : t("task.no_content");
  }
  if (showTime && task.result.srt) {
    const lrc = srtToLrc(task.result.srt);
    if (lrc) return lrc;
  }
  return task.result.text;
}

function render() {
  if (!task) return;
  $("detailTitle").textContent = task.title || t("task.detail_title");
  const status = statusText(task.status);
  const lang = task.params.language || "auto";
  const separate = task.params.separate ? t("task.meta_separate") : t("task.meta_original");
  const source = task.source === "mcp" ? "MCP" : t("tasks.source_gui");
  const finished = task.finished_at ? t("task.meta_finished", { time: fmtTime(task.finished_at) }) : "";
  $("detailMeta").innerHTML = `${esc(status)} · ${esc(source)} · ${esc(lang.toUpperCase())} · ${esc(separate)} · ${esc(
    t("task.meta_created", { time: fmtTime(task.created_at) })
  )}${esc(finished)}<br>${esc(t("task.meta_input"))}${esc(task.params.input_path)}`;
  $("detailText").textContent = displayText();
  const logEl = $("detailLog");
  logEl.textContent = task.log || t("task.no_log");
  logEl.scrollTop = logEl.scrollHeight;
  $("toggleTime").textContent = showTime ? t("task.show_plain") : t("task.show_time");
  const hasResult = !!task.result;
  $("copyText").disabled = !hasResult;
  $("saveTxt").disabled = !hasResult;
  $("saveSrt").disabled = !hasResult;
  $("saveLrc").disabled = !hasResult || !task.result.srt;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function refresh() {
  try {
    task = await invoke("get_task", { id });
    render();
  } catch (error) {
    $("detailText").textContent = t("task.load_failed", { error });
  }
}

$("copyText").addEventListener("click", async () => {
  if (!task?.result) return;
  await navigator.clipboard.writeText($("detailText").textContent);
});

$("toggleTime").addEventListener("click", () => {
  showTime = !showTime;
  render();
});

$("copyLog").addEventListener("click", async () => {
  if (!task?.log) return;
  await navigator.clipboard.writeText(task.log);
});

async function saveAs(ext, content) {
  const base = (task.title || "transcript").replace(/\.[^.]+$/, "");
  const path = await save({ defaultPath: `${base}.${ext}` });
  if (!path) return;
  await invoke("save_text", { path, content });
}

$("saveTxt").addEventListener("click", () => task?.result && saveAs("txt", task.result.text));
$("saveSrt").addEventListener("click", () => task?.result && saveAs("srt", task.result.srt));
$("saveLrc").addEventListener("click", () => task?.result && saveAs("lrc", srtToLrc(task.result.srt)));

listen("task_update", (event) => {
  if (event.payload?.id === id) {
    task = event.payload;
    render();
  }
});

document.addEventListener("localechange", () => render());

(async function init() {
  if (window.I18N) await I18N.init();
  if (task) render();
  refresh();
})();
