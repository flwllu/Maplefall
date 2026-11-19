const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const $ = (id) => document.getElementById(id);
const list = $("taskList");
const empty = $("taskEmpty");
const badge = $("concurrency");
let tasks = [];

const t = (key, vars) => (window.I18N ? I18N.t(key, vars) : key);

function fmtTime(ms) {
  if (!ms) return "—";
  const d = new Date(Number(ms));
  return d.toLocaleString(window.I18N ? I18N.locale() : "zh-CN", { hour12: false });
}

function statusText(status) {
  const key = `task.status_${status}`;
  const text = t(key);
  return text === key ? status : text;
}

function render() {
  const active = tasks.filter((t) => t.status === "queued" || t.status === "running").length;
  document.title = active ? `${t("tasks.title")} (${active})` : t("tasks.title");
  empty.hidden = tasks.length > 0;
  list.innerHTML = tasks
    .slice()
    .reverse()
    .map((task) => {
      const status = statusText(task.status);
      const canCancel = task.status === "queued" || task.status === "running";
      const preview = task.error
        ? `<div class="task-err">${esc(task.error)}</div>`
        : task.result
          ? `<div class="task-preview">${esc(task.result.text.slice(0, 80))}</div>`
          : "";
      const source = task.source === "mcp" ? "MCP" : t("tasks.source_gui");
      return `<div class="task-item" data-id="${esc(task.id)}" title="${esc(t("tasks.open_tip"))}">
        <div class="task-row">
          <span class="task-title">${esc(task.title)}</span>
          <span class="task-status s-${task.status}">${status}</span>
        </div>
        <div class="task-row sub">
          <span>${esc(source)} · ${fmtTime(task.created_at)}</span>
          ${canCancel ? `<button class="task-cancel" data-cancel="${esc(task.id)}" type="button">${esc(t("tasks.cancel"))}</button>` : ""}
        </div>
        ${task.status === "running" || task.status === "queued" ? `<div class="task-bar"><i style="width:${task.progress || 0}%"></i></div>` : ""}
        ${preview}
      </div>`;
    })
    .join("");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function refresh() {
  try {
    tasks = await invoke("list_tasks");
    render();
  } catch (error) {
    list.innerHTML = `<div class="task-err">${esc(t("tasks.load_failed", { error }))}</div>`;
  }
}

list.addEventListener("click", (event) => {
  const cancelId = event.target.dataset.cancel;
  if (cancelId) {
    event.stopPropagation();
    invoke("cancel_task", { id: cancelId }).then(refresh).catch((e) => alert(String(e)));
  }
});

list.addEventListener("dblclick", (event) => {
  const item = event.target.closest(".task-item");
  if (!item || event.target.dataset.cancel) return;
  const id = item.dataset.id;
  invoke("open_task_detail", { id }).catch((e) => alert(String(e)));
});

/* ---------------- 清理任务 ---------------- */

const clearMask = $("clearMask");
const clearArtifacts = $("clearArtifacts");
const taskNote = $("taskNote");
let noteTimer = null;

function fmtSize(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function showNote(text, kind = "") {
  taskNote.textContent = text;
  taskNote.className = `task-note ${kind}`;
  taskNote.hidden = false;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => {
    taskNote.hidden = true;
  }, 4000);
}

async function openClearDialog() {
  const active = tasks.filter((t) => t.status === "queued" || t.status === "running").length;
  const finished = tasks.length - active;
  const parts = [];
  parts.push(finished ? t("tasks.clear_finished", { n: finished }) : t("tasks.clear_none"));
  if (active) parts.push(t("tasks.clear_active", { n: active }));
  $("clearText").textContent = parts.join(" ");

  clearArtifacts.checked = false;
  $("artifactHint").textContent = t("tasks.artifact_counting");
  clearMask.hidden = false;

  try {
    const usage = await invoke("artifacts_usage");
    $("artifactHint").textContent = usage.files
      ? t("tasks.artifact_usage", { size: fmtSize(usage.bytes), files: usage.files })
      : t("tasks.artifact_empty");
  } catch (error) {
    $("artifactHint").textContent = t("tasks.artifact_failed", { error });
  }
}

function closeClearDialog() {
  clearMask.hidden = true;
}

$("clearFinished").addEventListener("click", openClearDialog);
$("clearCancel").addEventListener("click", closeClearDialog);
clearMask.addEventListener("click", (event) => {
  if (event.target === clearMask) closeClearDialog();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !clearMask.hidden) closeClearDialog();
});

$("clearConfirm").addEventListener("click", async () => {
  const withArtifacts = clearArtifacts.checked;
  closeClearDialog();
  try {
    const removed = await invoke("clear_finished_tasks");
    showNote(removed ? t("tasks.cleared", { n: removed }) : t("tasks.cleared_none"));
  } catch (error) {
    showNote(t("tasks.clear_failed", { error }), "err");
    return;
  }
  if (!withArtifacts) {
    refresh();
    return;
  }
  try {
    const usage = await invoke("clean_artifacts");
    showNote(
      usage.files
        ? t("tasks.artifacts_cleared", { files: usage.files, size: fmtSize(usage.bytes) })
        : t("tasks.artifacts_empty"),
      "ok"
    );
  } catch (error) {
    showNote(t("tasks.artifacts_failed", { error }), "err");
  }
  refresh();
});

badge.addEventListener("change", async () => {
  let n = Number(badge.value);
  if (!Number.isFinite(n)) n = 2;
  if (n > 100) {
    if (!confirm(t("tasks.concurrency_warn"))) {
      badge.value = 2;
      n = 2;
    }
  }
  n = Math.max(1, Math.min(100, Math.round(n)));
  badge.value = n;
  await invoke("set_task_concurrency", { n });
});

listen("task_update", (event) => {
  const task = event.payload;
  const idx = tasks.findIndex((t) => t.id === task.id);
  if (idx >= 0) tasks[idx] = task;
  else tasks.push(task);
  render();
});
listen("tasks_changed", refresh);

// 语言切换后重画列表（时间、状态、按钮文案都跟着变）
document.addEventListener("localechange", () => render());

(async function init() {
  if (window.I18N) await I18N.init();
  try {
    badge.value = await invoke("task_concurrency");
  } catch (_) {}
  refresh();
})();
