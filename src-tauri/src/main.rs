use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde::Deserialize;
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

mod convert;
mod engine;
mod mcp_server;
mod mdx;
mod media;
mod task_manager;
mod tools;

use tauri::{WebviewUrl, WebviewWindowBuilder};

fn resources_dir(app: &tauri::AppHandle) -> PathBuf {
    let mut candidates: Vec<PathBuf> = Vec::new();
    // 跨平台：允许用环境变量显式指定资源目录。
    if let Ok(dir) = std::env::var("WHISPER_STUDIO_RESOURCES") {
        if !dir.trim().is_empty() {
            candidates.push(PathBuf::from(dir));
        }
    }
    if let Ok(dir) = app.path().resource_dir() {
        candidates.push(dir.join("resources"));
        candidates.push(dir);
    }
    // 全部按运行时位置推导，不把开发机的绝对路径编进二进制。
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidates.push(parent.join("../Resources/resources"));
            candidates.push(parent.join("resources"));
            // 开发布局：可执行文件在 target/debug/，往上两级是 src-tauri/resources。
            let mut up = parent.to_path_buf();
            for _ in 0..4 {
                if let Some(parent) = up.parent() {
                    up = parent.to_path_buf();
                    candidates.push(up.join("resources"));
                }
            }
        }
    }
    for candidate in &candidates {
        if candidate.join("models").is_dir() {
            return candidate.clone();
        }
    }
    candidates
        .into_iter()
        .next()
        .unwrap_or_else(|| PathBuf::from("resources"))
}

/* ---------------- 应用内运行日志 ---------------- */

/// 调试日志总开关，与设置里的 debugLog 同步（AtomicBool 便于跨线程读取）。
static DEBUG_LOG: AtomicBool = AtomicBool::new(false);

#[tauri::command]
fn debug_log_enabled() -> bool {
    DEBUG_LOG.load(Ordering::SeqCst)
}

#[tauri::command]
fn debug_log_set_enabled(enabled: bool) {
    DEBUG_LOG.store(enabled, Ordering::SeqCst);
}

fn run_logs_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .app_log_dir()
        .map_err(|e| e.to_string())?
        .join("runs"))
}

#[tauri::command]
fn logs_dir(app: tauri::AppHandle) -> Result<String, String> {
    Ok(run_logs_dir(&app)?.display().to_string())
}

/// 在系统文件管理器里打开某个目录（按平台选命令）。
fn reveal_dir(dir: &std::path::Path) -> Result<(), String> {
    fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let mut cmd = if cfg!(windows) {
        let mut c = Command::new("explorer");
        c.arg(dir);
        c
    } else if cfg!(target_os = "macos") {
        let mut c = Command::new("open");
        c.arg(dir);
        c
    } else {
        let mut c = Command::new("xdg-open");
        c.arg(dir);
        c
    };
    cmd.spawn().map_err(|e| format!("打开目录失败: {e}"))?;
    Ok(())
}

#[tauri::command]
fn open_logs_dir(app: tauri::AppHandle) -> Result<(), String> {
    reveal_dir(&run_logs_dir(&app)?)
}

/// 打开随包的许可文件目录（GPL 全文、第三方声明），方便用户查看与留存。
#[tauri::command]
fn open_licenses_dir(app: tauri::AppHandle) -> Result<(), String> {
    reveal_dir(&resources_dir(&app).join("licenses"))
}

/* ---------------- 系统文件选择面板 ---------------- */

/// 用系统自带的「选择文件」面板挑一个文件，不做扩展名过滤。
/// 插件那套面板按扩展名匹配，`.MOV` 这类大写后缀会被卡掉；换成系统面板后什么都能选，
/// 能不能用交给选完后的后端检测（media_probe）。用户取消返回 None，
/// 平台不支持或调起失败返回 Err，由前端回退到应用内对话框。
#[tauri::command]
async fn pick_media_file() -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(pick_media_file_blocking)
        .await
        .map_err(|e| format!("选择面板执行失败：{e}"))?
}

