//! 后台任务执行器：主程序以 `--job <kind>` 启动时进入这里，一个任务一个进程。
//!
//! 参数 JSON 从 stdin 读入，结果 JSON 写到 stdout；进度与日志用 stderr 的
//! `@@P:` / `@@L:` 标记回传给任务管理器。取消由任务管理器直接 kill 进程完成。

use std::io::Read;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::mdx;
use crate::tools;

/// 资源根目录（包含 `models/`、`bin/` 的那一层），不依赖 Tauri 的 AppHandle。
pub fn resources_dir() -> PathBuf {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(dir) = std::env::var("WHISPER_STUDIO_RESOURCES") {
        if !dir.trim().is_empty() {
            candidates.push(PathBuf::from(dir));
        }
    }
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
    candidates
        .into_iter()
        .find(|dir| dir.join("models").is_dir())
        .unwrap_or_else(|| PathBuf::from("resources"))
}

/// 配置目录，与主程序 `app_config_dir()` 一致（macOS 即 Application Support 下的应用目录）。
fn config_dir() -> PathBuf {
    let home = std::env::var("HOME").ok().map(PathBuf::from);
    #[cfg(target_os = "macos")]
    {
        home.unwrap_or_default()
            .join("Library/Application Support/com.whisperstudio.desktop")
    }
    #[cfg(windows)]
    {
        std::env::var("APPDATA")
            .ok()
            .map(PathBuf::from)
            .or_else(|| home.clone())
            .unwrap_or_default()
            .join("com.whisperstudio.desktop")
    }
    #[cfg(all(not(target_os = "macos"), not(windows)))]
    {
        std::env::var("XDG_CONFIG_HOME")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .map(PathBuf::from)
            .or_else(|| home.clone())
            .unwrap_or_default()
            .join(".config")
            .join("com.whisperstudio.desktop")
    }
}

/// 用户模型目录：放进去的 ggml 模型会被自动列出。
pub fn user_models_dir() -> PathBuf {
    #[cfg(all(not(target_os = "macos"), not(windows)))]
    {
        let home = std::env::var("HOME").ok().map(PathBuf::from).unwrap_or_default();
        return std::env::var("XDG_DATA_HOME")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".local/share"))
            .join("com.whisperstudio.desktop")
            .join("models");
    }
    #[cfg(any(target_os = "macos", windows))]
    {
        config_dir().join("models")
    }
}

pub fn model_search_dirs() -> Vec<PathBuf> {
    vec![user_models_dir(), resources_dir().join("models")]
}

pub fn resolve_model(name: &str) -> Result<PathBuf, String> {
    if name.trim().is_empty() || name.contains('/') || name.contains('\\') || name.contains("..") {
        return Err(format!("非法的模型名：{name}"));
    }
    for dir in model_search_dirs() {
        let path = dir.join(name);
        if path.is_file() {
            return Ok(path);
        }
    }
    Err(format!("找不到模型：{name}"))
}

fn cache_key(path: &Path) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut hasher = DefaultHasher::new();
    path.to_string_lossy().hash(&mut hasher);
    if let Ok(meta) = std::fs::metadata(path) {
        meta.len().hash(&mut hasher);
        if let Ok(modified) = meta.modified() {
            if let Ok(since) = modified.duration_since(std::time::UNIX_EPOCH) {
                since.as_secs().hash(&mut hasher);
            }
        }
    }
    format!("{:016x}", hasher.finish())
}

/* ---------------- 参数取值 ---------------- */

fn opt_str(args: &Value, key: &str) -> Option<String> {
    args.get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(str::to_string)
}

fn req_str(args: &Value, key: &str) -> Result<String, String> {
    opt_str(args, key).ok_or_else(|| format!("缺少 {key}"))
}

fn opt_bool(args: &Value, key: &str) -> Option<bool> {
    args.get(key).and_then(Value::as_bool)
}

