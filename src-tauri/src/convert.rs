//! 格式转换：封装系统 ffmpeg，桌面端与 MCP 共用同一套拼参逻辑。
//!
//! 覆盖范围分三层：
//! 1. 结构化字段：常用参数（编码、质量、帧率、分辨率、采样率、声道、裁剪、流选择、元数据）；
//! 2. 能力自动发现：运行时读 `-encoders / -formats / -filters / -pix_fmts / -hwaccels`，
//!    前端下拉用真实可用项，不再写死几个编码器；
//! 3. 任意参数透传：`extra_args` 原样追加到命令行，没做成字段的功能都从这里走。

use serde::Deserialize;
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};

use tauri::Emitter;

pub static CANCEL: AtomicBool = AtomicBool::new(false);
/// 是否正在转换；关窗确认靠它判断「还有活在跑」，与 CANCEL 不是一回事。
static RUNNING: AtomicBool = AtomicBool::new(false);

pub fn is_running() -> bool {
    RUNNING.load(Ordering::SeqCst)
}

/// 作用域结束自动复位，转换中途报错也不会把状态卡在「运行中」。
struct RunningGuard;

impl RunningGuard {
    fn enter() -> Self {
        RUNNING.store(true, Ordering::SeqCst);
        Self
    }
}

impl Drop for RunningGuard {
    fn drop(&mut self) {
        RUNNING.store(false, Ordering::SeqCst);
    }
}

const VIDEO_PRESETS: &[&str] = &[
    "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower",
    "veryslow", "placebo",
];
const TUNES: &[&str] = &["film", "animation", "grain", "stillimage", "fastdecode", "zerolatency"];
const PROFILES: &[&str] = &["baseline", "main", "high", "high10", "high422", "high444"];
const LEVELS: &[&str] = &["3.0", "3.1", "4.0", "4.1", "4.2", "5.0", "5.1", "5.2"];

#[derive(Deserialize)]
pub struct ConvertArgs {
    pub input: String,
    pub output: String,
    /// 输出容器（-f），留空按扩展名推断
    #[serde(default)]
    pub format: Option<String>,
    /// 指定输入流，如 "0:2"；留空交给 ffmpeg 自动选
    #[serde(default)]
    pub video_stream: Option<String>,
    #[serde(default)]
    pub audio_stream: Option<String>,
    /// 用这个文件里的音频替换原音轨；留空表示保留原音轨
    #[serde(default)]
    pub replace_audio: Option<String>,
    #[serde(default)]
    pub no_video: bool,
    #[serde(default)]
    pub no_audio: bool,
    /// "copy" 复制字幕流 / "none" 去掉字幕
    #[serde(default)]
    pub subtitles: Option<String>,
    #[serde(default)]
    pub start: Option<f64>,
    #[serde(default)]
    pub duration: Option<f64>,
    #[serde(default)]
    pub video_codec: Option<String>,
    #[serde(default)]
    pub preset: Option<String>,
    #[serde(default)]
    pub tune: Option<String>,
    #[serde(default)]
    pub profile: Option<String>,
    #[serde(default)]
    pub level: Option<String>,
    #[serde(default)]
    pub pix_fmt: Option<String>,
    #[serde(default)]
    pub crf: Option<u32>,
    #[serde(default)]
    pub video_bitrate: Option<String>,
    #[serde(default)]
    pub maxrate: Option<String>,
    #[serde(default)]
    pub bufsize: Option<String>,
    #[serde(default)]
    pub fps: Option<String>,
    #[serde(default)]
    pub width: Option<u32>,
    #[serde(default)]
    pub height: Option<u32>,
    #[serde(default)]
    pub video_filters: Option<String>,
    #[serde(default)]
    pub audio_codec: Option<String>,
    #[serde(default)]
    pub audio_bitrate: Option<String>,
    #[serde(default)]
    pub sample_rate: Option<u32>,
    #[serde(default)]
    pub channels: Option<u32>,
    #[serde(default)]
    pub audio_filters: Option<String>,
    #[serde(default)]
    pub faststart: bool,
    #[serde(default)]
    pub two_pass: bool,
    #[serde(default = "default_true")]
    pub overwrite: bool,
    #[serde(default)]
    pub metadata: Option<Value>,
    #[serde(default)]
    pub extra_args: Option<Vec<String>>,
}

