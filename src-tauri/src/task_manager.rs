//! 统一任务队列：所有会改动文件的操作（转写、格式转换、标签/歌词、封面、
//! 重命名与批量重命名）都提交到这里，按并发数调度执行。
//! 任务状态持久化在 app_config_dir/tasks.json，重启后恢复；中断的任务标记为 interrupted。

use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{Emitter, Manager};

fn default_kind() -> String {
    "transcribe".into()
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Task {
    pub id: String,
    pub source: String,
    pub title: String,
    pub status: String,
    pub progress: u32,
    #[serde(default)]
    pub log: String,
    pub created_at: u128,
    pub started_at: Option<u128>,
    pub finished_at: Option<u128>,
    /// 任务类型：transcribe / convert / tags / cover / rename / batch_rename。
    #[serde(default = "default_kind")]
    pub kind: String,
    #[serde(default)]
    pub params: Value,
    #[serde(default)]
    pub result: Option<Value>,
    pub error: Option<String>,
}

struct Inner {
    tasks: Vec<Task>,
    cancel_flags: HashMap<String, Arc<AtomicBool>>,
    children: HashMap<String, Arc<Mutex<Option<Child>>>>,
    concurrency: usize,
    app: tauri::AppHandle,
    config_dir: PathBuf,
}

static MANAGER: OnceLock<Mutex<Inner>> = OnceLock::new();

fn now_ms() -> u128 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0)
}

fn tasks_file(config_dir: &PathBuf) -> PathBuf {
    config_dir.join("tasks.json")
}

fn load_tasks(config_dir: &PathBuf) -> Vec<Task> {
    let path = tasks_file(config_dir);
    let raw = match fs::read_to_string(&path) {
        Ok(raw) => raw,
        Err(_) => return Vec::new(),
    };
    let mut tasks: Vec<Task> = match serde_json::from_str(&raw) {
        Ok(tasks) => tasks,
        Err(_) => {
            let _ = fs::rename(&path, path.with_extension("json.corrupt"));
            return Vec::new();
        }
    };
    for task in &mut tasks {
        if task.status == "running" || task.status == "queued" {
            task.status = "interrupted".into();
            task.error = Some("应用重启，任务已中断".into());
            task.finished_at = Some(now_ms());
        }
    }
    tasks
}

fn persist(inner: &Inner) {
    let path = tasks_file(&inner.config_dir);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(json) = serde_json::to_string_pretty(&inner.tasks) {
        let tmp = path.with_extension("json.tmp");
        if fs::write(&tmp, json).is_ok() {
            let _ = fs::rename(&tmp, &path);
        }
    }
}

fn emit(inner: &Inner, event: &str, payload: serde_json::Value) {
    let _ = inner.app.emit(event, payload);
}

fn emit_task(inner: &Inner, task: &Task) {
    emit(inner, "task_update", serde_json::to_value(task).unwrap_or_default());
}

pub fn init(app: &tauri::AppHandle, concurrency: usize) -> Result<(), String> {
    let config_dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    let tasks = load_tasks(&config_dir);
    let inner = Inner {
        tasks,
        cancel_flags: HashMap::new(),
        children: HashMap::new(),
        concurrency: concurrency.clamp(1, 100),
        app: app.clone(),
        config_dir,
    };
    let _ = MANAGER.set(Mutex::new(inner));
    {
        let guard = MANAGER.get().unwrap().lock().unwrap();
        persist(&guard);
    }
    std::thread::spawn(scheduler_loop);
    Ok(())
}

fn manager() -> &'static Mutex<Inner> {
    MANAGER.get().expect("任务管理器尚未初始化")
}

pub fn set_concurrency(n: usize) -> usize {
    let mut inner = manager().lock().unwrap();
    inner.concurrency = n.clamp(1, 100);
    persist(&inner);
    inner.concurrency
}

pub fn get_concurrency() -> usize {
    manager().lock().unwrap().concurrency
}

pub fn submit(kind: &str, params: Value, source: &str, title: String) -> String {
    let mut inner = manager().lock().unwrap();
    let id = format!("{:013}-{:04x}", now_ms(), (inner.tasks.len() + 1) & 0xffff);
    let task = Task {
        id: id.clone(),
        source: source.to_string(),
        title,
        status: "queued".into(),
        progress: 0,
        log: String::new(),
        created_at: now_ms(),
        started_at: None,
        finished_at: None,
        kind: kind.to_string(),
        params,
        result: None,
        error: None,
    };
    inner.cancel_flags.insert(id.clone(), Arc::new(AtomicBool::new(false)));
    inner.children.insert(id.clone(), Arc::new(Mutex::new(None)));
    inner.tasks.push(task.clone());
    persist(&inner);
    emit_task(&inner, &task);
    emit(&inner, "tasks_changed", serde_json::json!({}));
    id
}