#[cfg(target_os = "macos")]
fn pick_media_file_blocking() -> Result<Option<String>, String> {
    let script = "set picked to choose file with prompt \"选择要处理的音视频文件\"\nreturn POSIX path of picked";
    let output = Command::new("osascript")
        .arg("-e")
        .arg(script)
        .output()
        .map_err(|e| format!("调起系统面板失败：{e}"))?;
    if output.status.success() {
        let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Ok((!path.is_empty()).then_some(path));
    }
    let err = String::from_utf8_lossy(&output.stderr).trim().to_string();
    // 用户点取消时 osascript 以 -128 结束，这不是故障。
    if err.contains("-128") || err.contains("User canceled") {
        return Ok(None);
    }
    Err(format!("系统面板失败：{err}"))
}

#[cfg(not(target_os = "macos"))]
fn pick_media_file_blocking() -> Result<Option<String>, String> {
    Err("当前平台暂不支持系统选择面板".into())
}

/* ---------------- 产物清理 ---------------- */

/// 应用自己生成的中间产物：人声分离缓存、转写临时输出、运行日志。
/// 一律在应用数据目录内，不碰用户指定目录里的成品。
fn artifact_dirs(app: &tauri::AppHandle) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(dir) = app.path().app_cache_dir() {
        dirs.push(dir.join("separated"));
        dirs.push(dir.join("output"));
    }
    if let Ok(dir) = run_logs_dir(app) {
        dirs.push(dir);
    }
    dirs
}

/// 递归统计体积；符号链接一律跳过，免得把链接指向的外面文件也算进来。
fn dir_usage(dir: &std::path::Path) -> (u64, u64) {
    let mut files = 0u64;
    let mut bytes = 0u64;
    let Ok(entries) = fs::read_dir(dir) else {
        return (0, 0);
    };
    for entry in entries.flatten() {
        let Ok(kind) = entry.file_type() else {
            continue;
        };
        if kind.is_symlink() {
            continue;
        }
        if kind.is_dir() {
            let (f, b) = dir_usage(&entry.path());
            files += f;
            bytes += b;
        } else if kind.is_file() {
            if let Ok(meta) = entry.metadata() {
                files += 1;
                bytes += meta.len();
            }
        }
    }
    (files, bytes)
}

/// 清空目录内容但保留目录本身；删不掉的条目跳过，不因一个文件失败而中断。
/// 符号链接只跳过不跟随，避免顺着链接删到应用数据目录之外。
fn clear_dir(dir: &std::path::Path) -> (u64, u64) {
    let mut files = 0u64;
    let mut bytes = 0u64;
    let Ok(entries) = fs::read_dir(dir) else {
        return (0, 0);
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Ok(kind) = entry.file_type() else {
            continue;
        };
        if kind.is_symlink() {
            continue;
        }
        if kind.is_dir() {
            let (f, b) = clear_dir(&path);
            files += f;
            bytes += b;
            let _ = fs::remove_dir(&path);
        } else if kind.is_file() {
            let size = entry.metadata().map(|m| m.len()).unwrap_or(0);
            if fs::remove_file(&path).is_ok() {
                files += 1;
                bytes += size;
            }
        }
    }
    (files, bytes)
}

/// 清理前的提示文案要用：产物当前占多大。
#[tauri::command]
fn artifacts_usage(app: tauri::AppHandle) -> serde_json::Value {
    let mut files = 0u64;
    let mut bytes = 0u64;
    for dir in artifact_dirs(&app) {
        let (f, b) = dir_usage(&dir);
        files += f;
        bytes += b;
    }
    serde_json::json!({ "files": files, "bytes": bytes })
}