fn default_true() -> bool {
    true
}

/// 去掉首尾空白后仍非空才算有效值。
fn arg_text(value: &Option<String>) -> Option<&str> {
    value.as_deref().map(str::trim).filter(|text| !text.is_empty())
}

fn video_encoder(codec: &str) -> &str {
    match codec {
        "h264" => "libx264",
        "hevc" => "libx265",
        "vp9" => "libvpx-vp9",
        "av1" => "libsvtav1",
        other => other,
    }
}

fn audio_encoder(codec: &str) -> &str {
    match codec {
        "mp3" => "libmp3lame",
        other => other,
    }
}

fn probe_duration(path: &Path) -> f64 {
    let output = Command::new(crate::tools::ffprobe())
        .args(["-v", "quiet", "-print_format", "json", "-show_format"])
        .arg(path)
        .output();
    let Ok(output) = output else { return 0.0 };
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(&output.stdout) else {
        return 0.0;
    };
    value
        .get("format")
        .and_then(|f| f.get("duration"))
        .and_then(|d| d.as_str())
        .and_then(|d| d.parse::<f64>().ok())
        .unwrap_or(0.0)
}

/// 视频实际会输出多长：先扣掉裁剪起点，再受裁剪时长限制；探测失败返回 0。
fn effective_video_len(input: &Path, start: Option<f64>, duration: Option<f64>) -> f64 {
    let total = probe_duration(input);
    if total <= 0.0 {
        return 0.0;
    }
    let remain = (total - start.unwrap_or(0.0).max(0.0)).max(0.0);
    duration.map(|d| d.min(remain)).unwrap_or(remain)
}

#[tauri::command]
pub fn cancel_convert() {
    CANCEL.store(true, Ordering::SeqCst);
}

/// 在目标目录里找一个不冲突的输出文件名：重名自动加 -1、-2 后缀。
/// ffmpeg 本身没有"输出目录"的概念，落点必须是一个确定路径，所以由这里拼名字。
#[tauri::command]
pub fn unique_output_path(dir: String, filename: String) -> Result<String, String> {
    let folder = PathBuf::from(&dir);
    if !folder.is_dir() {
        return Err(format!("输出目录不存在: {dir}"));
    }
    let safe = sanitize_file_name(&filename);
    let path = Path::new(&safe);
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("output")
        .to_string();
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_string();
    let mut candidate = folder.join(&safe);
    let mut index = 1;
    while candidate.exists() {
        let name = if ext.is_empty() {
            format!("{stem}-{index}")
        } else {
            format!("{stem}-{index}.{ext}")
        };
        candidate = folder.join(name);
        index += 1;
    }
    Ok(candidate.to_string_lossy().to_string())
}

fn sanitize_file_name(name: &str) -> String {
    let cleaned: String = name
        .chars()
        .map(|c| if "/\\:*?\"<>|".contains(c) { '_' } else { c })
        .collect();
    let trimmed = cleaned.trim().trim_matches('.').to_string();
    if trimmed.is_empty() {
        "output".to_string()
    } else {
        trimmed
    }
}

#[tauri::command]
pub async fn convert_media(app: tauri::AppHandle, args: ConvertArgs) -> Result<(), String> {
    CANCEL.store(false, Ordering::SeqCst);
    let _running = RunningGuard::enter();
    tauri::async_runtime::spawn_blocking(move || run_convert(&app, args))
        .await
        .map_err(|e| format!("任务执行失败：{e}"))?
}