pub fn list() -> Vec<Task> {
    manager().lock().unwrap().tasks.clone()
}

pub fn get(id: &str) -> Option<Task> {
    manager().lock().unwrap().tasks.iter().find(|t| t.id == id).cloned()
}

pub fn cancel(id: &str) -> Result<(), String> {
    let mut inner = manager().lock().unwrap();
    let flag = inner.cancel_flags.get(id).cloned().ok_or("任务不存在或已结束")?;
    flag.store(true, Ordering::SeqCst);

    // 立即杀掉正在运行的子进程，否则 read_line 会一直阻塞到转写自然结束。
    let child = inner.children.get(id).cloned();
    if let Some(child) = child {
        if let Ok(mut guard) = child.lock() {
            if let Some(process) = guard.as_mut() {
                let _ = process.kill();
            }
        }
    }

    let mut changed = None;
    if let Some(task) = inner.tasks.iter_mut().find(|t| t.id == id) {
        if task.status == "queued" || task.status == "running" {
            task.status = "cancelled".into();
            task.finished_at = Some(now_ms());
            changed = Some(task.clone());
        }
    }
    if let Some(task) = changed {
        persist(&inner);
        emit_task(&inner, &task);
        emit(&inner, "tasks_changed", serde_json::json!({}));
    }
    Ok(())
}

/// 运行中 / 排队中的任务数，供「关窗确认」判断还有没有活在跑。
pub fn active_counts() -> (usize, usize) {
    let Some(manager) = MANAGER.get() else {
        return (0, 0);
    };
    let inner = manager.lock().unwrap();
    let running = inner.tasks.iter().filter(|t| t.status == "running").count();
    let queued = inner.tasks.iter().filter(|t| t.status == "queued").count();
    (running, queued)
}

/// 退出前把所有在跑的任务停掉，避免子进程变成孤儿继续占 CPU。
pub fn cancel_all_active() -> usize {
    let Some(manager) = MANAGER.get() else {
        return 0;
    };
    let ids: Vec<String> = {
        let inner = manager.lock().unwrap();
        inner
            .tasks
            .iter()
            .filter(|t| t.status == "running" || t.status == "queued")
            .map(|t| t.id.clone())
            .collect()
    };
    let mut stopped = 0;
    for id in ids {
        if cancel(&id).is_ok() {
            stopped += 1;
        }
    }
    stopped
}

pub fn clear_finished() -> usize {
    let mut inner = manager().lock().unwrap();
    let before = inner.tasks.len();
    inner.tasks.retain(|t| !matches!(t.status.as_str(), "done" | "failed" | "cancelled" | "interrupted"));
    let removed = before - inner.tasks.len();
    if removed > 0 {
        persist(&inner);
        emit(&inner, "tasks_changed", serde_json::json!({}));
    }
    removed
}

fn scheduler_loop() {
    loop {
        std::thread::sleep(Duration::from_millis(300));
        let dispatched = {
            let mut inner = manager().lock().unwrap();
            let running = inner.tasks.iter().filter(|t| t.status == "running").count();
            let limit = inner.concurrency;
            if running >= limit {
                Vec::new()
            } else {
                let slots = limit - running;
                let mut picked = Vec::new();
                let mut snapshots = Vec::new();
                for task in inner.tasks.iter_mut() {
                    if picked.len() >= slots { break; }
                    if task.status == "queued" {
                        task.status = "running".into();
                        task.started_at = Some(now_ms());
                        task.progress = 0;
                        picked.push(task.clone());
                        snapshots.push(task.clone());
                    }
                }
                for task in &snapshots {
                    emit_task(&inner, task);
                }
                if !picked.is_empty() {
                    persist(&inner);
                    emit(&inner, "tasks_changed", serde_json::json!({}));
                }
                picked
            }
        };
        for task in dispatched {
            let flag = manager().lock().unwrap().cancel_flags.get(&task.id).cloned().unwrap_or_default();
            std::thread::spawn(move || execute(task, flag));
        }
    }
}

fn execute(task: Task, cancel: Arc<AtomicBool>) {
    let result = run_child_job(&task.id, &task.kind, &task.params, &cancel);

    let mut inner = manager().lock().unwrap();
    let mut finished = None;
    if let Some(t) = inner.tasks.iter_mut().find(|t| t.id == task.id) {
        match result {
            Ok(output) => {
                t.status = "done".into();
                t.progress = 100;
                t.result = Some(output);
            }
            Err(err) => {
                t.status = if cancel.load(Ordering::SeqCst) { "cancelled".into() } else { "failed".into() };
                t.error = Some(err);
            }
        }
        t.finished_at = Some(now_ms());
        finished = Some(t.clone());
    }
    if let Some(task) = finished {
        persist(&inner);
        emit_task(&inner, &task);
        emit(&inner, "tasks_changed", serde_json::json!({}));
    }
    inner.cancel_flags.remove(&task.id);
    if let Some(child) = inner.children.remove(&task.id) {
        if let Ok(mut guard) = child.lock() {
            if let Some(process) = guard.as_mut() {
                let _ = process.kill();
                let _ = process.wait();
            }
        }
    }
}