/// 清空产物。有任务在跑时目录正被写入，直接拒绝，免得把运行中的任务弄坏。
#[tauri::command]
fn clean_artifacts(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let busy = running_work();
    if !busy.is_empty() {
        return Err(format!("{busy}，先取消或等它结束再清理产物"));
    }
    let mut files = 0u64;
    let mut bytes = 0u64;
    for dir in artifact_dirs(&app) {
        let (f, b) = clear_dir(&dir);
        files += f;
        bytes += b;
    }
    Ok(serde_json::json!({ "files": files, "bytes": bytes }))
}

/// 一次运行对应一个日志文件；关闭调试时所有写入都是空操作。
struct RunLogger {
    file: Option<Mutex<fs::File>>,
    started: Instant,
}

impl RunLogger {
    fn start(app: &tauri::AppHandle, tag: &str) -> Self {
        let started = Instant::now();
        if !DEBUG_LOG.load(Ordering::SeqCst) {
            return Self { file: None, started };
        }
        let dir = match run_logs_dir(app) {
            Ok(dir) => dir,
            Err(err) => {
                eprintln!("日志目录不可用：{err}");
                return Self { file: None, started };
            }
        };
        if let Err(err) = fs::create_dir_all(&dir) {
            eprintln!("创建日志目录失败：{err}");
            return Self { file: None, started };
        }
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis())
            .unwrap_or(0);
        let name = format!("run-{millis}-{}-{tag}.log", std::process::id());
        match OpenOptions::new().create(true).append(true).open(dir.join(&name)) {
            Ok(file) => Self { file: Some(Mutex::new(file)), started },
            Err(err) => {
                eprintln!("创建日志文件失败：{err}");
                Self { file: None, started }
            }
        }
    }

    fn line(&self, text: &str) {
        if let Some(file) = &self.file {
            if let Ok(mut file) = file.lock() {
                let elapsed = self.started.elapsed().as_millis();
                let _ = writeln!(file, "[{elapsed:>7} ms] {text}");
                let _ = file.flush();
            }
        }
    }
}

/* ---------------- 模型目录 ---------------- */

/// 用户自己放模型的目录：应用数据目录下的 `models/`，可自由添加/删除。
/// macOS：~/Library/Application Support/com.whisperstudio.desktop/models
fn user_models_dir(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path().app_data_dir().ok().map(|dir| dir.join("models"))
}

/// 模型查找顺序：用户目录优先，其次随包资源目录。
fn model_search_dirs(app: &tauri::AppHandle) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Some(dir) = user_models_dir(app) {
        dirs.push(dir);
    }
    dirs.push(resources_dir(app).join("models"));
    dirs
}

/// 能用于转写的模型只认 ggml 格式的 whisper 权重：`.bin` 且不是 VAD（silero）。
fn is_transcribe_model(name: &str) -> bool {
    name.ends_with(".bin") && !name.to_ascii_lowercase().contains("silero")
}

#[tauri::command]
fn list_models(app: tauri::AppHandle) -> Vec<String> {
    let mut names = std::collections::BTreeSet::new();
    for dir in model_search_dirs(&app) {
        let Ok(entries) = fs::read_dir(dir) else {
            continue;
        };
        for name in entries.flatten().filter_map(|e| e.file_name().into_string().ok()) {
            if is_transcribe_model(&name) {
                names.insert(name);
            }
        }
    }
    names.into_iter().collect()
}

/// 把前端传来的模型名解析成真实路径；拒绝带路径分隔符的名字，避免越出模型目录。
fn resolve_model(app: &tauri::AppHandle, name: &str) -> Result<PathBuf, String> {
    if name.trim().is_empty()
        || name.contains('/')
        || name.contains('\\')
        || name.contains("..")
    {
        return Err(format!("非法的模型名：{name}"));
    }
    for dir in model_search_dirs(app) {
        let path = dir.join(name);
        if path.is_file() {
            return Ok(path);
        }
    }
    Err(format!("找不到模型：{name}"))
}

/// 返回用户模型目录的绝对路径（不存在则创建），用于界面提示。
#[tauri::command]
fn models_dir(app: tauri::AppHandle) -> Result<String, String> {
    let dir = user_models_dir(&app).ok_or("无法定位应用数据目录")?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.display().to_string())
}