fn run_convert(app: &tauri::AppHandle, args: ConvertArgs) -> Result<(), String> {
    let result = convert_with(
        &args,
        &mut |percent| {
            let _ = app.emit(
                "convert-progress",
                serde_json::json!({ "percent": percent }),
            );
        },
        &|| CANCEL.load(Ordering::SeqCst),
    );
    if result.is_ok() {
        let _ = app.emit(
            "convert-progress",
            serde_json::json!({ "percent": 100.0, "done": true }),
        );
    }
    result
}

/// 转码主流程：不依赖 Tauri，进度与取消都由调用方提供。
pub fn convert_with(
    args: &ConvertArgs,
    on_progress: &mut dyn FnMut(f64),
    cancelled: &dyn Fn() -> bool,
) -> Result<(), String> {
    let input = PathBuf::from(&args.input);
    if !input.is_file() {
        return Err("输入文件不存在".into());
    }
    if args.output.trim().is_empty() {
        return Err("未指定输出文件".into());
    }
    if let Some(audio) = arg_text(&args.replace_audio) {
        if !Path::new(audio).is_file() {
            return Err("用来替换音轨的音频文件不存在".into());
        }
    }
    let total = args.duration.unwrap_or_else(|| probe_duration(&input));
    let passlog = std::env::temp_dir().join(format!("whisper-studio-pass-{}", std::process::id()));

    let two_pass = args.two_pass
        && !args.no_video
        && arg_text(&args.video_bitrate).is_some()
        && arg_text(&args.video_codec)
            .map(|codec| codec != "copy")
            .unwrap_or(false);

    if !two_pass {
        return run_pass(args, 0, total, &passlog, on_progress, cancelled);
    }

    // 两遍编码：第一遍只分析，第二遍才写文件；进度各占一半。
    run_pass(args, 1, total, &passlog, &mut |p| on_progress(p * 0.5), cancelled)?;
    let result = run_pass(args, 2, total, &passlog, &mut |p| on_progress(50.0 + p * 0.5), cancelled);
    cleanup_passlog(&passlog);
    result
}

fn cleanup_passlog(prefix: &Path) {
    let Some(dir) = prefix.parent() else { return };
    let Some(name) = prefix.file_name().and_then(|n| n.to_str()) else { return };
    if let Ok(entries) = std::fs::read_dir(dir) {
        for entry in entries.flatten() {
            let file = entry.file_name();
            if file.to_string_lossy().starts_with(name) {
                let _ = std::fs::remove_file(entry.path());
            }
        }
    }
}

fn scale_filter(args: &ConvertArgs) -> Option<String> {
    let width = args.width.filter(|w| *w > 0);
    let height = args.height.filter(|h| *h > 0);
    match (width, height) {
        (Some(w), Some(h)) => Some(format!("scale={w}:{h}")),
        // 只给一边时另一边按比例自动，避免拉变形。
        (Some(w), None) => Some(format!("scale={w}:-2")),
        (None, Some(h)) => Some(format!("scale=-2:{h}")),
        (None, None) => None,
    }
}

fn wants_faststart(args: &ConvertArgs) -> bool {
    if !args.faststart {
        return false;
    }
    if let Some(format) = arg_text(&args.format) {
        return matches!(format, "mp4" | "mov" | "ipod" | "m4a");
    }
    let ext = Path::new(&args.output)
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    matches!(ext.as_str(), "mp4" | "m4v" | "mov" | "m4a")
}