/// 读取后台任务进程的 stderr，解析 @@P:(进度) 与 @@L:(日志) 标记，实时写回任务。
fn pump_stderr(task_id: &str, stderr: std::process::ChildStderr) {
    use std::io::{BufRead, BufReader};
    let mut last_progress: u32 = 0;
    for raw in BufReader::new(stderr).lines() {
        let line = match raw {
            Ok(line) => line,
            Err(_) => break,
        };
        let (kind, value) = if let Some(v) = line.strip_prefix("@@P:") {
            ("p", v.trim())
        } else if let Some(v) = line.strip_prefix("@@L:") {
            ("l", v.trim())
        } else {
            continue;
        };
        let mut inner = manager().lock().unwrap();
        let snapshot = if let Some(task) = inner.tasks.iter_mut().find(|t| t.id == task_id) {
            if kind == "p" {
                if let Ok(progress) = value.parse::<u32>() {
                    // 只往前走；99 留给实际完成，100 由任务收尾设置。
                    let progress = progress.min(99);
                    if progress > last_progress {
                        last_progress = progress;
                        task.progress = progress;
                    }
                }
            } else if !value.is_empty() {
                task.log.push_str(value);
                task.log.push('\n');
            }
            Some(task.clone())
        } else {
            None
        };
        if let Some(snapshot) = snapshot {
            emit_task(&inner, &snapshot);
        }
    }
}

/// 统一的后台执行：以 `当前程序 --job <kind>` 起一个子进程，参数从 stdin 传入，
/// 结果从 stdout 读回。每个任务一个进程，ONNX / ffmpeg 互不干扰，取消直接 kill。
fn run_child_job(
    task_id: &str,
    kind: &str,
    params: &Value,
    cancel: &Arc<AtomicBool>,
) -> Result<Value, String> {
    use std::io::{Read, Write};

    // 如果任务在子进程启动前就已被取消，直接返回。
    if cancel.load(Ordering::SeqCst) {
        return Err("已停止".into());
    }
    let exe = std::env::current_exe().map_err(|e| format!("找不到应用主程序: {e}"))?;
    let child = Command::new(&exe)
        .arg("--job")
        .arg(kind)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("启动后台进程失败: {e}"))?;
    // 把句柄登记到任务表，cancel() 才能立即 kill 掉它。
    {
        let inner = manager().lock().unwrap();
        if let Some(slot) = inner.children.get(task_id) {
            if let Ok(mut guard) = slot.lock() {
                *guard = Some(child);
            }
        }
    }

    // 从任务表里的句柄上取走 stdin / stdout / stderr（Child 仍留在表里供 cancel 使用）。
    let (stdin, stdout, stderr) = {
        let inner = manager().lock().unwrap();
        let slot = inner
            .children
            .get(task_id)
            .cloned()
            .ok_or_else(|| "任务句柄已释放".to_string())?;
        let mut guard = slot.lock().map_err(|_| "无法读取后台进程输出".to_string())?;
        let child = guard.as_mut().ok_or_else(|| "无法读取后台进程输出".to_string())?;
        (child.stdin.take(), child.stdout.take(), child.stderr.take())
    };

    if let Some(mut stdin) = stdin {
        let _ = write!(stdin, "{}", params);
        // stdin 在这里离开作用域关闭，子进程读参数不会一直等。
    }
    let stdout = stdout.ok_or_else(|| "无法读取后台进程输出".to_string())?;
    let _stderr_thread = stderr.map(|stderr| {
        let tid = task_id.to_string();
        std::thread::spawn(move || pump_stderr(&tid, stderr))
    });

    let mut text = String::new();
    let mut reader = std::io::BufReader::new(stdout);
    let read_result = reader.read_to_string(&mut text);
    if cancel.load(Ordering::SeqCst) {
        return Err("已停止".into());
    }
    read_result.map_err(|e| format!("读取后台进程输出失败: {e}"))?;

    let line = text
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
        .ok_or("后台进程没有返回结果")?
        .trim();
    let response: Value =
        serde_json::from_str(line).map_err(|e| format!("解析后台进程结果失败: {e}"))?;
    if response.get("ok").and_then(Value::as_bool) != Some(true) {
        let message = response
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("后台任务执行失败");
        return Err(message.to_string());
    }
    Ok(response.get("result").cloned().unwrap_or(Value::Null))
}