/// 打开用户模型目录，方便直接拖模型进去。
#[tauri::command]
fn open_models_dir(app: tauri::AppHandle) -> Result<(), String> {
    let dir = user_models_dir(&app).ok_or("无法定位应用数据目录")?;
    reveal_dir(&dir)
}

#[derive(Deserialize, Default, Debug)]
struct Advanced {
    prompt: Option<String>,
    #[serde(default)]
    no_fallback: bool,
    beam_size: Option<u32>,
    best_of: Option<u32>,
    no_speech_thold: Option<f64>,
    entropy_thold: Option<f64>,
    logprob_thold: Option<f64>,
    word_thold: Option<f64>,
    max_len: Option<u32>,
}

#[derive(Deserialize)]
struct TranscribeArgs {
    audio: String,
    model: String,
    lang: String,
    suppress_ns: bool,
    no_context: bool,
    #[serde(default)]
    vad: bool,
    #[serde(default)]
    separate: bool,
    #[serde(default)]
    advanced: Advanced,
}

fn emit_progress(app: &tauri::AppHandle, stage: &str, detail: u32, overall: u32) {
    let _ = app.emit(
        "progress",
        serde_json::json!({ "stage": stage, "detail": detail, "percent": overall }),
    );
}

fn cache_key(path: &std::path::Path) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut hasher = DefaultHasher::new();
    path.to_string_lossy().hash(&mut hasher);
    if let Ok(meta) = fs::metadata(path) {
        meta.len().hash(&mut hasher);
        if let Ok(modified) = meta.modified() {
            if let Ok(since) = modified.duration_since(std::time::UNIX_EPOCH) {
                since.as_secs().hash(&mut hasher);
            }
        }
    }
    format!("{:016x}", hasher.finish())
}

fn settings_file(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    Ok(dir.join("settings.json"))
}

#[tauri::command]
fn settings_path(app: tauri::AppHandle) -> Result<String, String> {
    Ok(settings_file(&app)?.display().to_string())
}

#[tauri::command]
fn mcp_enabled() -> bool {
    mcp_server::is_enabled()
}

#[tauri::command]
fn mcp_set_enabled(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    let result = mcp_server::set_enabled(enabled);
    let logger = RunLogger::start(&app, "mcp");
    match &result {
        Ok(()) => logger.line(&format!("MCP 已{}", if enabled { "开启" } else { "关闭" })),
        Err(err) => logger.line(&format!("MCP 切换失败：{err}")),
    }
    result
}

#[tauri::command]
fn load_settings(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let path = settings_file(&app)?;
    let raw = match fs::read_to_string(&path) {
        Ok(raw) => raw,
        Err(_) => return Ok(serde_json::json!({})),
    };
    match serde_json::from_str::<serde_json::Value>(&raw) {
        Ok(value) if value.is_object() => Ok(value),
        _ => {
            // 文件坏了就留一份备份，然后按空设置启动；下次保存会直接覆盖原文件。
            let _ = fs::rename(&path, path.with_extension("json.corrupt"));
            Ok(serde_json::json!({}))
        }
    }
}

#[tauri::command]
fn save_settings(app: tauri::AppHandle, data: serde_json::Value) -> Result<(), String> {
    if let Some(enabled) = data.get("debugLog").and_then(|v| v.as_bool()) {
        DEBUG_LOG.store(enabled, Ordering::SeqCst);
    }
    let path = settings_file(&app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let pretty = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
    // 先写临时文件再改名，避免写到一半崩溃留下半截 JSON。
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, pretty).map_err(|e| e.to_string())?;
    fs::rename(&tmp, &path).map_err(|e| e.to_string())
}

/// 界面上的「开始转写」不经过任务队列，单独用一个开关登记它还在跑。
static TRANSCRIBING: AtomicBool = AtomicBool::new(false);