#[allow(clippy::too_many_lines)]
fn run_pass(
    args: &ConvertArgs,
    pass: u8,
    total: f64,
    passlog: &Path,
    on_progress: &mut dyn FnMut(f64),
    cancelled: &dyn Fn() -> bool,
) -> Result<(), String> {
    let input = PathBuf::from(&args.input);
    let mut cmd = Command::new(crate::tools::ffmpeg());
    cmd.arg("-v").arg("error");
    cmd.arg(if args.overwrite { "-y" } else { "-n" });
    if let Some(start) = args.start {
        cmd.arg("-ss").arg(format!("{start}"));
    }
    cmd.arg("-i").arg(&input);
    if let Some(duration) = args.duration {
        cmd.arg("-t").arg(format!("{duration}"));
    }

    // 替换音轨：第二个输入只取它的音频，视频仍来自原文件。
    let replace_audio = arg_text(&args.replace_audio);
    if let Some(path) = replace_audio {
        cmd.arg("-i").arg(path);
        // 以视频为主：音频更长就按视频收尾；音频更短则保持视频完整，音频自然结束。
        if pass != 1 {
            let video_len = effective_video_len(&input, args.start, args.duration);
            let audio_len = probe_duration(Path::new(path));
            if audio_len > 0.0 && (video_len <= 0.0 || audio_len > video_len + 0.05) {
                cmd.arg("-shortest");
            }
        }
    }

    // 流选择：显式指定就用 -map，否则交给 ffmpeg 自动挑。
    if let Some(stream) = arg_text(&args.video_stream) {
        cmd.arg("-map").arg(stream);
    } else if replace_audio.is_some() && !args.no_video {
        cmd.arg("-map").arg("0:v:0");
    }
    if replace_audio.is_some() {
        // 第一遍只分析、以及选「去掉音轨」时都不能 map 音频。
        if !args.no_audio && pass != 1 && arg_text(&args.audio_codec) != Some("none") {
            cmd.arg("-map").arg("1:a:0");
        }
    } else if let Some(stream) = arg_text(&args.audio_stream) {
        cmd.arg("-map").arg(stream);
    }

    /* ---- 视频 ---- */
    let video_codec = arg_text(&args.video_codec).unwrap_or("");
    let video_reencode = !video_codec.is_empty() && video_codec != "copy";
    if args.no_video {
        cmd.arg("-vn");
    } else if !video_codec.is_empty() {
        cmd.arg("-c:v").arg(video_encoder(video_codec));
    }

    if !args.no_video && video_reencode {
        if let Some(preset) = arg_text(&args.preset) {
            cmd.arg("-preset").arg(preset);
        }
        if let Some(tune) = arg_text(&args.tune) {
            cmd.arg("-tune").arg(tune);
        }
        if let Some(profile) = arg_text(&args.profile) {
            cmd.arg("-profile:v").arg(profile);
        }
        if let Some(level) = arg_text(&args.level) {
            cmd.arg("-level").arg(level);
        }
        if let Some(pix_fmt) = arg_text(&args.pix_fmt) {
            cmd.arg("-pix_fmt").arg(pix_fmt);
        }
        // 两遍编码靠码率控体积，这时 CRF 会互相打架。
        if pass == 0 && !args.two_pass {
            if let Some(crf) = args.crf {
                cmd.arg("-crf").arg(crf.to_string());
            }
        }
        if let Some(bitrate) = arg_text(&args.video_bitrate) {
            cmd.arg("-b:v").arg(bitrate);
        }
        if let Some(maxrate) = arg_text(&args.maxrate) {
            cmd.arg("-maxrate").arg(maxrate);
        }
        if let Some(bufsize) = arg_text(&args.bufsize) {
            cmd.arg("-bufsize").arg(bufsize);
        }
        if let Some(fps) = arg_text(&args.fps) {
            cmd.arg("-r").arg(fps);
        }
        if pass > 0 {
            cmd.arg("-pass").arg(pass.to_string());
            cmd.arg("-passlogfile").arg(passlog);
        }
    }

    // 滤镜链：先缩放，再拼用户自己写的滤镜。
    let mut filters: Vec<String> = Vec::new();
    if let Some(scale) = scale_filter(args) {
        filters.push(scale);
    }
    if let Some(extra) = arg_text(&args.video_filters) {
        filters.push(extra.to_string());
    }
    if !args.no_video && video_codec != "copy" && !filters.is_empty() {
        cmd.arg("-vf").arg(filters.join(","));
    }

    /* ---- 音频 ---- */
    let mut audio_codec = arg_text(&args.audio_codec).unwrap_or("");
    if replace_audio.is_some() && (audio_codec.is_empty() || audio_codec == "copy") {
        // 外部音频的容器编码不确定，直接 copy 进 mp4/mov 很容易失败，统一转 AAC。
        audio_codec = "aac";
    }
    let audio_dropped = args.no_audio || audio_codec == "none" || pass == 1;
    if audio_dropped {
        cmd.arg("-an");
    } else if !audio_codec.is_empty() {
        cmd.arg("-c:a").arg(audio_encoder(audio_codec));
        if audio_codec != "copy" {
            if let Some(bitrate) = arg_text(&args.audio_bitrate) {
                cmd.arg("-b:a").arg(bitrate);
            }
            if let Some(rate) = args.sample_rate.filter(|r| *r > 0) {
                cmd.arg("-ar").arg(rate.to_string());
            }
            if let Some(channels) = args.channels.filter(|c| *c > 0) {
                cmd.arg("-ac").arg(channels.to_string());
            }
        }
    }
    if !audio_dropped && audio_codec != "copy" {
        if let Some(extra) = arg_text(&args.audio_filters) {
            cmd.arg("-af").arg(extra);
        }
    }

    /* ---- 字幕 / 容器 / 元数据 ---- */
    match arg_text(&args.subtitles) {
        Some("copy") => {
            cmd.arg("-map").arg("0:s?");
            cmd.arg("-c:s").arg("copy");
        }
        Some("none") => {
            cmd.arg("-sn");
        }
        _ => {}
    }

    if pass == 0 {
        if let Some(format) = arg_text(&args.format) {
            cmd.arg("-f").arg(format);
        }
        if wants_faststart(args) {
            cmd.arg("-movflags").arg("+faststart");
        }
        if let Some(Value::Object(map)) = &args.metadata {
            for (key, value) in map {
                if let Some(text) = value.as_str() {
                    cmd.arg("-metadata").arg(format!("{key}={text}"));
                }
            }
        }
    }

    if let Some(extra) = &args.extra_args {
        for piece in extra.iter().map(|v| v.trim()).filter(|v| !v.is_empty()) {
            cmd.arg(piece);
        }
    }

    cmd.arg("-progress").arg("pipe:1").arg("-nostats");
    if pass == 1 {
        // 第一遍不写成品，只产出分析数据。
        cmd.arg("-f").arg("null");
        cmd.arg(if cfg!(windows) { "NUL" } else { "/dev/null" });
    } else {
        cmd.arg(&args.output);
    }
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("启动 ffmpeg 失败（请确认已安装 FFmpeg）：{e}"))?;

    // stderr 单独线程读，避免管道写满把进程卡死；出错时还能拿到可读原因。
    let stderr = child.stderr.take();
    let stderr_reader = std::thread::spawn(move || {
        let mut text = String::new();
        if let Some(mut pipe) = stderr {
            let _ = pipe.read_to_string(&mut text);
        }
        text
    });

    if let Some(stdout) = child.stdout.take() {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            if cancelled() {
                let _ = child.kill();
                let _ = child.wait();
                let _ = stderr_reader.join();
                return Err("已取消".into());
            }
            if let Some(value) = line.strip_prefix("out_time_us=") {
                if let Ok(micros) = value.trim().parse::<f64>() {
                    let percent = if total > 0.0 {
                        (micros / 1_000_000.0 / total * 100.0).clamp(0.0, 100.0)
                    } else {
                        0.0
                    };
                    on_progress(percent);
                }
            }
        }
    }

    let status = child.wait().map_err(|e| e.to_string())?;
    let stderr_text = stderr_reader.join().unwrap_or_default();
    if cancelled() {
        return Err("已取消".into());
    }
    if !status.success() {
        let detail = stderr_text.trim();
        return Err(if detail.is_empty() {
            "转码失败，请检查参数或源文件".to_string()
        } else {
            format!("转码失败：{}", detail.lines().last().unwrap_or(detail))
        });
    }
    if pass != 1 {
        on_progress(100.0);
    }
    Ok(())
}