fn opt_u32(args: &Value, key: &str) -> Option<u32> {
    args.get(key).and_then(Value::as_u64).map(|value| value as u32)
}

fn opt_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(Value::as_f64)
}

/* ---------------- 转写 ---------------- */

pub struct TranscribeOpts {
    pub model: String,
    pub language: String,
    pub separate: bool,
    pub vad: bool,
    pub suppress_ns: bool,
    pub coreml: bool,
    pub no_context: bool,
    pub prompt: Option<String>,
    pub no_fallback: bool,
    pub beam_size: Option<u32>,
    pub best_of: Option<u32>,
    pub no_speech_thold: Option<f64>,
    pub entropy_thold: f64,
    pub logprob_thold: Option<f64>,
    pub word_thold: Option<f64>,
    pub max_len: Option<u32>,
}

impl TranscribeOpts {
    /// 同时接受桌面端的 `coreml` 与 MCP 的 `acceleration`，其余字段同名。
    pub fn from_value(args: &Value) -> Result<Self, String> {
        Ok(Self {
            model: opt_str(args, "model").unwrap_or_else(|| "ggml-large-v3-turbo-q5_0.bin".to_string()),
            language: opt_str(args, "language").unwrap_or_else(|| "auto".to_string()),
            separate: opt_bool(args, "separate").unwrap_or(true),
            vad: opt_bool(args, "vad").unwrap_or(false),
            suppress_ns: opt_bool(args, "suppress_ns").unwrap_or(true),
            coreml: opt_bool(args, "coreml")
                .or_else(|| opt_bool(args, "acceleration"))
                .unwrap_or(true),
            no_context: opt_bool(args, "no_context").unwrap_or(true),
            prompt: opt_str(args, "prompt"),
            no_fallback: opt_bool(args, "no_fallback").unwrap_or(false),
            beam_size: opt_u32(args, "beam_size"),
            best_of: opt_u32(args, "best_of"),
            no_speech_thold: opt_f64(args, "no_speech_thold"),
            entropy_thold: opt_f64(args, "entropy_thold").unwrap_or(2.8),
            logprob_thold: opt_f64(args, "logprob_thold"),
            word_thold: opt_f64(args, "word_thold"),
            max_len: opt_u32(args, "max_len"),
        })
    }
}

pub fn separate(
    input: &Path,
    on_progress: &mut dyn FnMut(u32),
    on_log: &dyn Fn(&str),
) -> Result<PathBuf, String> {
    let cache_dir = std::env::temp_dir().join("whisper-studio-mcp/separated");
    std::fs::create_dir_all(&cache_dir).map_err(|e| e.to_string())?;
    let vocals = cache_dir.join(mdx::cache_file_name(input, "vocals", &cache_key(input)));
    if vocals.metadata().map(|m| m.len() > 44).unwrap_or(false) {
        on_log("命中已分离人声缓存，跳过分离");
        on_progress(100);
        return Ok(vocals);
    }
    on_log(&format!("开始人声分离：{}", input.display()));
    let root = resources_dir();
    let model = mdx::model_path(Some(root.as_path()))
        .ok_or("找不到 MDX 分离模型：resources/models/UVR-MDX-NET-Inst_HQ_3.onnx 缺失")?;
    let tmp = vocals.with_extension("wav.part");
    let _ = std::fs::remove_file(&tmp);
    mdx::separate_vocals(&model, input, &tmp, on_progress, &|| false)?;
    std::fs::rename(&tmp, &vocals).map_err(|e| format!("写入分离缓存失败: {e}"))?;
    on_log("人声分离完成");
    on_progress(100);
    Ok(vocals)
}