/// 标记一段工作在跑，作用域结束自动复位；中途报错也不会卡在「运行中」。
struct BusyGuard<'a>(&'a AtomicBool);

impl<'a> BusyGuard<'a> {
    fn new(flag: &'a AtomicBool) -> Self {
        flag.store(true, Ordering::SeqCst);
        Self(flag)
    }
}

impl Drop for BusyGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

#[derive(Default)]
struct JobState(AtomicBool);

#[tauri::command]
fn cancel_transcribe(state: tauri::State<'_, JobState>) {
    state.0.store(true, Ordering::SeqCst);
}

#[tauri::command]
async fn transcribe(app: tauri::AppHandle, args: TranscribeArgs) -> Result<serde_json::Value, String> {
    app.state::<JobState>().0.store(false, Ordering::SeqCst);
    let _busy = BusyGuard::new(&TRANSCRIBING);
    // DSP 和 ONNX 推理都是纯 CPU 活儿，放在主线程会直接把界面卡成转圈。
    tauri::async_runtime::spawn_blocking(move || run_transcribe(&app, args))
        .await
        .map_err(|e| format!("任务执行失败: {e}"))?
}

/// 外层负责建一份「本次转写」日志并统一收尾，内部所有早退出的错误都会被记下来。
fn run_transcribe(app: &tauri::AppHandle, args: TranscribeArgs) -> Result<serde_json::Value, String> {
    let logger = RunLogger::start(app, "transcribe");
    logger.line("=== 转写开始 ===");
    logger.line(&format!("音频：{}", args.audio));
    logger.line(&format!(
        "模型：{}　语言：{}　分离：{}　VAD：{}",
        args.model, args.lang, args.separate, args.vad
    ));
    logger.line(&format!(
        "其它选项：抑制口头语={} 关闭上下文={} 高级参数={:?}",
        args.suppress_ns, args.no_context, args.advanced
    ));
    logger.line(&format!("whisper-cli：{}", tools::whisper_cli_path(&resources_dir(app)).display()));
    let result = run_transcribe_inner(app, args, &logger);
    match &result {
        Ok(value) => {
            let chars = value
                .get("text")
                .and_then(|v| v.as_str())
                .map(|s| s.chars().count())
                .unwrap_or(0);
            logger.line(&format!("=== 转写成功（文本 {chars} 字）==="));
        }
        Err(err) => logger.line(&format!("=== 转写失败：{err} ===")),
    }
    result
}