/* ---------------- 能力自动发现 ---------------- */

fn run_capture(exe: &std::path::Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new(exe)
        .args(args)
        .output()
        .map_err(|e| format!("无法执行 {}：{e}", exe.display()))?;
    if !output.status.success() {
        return Err(format!(
            "{} 执行失败：{}",
            exe.display(),
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

fn is_separator(line: &str) -> bool {
    let trimmed = line.trim();
    trimmed.len() >= 2 && trimmed.chars().all(|c| c == '-' || c == '.')
}

fn parse_encoders(text: &str) -> Vec<Value> {
    let mut out = Vec::new();
    let mut started = false;
    for line in text.lines() {
        if !started {
            started = is_separator(line);
            continue;
        }
        let trimmed = line.trim_start();
        if trimmed.is_empty() {
            continue;
        }
        let flags: String = trimmed.chars().take(6).collect();
        let rest = trimmed.chars().skip(6).collect::<String>();
        let mut parts = rest.trim().splitn(2, char::is_whitespace);
        let name = parts.next().unwrap_or("").trim().to_string();
        if name.is_empty() {
            continue;
        }
        let description = parts.next().unwrap_or("").trim().to_string();
        let kind = if flags.contains('V') {
            "video"
        } else if flags.contains('A') {
            "audio"
        } else if flags.contains('S') {
            "subtitle"
        } else {
            "other"
        };
        out.push(json!({
            "name": name,
            "kind": kind,
            "description": description,
            "experimental": flags.contains('X'),
            "lossy": flags.contains('L'),
        }));
    }
    out
}

fn parse_formats(text: &str) -> Vec<Value> {
    let mut out = Vec::new();
    let mut started = false;
    for line in text.lines() {
        if !started {
            started = is_separator(line);
            continue;
        }
        let mut tokens = line.split_whitespace();
        // 标志位是独立的短 token（D=demux、E=mux、d=设备），可能合并成 "DE"、也可能分开。
        let mut demux = false;
        let mut mux = false;
        let mut device = false;
        let mut name = "";
        for token in tokens.by_ref() {
            let is_flag = token.len() <= 3
                && token.chars().all(|c| matches!(c, 'D' | 'E' | 'd'));
            if !is_flag {
                name = token;
                break;
            }
            demux |= token.contains('D');
            mux |= token.contains('E');
            device |= token.contains('d');
        }
        if name.is_empty() {
            continue;
        }
        let names: Vec<&str> = name.split(',').filter(|part| !part.is_empty()).collect();
        if names.is_empty() {
            continue;
        }
        out.push(json!({
            "names": names,
            "demux": demux,
            "mux": mux,
            "device": device,
            "description": tokens.collect::<Vec<&str>>().join(" "),
        }));
    }
    out
}

fn parse_filters(text: &str) -> Vec<Value> {
    // `-filters` 没有分隔线，表头是 "T.. = Timeline support" 这类说明，
    // 正文每行形如 " TSC aap  AA->A  描述"，所以按 "->" 那一列定位。
    let mut out = Vec::new();
    for line in text.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        let Some(io_pos) = parts.iter().position(|part| part.contains("->")) else {
            continue;
        };
        if io_pos == 0 {
            continue;
        }
        let name = parts[io_pos - 1];
        if name == "=" {
            continue;
        }
        out.push(json!({
            "name": name,
            "io": parts[io_pos],
            "description": parts[io_pos + 1..].join(" "),
        }));
    }
    out
}

fn parse_pixel_formats(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut started = false;
    for line in text.lines() {
        if !started {
            started = is_separator(line);
            continue;
        }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 2 {
            continue;
        }
        out.push(parts[1].to_string());
    }
    out
}

fn parse_hwaccels(text: &str) -> Vec<String> {
    text.lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.ends_with(':'))
        .map(str::to_string)
        .collect()
}

/// 盘点内置 ffmpeg 的真实能力：编码器、容器、滤镜、像素格式、硬件加速。
pub fn capabilities() -> Value {
    let exe = crate::tools::ffmpeg();
    let version = match run_capture(&exe, &["-version"]) {
        Ok(text) => text.lines().next().unwrap_or("").to_string(),
        Err(err) => return json!({ "error": err }),
    };
    let encoders = run_capture(&exe, &["-hide_banner", "-encoders"])
        .map(|text| parse_encoders(&text))
        .unwrap_or_default();
    let formats = run_capture(&exe, &["-hide_banner", "-formats"])
        .map(|text| parse_formats(&text))
        .unwrap_or_default();
    let filters = run_capture(&exe, &["-hide_banner", "-filters"])
        .map(|text| parse_filters(&text))
        .unwrap_or_default();
    let pixel_formats = run_capture(&exe, &["-hide_banner", "-pix_fmts"])
        .map(|text| parse_pixel_formats(&text))
        .unwrap_or_default();
    let hwaccels = run_capture(&exe, &["-hide_banner", "-hwaccels"])
        .map(|text| parse_hwaccels(&text))
        .unwrap_or_default();

    json!({
        "version": version,
        "encoders": encoders,
        "formats": formats,
        "filters": filters,
        "pixel_formats": pixel_formats,
        "hwaccels": hwaccels,
        "presets": VIDEO_PRESETS,
        "tunes": TUNES,
        "profiles": PROFILES,
        "levels": LEVELS,
    })
}

/// 场景预设：一组常用参数组合，前端一键套用，MCP 也能取到同一份定义。
pub fn presets() -> Value {
    json!([
        {
            "id": "audio_mp3",
            "name": "提取音频 · MP3 192k",
            "args": { "no_video": true, "audio_codec": "libmp3lame", "audio_bitrate": "192k" }
        },
        {
            "id": "audio_aac",
            "name": "提取音频 · AAC 256k",
            "args": { "no_video": true, "audio_codec": "aac", "audio_bitrate": "256k" }
        },
        {
            "id": "whisper_wav",
            "name": "转 16k 单声道 WAV（喂 whisper）",
            "args": {
                "no_video": true,
                "audio_codec": "pcm_s16le",
                "sample_rate": 16000,
                "channels": 1
            }
        },
        {
            "id": "social_720p",
            "name": "社交分享 · H.264 720p 压缩",
            "args": {
                "video_codec": "libx264",
                "crf": 28,
                "preset": "veryfast",
                "height": 720,
                "pix_fmt": "yuv420p",
                "audio_codec": "aac",
                "audio_bitrate": "128k",
                "faststart": true
            }
        },
        {
            "id": "h265_small",
            "name": "高压缩 · H.265 CRF 30",
            "args": {
                "video_codec": "libx265",
                "crf": 30,
                "preset": "slow",
                "pix_fmt": "yuv420p",
                "audio_codec": "aac",
                "audio_bitrate": "128k",
                "faststart": true
            }
        },
        {
            "id": "remux_faststart",
            "name": "仅重封装 · 网页秒开",
            "args": { "video_codec": "copy", "audio_codec": "copy", "faststart": true }
        },
        {
            "id": "gif",
            "name": "视频转 GIF · 480 宽 12fps",
            "args": {
                "video_codec": "gif",
                "video_filters": "fps=12,scale=480:-1:flags=lanczos",
                "audio_codec": "none"
            }
        },
        {
            "id": "loudnorm",
            "name": "响度归一化 · -16 LUFS",
            "args": { "audio_filters": "loudnorm=I=-16:TP=-1.5:LRA=11" }
        }
    ])
}