pub fn transcribe(input: &Path, opts: &TranscribeOpts) -> Result<Value, String> {
    if !input.exists() {
        return Err(format!("找不到音频文件: {}", input.display()));
    }
    let root = resources_dir();
    let cli = tools::whisper_cli_path(&root);
    if !cli.exists() {
        return Err(format!("找不到 whisper-cli: {}", cli.display()));
    }
    let model = resolve_model(&opts.model)?;

    let out_dir = std::env::temp_dir().join("whisper-studio-mcp/output");
    std::fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);

    // 进度与日志通过 stderr 带标记回传给任务管理器（stdout 留给最终结果）。
    // 分离占 0-60，转写占 60-100，合起来是连续的 0-100。
    let emit_progress = |p: u32| eprintln!("@@P:{}", p.min(100));
    let emit_log = |line: &str| {
        for part in line.lines().filter(|l| !l.trim().is_empty()) {
            eprintln!("@@L:{}", part);
        }
    };

    let mut audio_path = input.to_path_buf();
    if opts.separate {
        emit_log("阶段：人声分离");
        audio_path = separate(
            input,
            &mut |p| emit_progress(p * 60 / 100),
            &|line| emit_log(line),
        )?;
    }

    let threads = (std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(8)
        / 2)
        .max(1);

    let prompt = opts
        .prompt
        .as_deref()
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(str::to_string);

    let engine_opts = crate::engine::Options {
        cli: cli.clone(),
        model: model.clone(),
        vad_model: if opts.vad {
            let path = root.join("models").join("ggml-silero-v5.1.2.bin");
            path.exists().then_some(path)
        } else {
            None
        },
        language: opts.language.clone(),
        threads: threads as i32,
        suppress_ns: opts.suppress_ns,
        vad: opts.vad,
        coreml: opts.coreml,
        // 与桌面端一致：-mc 0 与初始提示互斥，有提示时不用它。
        no_context: opts.no_context && prompt.is_none(),
        prompt,
        entropy_thold: opts.entropy_thold,
        no_fallback: opts.no_fallback,
        beam_size: opts.beam_size,
        best_of: opts.best_of,
        no_speech_thold: opts.no_speech_thold,
        logprob_thold: opts.logprob_thold,
        word_thold: opts.word_thold,
        max_len: opts.max_len,
        chunk_ms: 30_000,
    };
    emit_log(&format!(
        "阶段：转写（模型 {}，语言 {}）",
        opts.model, opts.language
    ));
    let output = crate::engine::run(
        &audio_path,
        &out_dir,
        stamp,
        &engine_opts,
        &mut |p| emit_progress(60 + p * 40 / 100),
        &mut |line| emit_log(line),
        &|| false,
    )?;
    emit_log(&format!("转写完成，共 {} 字", output.text.trim().chars().count()));
    if output.text.trim().is_empty() {
        return Err(if opts.vad {
            "没有检测到语音（纯音乐或静音片段已被跳过）".into()
        } else {
            "没有识别到任何内容".into()
        });
    }
    Ok(json!({
        "text": output.text.trim(),
        "srt": output.srt,
        "audio_used": audio_path.display().to_string()
    }))
}

/* ---------------- 任务分发 ---------------- */