fn run_transcribe_inner(
    app: &tauri::AppHandle,
    args: TranscribeArgs,
    logger: &RunLogger,
) -> Result<serde_json::Value, String> {
    let state = app.state::<JobState>();
    let cancelled = || state.0.load(Ordering::SeqCst);
    let root = resources_dir(&app);
    let cli = tools::whisper_cli_path(&root);
    if !cli.exists() {
        return Err(format!("找不到 whisper-cli: {}", cli.display()));
    }
    // 模型可能来自用户目录或随包资源目录，统一在这里解析。
    let model = resolve_model(&app, &args.model)?;

    let out_dir = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join("output");
    fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;
    // 每次用独立前缀，避免读到上一次遗留的结果文件。
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let prefix = out_dir.join(format!("transcript-{stamp}"));
    let _ = &prefix;

    let mut audio_path = PathBuf::from(&args.audio);
    if args.separate {
        // 分离结果按「源文件路径 + 大小 + 修改时间」缓存到固定目录，重复转写不再重算。
        let cache_dir = app
            .path()
            .app_cache_dir()
            .map_err(|e| e.to_string())?
            .join("separated");
        fs::create_dir_all(&cache_dir).map_err(|e| e.to_string())?;
        let vocals = cache_dir.join(mdx::cache_file_name(&audio_path, "vocals", &cache_key(&audio_path)));

        let cached = vocals
            .metadata()
            .map(|m| m.len() > 44)
            .unwrap_or(false);
        if cached {
            let msg = format!("使用已分离缓存: {}", vocals.display());
            logger.line(&msg);
            let _ = app.emit("process", serde_json::json!({ "line": msg }));
            emit_progress(app, "separate", 100, 70);
        } else {
            let model = mdx::model_path(Some(root.as_path())).ok_or_else(|| {
                "找不到 MDX 分离模型：resources/models/UVR-MDX-NET-Inst_HQ_3.onnx 缺失".to_string()
            })?;
            let tmp = vocals.with_extension("wav.part");
            let _ = fs::remove_file(&tmp);
            emit_progress(app, "separate", 0, 0);
            let outcome = mdx::separate_vocals(
                &model,
                &audio_path,
                &tmp,
                &mut |percent| {
                    emit_progress(app, "separate", percent, percent * 70 / 100);
                },
                &cancelled,
            );
            if let Err(err) = outcome {
                let _ = fs::remove_file(&tmp);
                return Err(err);
            }
            fs::rename(&tmp, &vocals).map_err(|e| format!("写入分离缓存失败: {e}"))?;
        }
        audio_path = vocals;
    }

    let threads = (std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(8)
        / 2)
        .max(1);

    let adv = args.advanced;
    let prompt = adv
        .prompt
        .as_deref()
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .map(str::to_string);
    let vad_model = if args.vad {
        let path = root.join("models").join("ggml-silero-v5.1.2.bin");
        path.exists().then_some(path)
    } else {
        None
    };
    let opts = engine::Options {
        cli: cli.clone(),
        model: model.clone(),
        vad_model,
        language: args.lang.clone(),
        threads: threads as i32,
        suppress_ns: args.suppress_ns,
        vad: args.vad,
        // -mc 0 blocks the initial prompt entirely, so it only applies without a prompt.
        no_context: args.no_context && prompt.is_none(),
        prompt,
        entropy_thold: adv.entropy_thold.unwrap_or(2.8),
        no_fallback: adv.no_fallback,
        beam_size: adv.beam_size,
        best_of: adv.best_of,
        no_speech_thold: adv.no_speech_thold,
        logprob_thold: adv.logprob_thold,
        word_thold: adv.word_thold,
        max_len: adv.max_len,
        chunk_ms: 30_000,
    };

    // 分离占前 70%，转写占后 30%；不分离时转写独占 0-100%。
    let (base, span) = if args.separate { (70u32, 30u32) } else { (0u32, 100u32) };
    let output = engine::run(
        &audio_path,
        &out_dir,
        stamp,
        &opts,
        &mut |percent| {
            logger.line(&format!("转写进度：{percent}%"));
            emit_progress(app, "transcribe", percent, base + percent * span / 100);
        },
        &mut |line| {
            logger.line(line);
            let _ = app.emit("process", serde_json::json!({ "line": line }));
        },
        &cancelled,
    )?;

    if output.text.trim().is_empty() {
        return Err(if args.vad {
            "没有检测到语音（纯音乐或静音片段已被跳过）".into()
        } else {
            "没有识别到任何内容".into()
        });
    }
    Ok(serde_json::json!({ "text": output.text.trim(), "srt": output.srt }))
}

#[tauri::command]
fn save_text(path: String, content: String) -> Result<(), String> {
    fs::write(path, content).map_err(|e| e.to_string())
}

/// 盘点本机 ffmpeg 支持的编码器 / 容器 / 滤镜 / 像素格式 / 硬件加速。
#[tauri::command]
fn ffmpeg_capabilities() -> serde_json::Value {
    convert::capabilities()
}

/// 场景预设：一组常用参数组合，与 MCP 共用同一份定义。
#[tauri::command]
fn convert_presets() -> serde_json::Value {
    convert::presets()
}

/* ---------------- 统一任务队列 ---------------- */

#[tauri::command]
fn submit_task(params: task_manager::JobParams, source: String, title: String) -> String {
    task_manager::submit(params, &source, title)
}

#[tauri::command]
fn list_tasks() -> Vec<task_manager::Task> {
    task_manager::list()
}

#[tauri::command]
fn get_task(id: String) -> Option<task_manager::Task> {
    task_manager::get(&id)
}

#[tauri::command]
fn cancel_task(id: String) -> Result<(), String> {
    task_manager::cancel(&id)
}

#[tauri::command]
fn clear_finished_tasks() -> usize {
    task_manager::clear_finished()
}

#[tauri::command]
fn set_task_concurrency(app: tauri::AppHandle, n: usize) -> Result<usize, String> {
    let n = task_manager::set_concurrency(n);
    let mut settings = load_settings(app.clone())?;
    settings["taskConcurrency"] = serde_json::json!(n);
    save_settings(app, settings)?;
    Ok(n)
}

#[tauri::command]
fn task_concurrency() -> usize {
    task_manager::get_concurrency()
}

#[tauri::command]
fn open_tasks_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("tasks") {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }
    WebviewWindowBuilder::new(&app, "tasks", WebviewUrl::App("tasks.html".into()))
        .title("任务列表")
        .inner_size(520.0, 620.0)
        .min_inner_size(380.0, 320.0)
        .center()
        .build()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn open_task_detail(app: tauri::AppHandle, id: String) -> Result<(), String> {
    let label = format!("task-{}", id.replace(|c: char| !c.is_ascii_alphanumeric() && c != '-', "_"));
    if let Some(window) = app.get_webview_window(&label) {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }
    WebviewWindowBuilder::new(
        &app,
        &label,
        WebviewUrl::App(format!("task-detail.html?id={}", urlencode(&id)).into()),
    )
    .title("任务详情")
    .inner_size(680.0, 720.0)
    .min_inner_size(420.0, 360.0)
    .center()
    .build()
    .map_err(|e| e.to_string())?;
    Ok(())
}

fn urlencode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' => out.push(b as char),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/* ---------------- 关窗确认 ---------------- */

/// 用户已经确认过退出：之后的关窗 / 退出请求不再拦。
static EXIT_CONFIRMED: AtomicBool = AtomicBool::new(false);
/// 确认框已经弹着：避免关窗和 Cmd+Q 各弹一个叠在一起。
static EXIT_CONFIRMING: AtomicBool = AtomicBool::new(false);

/// 汇总当前还在跑的工作；空串表示可以放心退出。
fn running_work() -> String {
    let (running, queued) = task_manager::active_counts();
    let mut parts: Vec<String> = Vec::new();
    if running > 0 {
        parts.push(format!("{running} 个任务正在运行"));
    }
    if queued > 0 {
        parts.push(format!("{queued} 个任务在排队"));
    }
    if convert::is_running() {
        parts.push("格式转换进行中".to_string());
    }
    if TRANSCRIBING.load(Ordering::SeqCst) {
        parts.push("转写进行中".to_string());
    }
    parts.join("，")
}