pub fn run(kind: &str, params: &Value) -> Result<Value, String> {
    tools::set_resources(resources_dir());
    match kind {
        "transcribe" => {
            let input = PathBuf::from(req_str(params, "input_path")?);
            let opts = TranscribeOpts::from_value(params)?;
            transcribe(&input, &opts)
        }
        "convert" => {
            let conversion: crate::convert::ConvertArgs = serde_json::from_value(params.clone())
                .map_err(|e| format!("参数不合法: {e}"))?;
            let output = conversion.output.clone();
            crate::convert::convert_with(
                &conversion,
                &mut |percent| eprintln!("@@P:{}", percent.min(99.0) as u32),
                &|| false,
            )?;
            Ok(json!({ "path": output, "name": base_name(&output) }))
        }
        "tags" => {
            let path = req_str(params, "path")?;
            let tags = params.get("tags").cloned().ok_or("缺少 tags")?;
            if !tags.is_object() {
                return Err("tags 必须是 JSON 对象".into());
            }
            crate::media::media_write_tags(path.clone(), tags)?;
            Ok(json!({ "path": path, "name": base_name(&path), "written": true }))
        }
        "cover" => {
            let path = req_str(params, "path")?;
            let action = opt_str(params, "action").unwrap_or_else(|| "set".into());
            if action == "remove" {
                crate::media::media_remove_cover(path.clone())?;
                Ok(json!({ "path": path, "name": base_name(&path), "removed": true }))
            } else {
                let image = req_str(params, "image")?;
                crate::media::media_set_cover(path.clone(), image)?;
                Ok(json!({ "path": path, "name": base_name(&path), "written": true }))
            }
        }
        "rename" => {
            let path = req_str(params, "path")?;
            let filename = req_str(params, "filename")?;
            let next = crate::media::media_rename(path, filename)?;
            Ok(json!({ "path": next, "name": base_name(&next) }))
        }
        "batch_rename" => {
            let dir = req_str(params, "dir")?;
            let pattern = opt_str(params, "pattern").unwrap_or_else(|| "artist_title".into());
            let items = crate::media::media_scan_folder(dir.clone())?;
            let mut plan: Vec<Value> = Vec::with_capacity(items.len());
            let mut renamed = 0usize;
            for item in items {
                let path = item
                    .get("path")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string();
                let current = item
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string();
                let tags = item
                    .get("info")
                    .and_then(|info| info.get("tags"))
                    .cloned()
                    .unwrap_or_else(|| json!({}));
                let title = tags.get("title").and_then(Value::as_str).map(str::to_string);
                let artist = tags.get("artist").and_then(Value::as_str).map(str::to_string);
                let target = crate::media::media_build_name(title, artist, pattern.clone());
                let entry = match target {
                    None => json!({ "from": current, "skipped": true, "reason": "标签不足" }),
                    Some(target) => {
                        let ext = current
                            .rfind('.')
                            .map(|index| current[index..].to_string())
                            .unwrap_or_default();
                        let preview = format!("{target}{ext}");
                        if preview == current {
                            json!({ "from": current, "to": preview, "skipped": true, "reason": "同名" })
                        } else {
                            match crate::media::media_rename(path, target) {
                                Ok(next) => {
                                    renamed += 1;
                                    eprintln!("@@L:{} -> {}", current, base_name(&next));
                                    json!({ "from": current, "to": base_name(&next), "path": next })
                                }
                                Err(err) => {
                                    eprintln!("@@L:{} 失败：{}", current, err);
                                    json!({ "from": current, "to": preview, "error": err })
                                }
                            }
                        }
                    }
                };
                plan.push(entry);
            }
            Ok(json!({
                "dir": dir,
                "pattern": pattern,
                "renamed": renamed,
                "items": plan
            }))
        }
        other => Err(format!("未知任务类型: {other}")),
    }
}

fn base_name(path: &str) -> String {
    path.rsplit(|c| c == '/' || c == '\\')
        .next()
        .unwrap_or(path)
        .to_string()
}

/// `--job` 模式的入口：读 stdin 参数，跑完在 stdout 输出一行 JSON。
pub fn run_cli(kind: &str) -> i32 {
    let mut raw = String::new();
    if std::io::stdin().read_to_string(&mut raw).is_err() {
        println!("{}", json!({ "ok": false, "error": "读取任务参数失败" }));
        return 2;
    }
    let params: Value = if raw.trim().is_empty() {
        json!({})
    } else {
        match serde_json::from_str(&raw) {
            Ok(value) => value,
            Err(err) => {
                println!("{}", json!({ "ok": false, "error": format!("任务参数不合法: {err}") }));
                return 2;
            }
        }
    };
    match run(kind, &params) {
        Ok(result) => {
            println!("{}", json!({ "ok": true, "result": result }));
            0
        }
        Err(err) => {
            println!("{}", json!({ "ok": false, "error": err }));
            1
        }
    }
}