/// 有活在跑时问一句再退：没活直接退，有活等用户点头。
fn confirm_quit(app: &tauri::AppHandle) {
    let detail = running_work();
    if detail.is_empty() {
        EXIT_CONFIRMED.store(true, Ordering::SeqCst);
        app.exit(0);
        return;
    }
    if EXIT_CONFIRMING.swap(true, Ordering::SeqCst) {
        return;
    }
    let handle = app.clone();
    let dialog = app
        .dialog()
        .message(format!(
            "{detail}。\n现在退出会中断这些任务，已跑出的部分不会保留。"
        ))
        .title("还有任务在运行")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "中断并退出".to_string(),
            "继续等待".to_string(),
        ));
    let confirm = move |confirmed: bool| {
        EXIT_CONFIRMING.store(false, Ordering::SeqCst);
        if !confirmed {
            return;
        }
        EXIT_CONFIRMED.store(true, Ordering::SeqCst);
        // 先把子进程收掉，别让它们脱离应用继续占着 CPU。
        handle.state::<JobState>().0.store(true, Ordering::SeqCst);
        convert::cancel_convert();
        task_manager::cancel_all_active();
        handle.exit(0);
    };
    // 挂在主窗口上弹成表单（macOS 是窗口下拉的 sheet），不接就退化成独立弹窗。
    match app.get_webview_window("main") {
        Some(window) => dialog.parent(&window).show(confirm),
        None => dialog.show(confirm),
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(JobState::default())
        .setup(|app| {
            // 先把资源目录登记给 tools，之后 ffmpeg / ffprobe 一律优先用包内副本。
            tools::set_resources(resources_dir(app.handle()));
            let settings = load_settings(app.handle().clone()).unwrap_or_default();
            // MCP 端点是否开放由设置决定；关闭时不占端口，不常驻空转。
            let enabled = settings
                .get("mcpEnabled")
                .and_then(|v| v.as_bool())
                .unwrap_or(true);
            if let Err(err) = mcp_server::start_if(enabled) {
                eprintln!("MCP 启动失败：{err}");
            }
            // 统一任务队列：并发数来自设置（默认 2，上限 100）。
            let concurrency = settings
                .get("taskConcurrency")
                .and_then(|v| v.as_u64())
                .unwrap_or(2)
                .clamp(1, 100) as usize;
            if let Err(err) = task_manager::init(app.handle(), concurrency) {
                eprintln!("任务管理器启动失败：{err}");
            }
            // 调试日志在启动时恢复；应用自身也留一份启动记录。
            let debug_log = settings
                .get("debugLog")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            DEBUG_LOG.store(debug_log, Ordering::SeqCst);
            if debug_log {
                let logger = RunLogger::start(app.handle(), "app");
                logger.line(&format!("=== 应用启动（v{}）===", env!("CARGO_PKG_VERSION")));
                logger.line(&format!("资源目录：{}", resources_dir(app.handle()).display()));
                if let Ok(path) = settings_file(app.handle()) {
                    logger.line(&format!("设置文件：{}", path.display()));
                }
                logger.line(&format!("MCP：{}", if enabled { "开启" } else { "关闭" }));
            }
            Ok(())
        })
        // 关窗先看一眼有没有活在跑：没活照常关，有活拦下来问一句。
        .on_window_event(|window, event| {
            if window.label() != "main" {
                return;
            }
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if EXIT_CONFIRMED.load(Ordering::SeqCst) || running_work().is_empty() {
                    return;
                }
                api.prevent_close();
                confirm_quit(window.app_handle());
            }
        })
        .invoke_handler(tauri::generate_handler![
            list_models,
            models_dir,
            open_models_dir,
            transcribe,
            cancel_transcribe,
            save_text,
            load_settings,
            save_settings,
            settings_path,
            mcp_enabled,
            mcp_set_enabled,
            debug_log_enabled,
            debug_log_set_enabled,
            logs_dir,
            open_logs_dir,
            open_licenses_dir,
            pick_media_file,
            artifacts_usage,
            clean_artifacts,
            media::media_info,
            media::media_probe,
            media::media_write_tags,
            media::media_read_text,
            media::media_read_cover,
            media::media_set_cover,
            media::media_remove_cover,
            media::media_rename,
            media::media_scan_folder,
            media::media_build_name,
            ffmpeg_capabilities,
            convert_presets,
            submit_task,
            list_tasks,
            get_task,
            cancel_task,
            clear_finished_tasks,
            set_task_concurrency,
            task_concurrency,
            open_tasks_window,
            open_task_detail,
            convert::unique_output_path,
            convert::convert_media,
            convert::cancel_convert
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app, event| {
        // Cmd+Q / 程序坞退出走的是 ExitRequested，不走关窗，这里同样拦一次。
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            if EXIT_CONFIRMED.load(Ordering::SeqCst) || running_work().is_empty() {
                return;
            }
            api.prevent_exit();
            confirm_quit(app);
        }
    });
}
