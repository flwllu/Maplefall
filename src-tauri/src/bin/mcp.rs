//! 枫落工具的 MCP 服务器：走 stdio，JSON-RPC 2.0，无第三方依赖。
//! 对外暴露桌面端的全部能力：转写、人声分离、模型列表、设置读写、
//! 媒体信息读取、标签/封面读写、重命名、批量重命名、格式转换、字幕导出。

// 工具表用 json! 手写，条目多，默认递归上限不够。
#![recursion_limit = "256"]

use std::fs;
use std::io::{BufRead, Write};
use std::path::PathBuf;

use serde_json::{json, Value};

// MCP 只用到这些模块的核心逻辑，Tauri 命令入口在这里用不上。
#[allow(dead_code)]
#[path = "../convert.rs"]
mod convert;
#[path = "../engine.rs"]
mod engine;
#[allow(dead_code)]
#[path = "../job.rs"]
mod job;
#[path = "../mdx.rs"]
mod mdx;
#[allow(dead_code)]
#[path = "../media.rs"]
mod media;
#[path = "../tools.rs"]
mod tools;

/// 配置目录，与主程序的 `app_config_dir()` 一致（settings.json 所在位置）。
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

/// 数据目录，与主程序的 `app_data_dir()` 一致（用户自放模型的位置）。
fn settings_path() -> PathBuf {
    config_dir().join("settings.json")
}

fn is_transcribe_model(name: &str) -> bool {
    name.ends_with(".bin") && !name.to_ascii_lowercase().contains("silero")
}

fn tool_text(value: Value) -> Value {
    json!({
        "content": [{ "type": "text", "text": value.to_string() }],
        "isError": false
    })
}

fn tool_fail(message: String) -> Value {
    json!({
        "content": [{ "type": "text", "text": message }],
        "isError": true
    })
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

/* ---------------- 转写 ---------------- */

fn list_models() -> Result<Value, String> {
    let mut names = std::collections::BTreeSet::new();
    for dir in job::model_search_dirs() {
        let Ok(entries) = fs::read_dir(dir) else {
            continue;
        };
        for name in entries.flatten().filter_map(|e| e.file_name().into_string().ok()) {
            if is_transcribe_model(&name) {
                names.insert(name);
            }
        }
    }
    Ok(json!({
        "models": names.into_iter().collect::<Vec<String>>(),
        "user_dir": job::user_models_dir().display().to_string()
    }))
}

/* ---------------- 字幕导出 ---------------- */

fn srt_to_lrc(srt: &str) -> String {
    srt.trim()
        .split("\n\n")
        .filter_map(|block| {
            let lines: Vec<&str> = block
                .lines()
                .map(str::trim)
                .filter(|line| !line.is_empty())
                .collect();
            let time = lines.iter().find(|line| line.contains("-->"))?;
            let start = time.split("-->").next()?.trim();
            let mut parts = start.split(':');
            let hours = parts.next()?;
            let minutes = parts.next()?;
            let rest = parts.next()?;
            let seconds = rest.replace(',', ".");
            let stamp = if hours == "00" {
                format!("{minutes}:{seconds}")
            } else {
                format!("{hours}:{minutes}:{seconds}")
            };
            let content = lines
                .iter()
                .filter(|line| !line.contains("-->") && !line.chars().all(|c| c.is_ascii_digit()))
                .copied()
                .collect::<Vec<&str>>()
                .join(" ");
            let content = content.trim();
            if content.is_empty() {
                None
            } else {
                Some(format!("[{stamp}]{content}"))
            }
        })
        .collect::<Vec<String>>()
        .join("\n")
}

fn base_name(path: &str) -> String {
    path.rsplit(|c| c == '/' || c == '\\')
        .next()
        .unwrap_or(path)
        .to_string()
}

/* ---------------- 工具定义 ---------------- */

fn tool_defs() -> Value {
    json!([
        {
            "name": "transcribe_audio",
            "description": "把音频/视频转成文字和 SRT 字幕。默认先做 MDX 人声分离以提升歌词识别率；说唱或人声很轻的内容建议关闭 vad。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input_path": { "type": "string", "description": "音频或视频文件绝对路径" },
                    "model": { "type": "string", "description": "模型文件名（取自 list_models），默认 ggml-large-v3-turbo-q5_0.bin；用户模型目录优先于随包目录" },
                    "language": { "type": "string", "description": "语言代码，如 zh、en、auto，默认 auto" },
                    "separate": { "type": "boolean", "description": "是否先分离人声，默认 true" },
                    "vad": { "type": "boolean", "description": "是否跳过无语音片段（使用 silero VAD），默认 false" },
                    "suppress_ns": { "type": "boolean", "description": "是否抑制非语音 token，默认 true" },
                    "acceleration": { "type": "boolean", "description": "是否允许加载模型旁的 CoreML 编码器，默认 true；没有编码器时自动走 Metal + CPU" },
                    "no_context": { "type": "boolean", "description": "是否不沿用上文（无提示词时生效），默认 true" },
                    "prompt": { "type": "string", "description": "可选的初始提示，例如已知的歌名或歌词片段" },
                    "no_fallback": { "type": "boolean", "description": "关闭温度回退，不乱编但可能留空，默认 false" },
                    "beam_size": { "type": "integer", "description": "beam size（-bs）" },
                    "best_of": { "type": "integer", "description": "best of（-bo）" },
                    "no_speech_thold": { "type": "number", "description": "无语音阈值（-nth）" },
                    "entropy_thold": { "type": "number", "description": "熵阈值（-et），默认 2.8" },
                    "logprob_thold": { "type": "number", "description": "对数概率阈值（-lpt）" },
                    "word_thold": { "type": "number", "description": "词置信阈值（-wt）" },
                    "max_len": { "type": "integer", "description": "单段最大字数（-ml）" }
                },
                "required": ["input_path"]
            }
        },
        {
            "name": "separate_vocals",
            "description": "用 UVR 的 MDX 模型把音频分离成人声轨，返回分离后 WAV 的路径。结果有缓存，重复调用同一文件不会重算。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input_path": { "type": "string", "description": "音频或视频文件绝对路径" }
                },
                "required": ["input_path"]
            }
        },
        {
            "name": "export_transcript",
            "description": "把转写结果写成本地文件，支持 txt / srt / lrc 三种格式（对应桌面端结果区三个导出按钮）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "output_path": { "type": "string", "description": "输出文件的绝对路径" },
                    "format": { "type": "string", "enum": ["txt", "srt", "lrc"], "description": "导出格式，默认 txt" },
                    "text": { "type": "string", "description": "纯文本内容，format=txt 时使用" },
                    "srt": { "type": "string", "description": "SRT 内容，format=srt 或 lrc 时使用" }
                },
                "required": ["output_path"]
            }
        },
        {
            "name": "list_models",
            "description": "列出可用的 whisper 模型文件名：合并用户模型目录与随包资源目录并去重（同名时用户目录优先），同时返回用户模型目录路径 user_dir。",
            "inputSchema": { "type": "object", "properties": {} }
        },
        {
            "name": "get_settings",
            "description": "读取应用保存的界面设置（settings.json 内容）。",
            "inputSchema": { "type": "object", "properties": {} }
        },
        {
            "name": "save_settings",
            "description": "覆盖写入应用的设置 JSON。传入完整对象，写入是原子的。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "data": { "type": "object", "description": "完整设置对象，例如 {\"remember\":true,\"ui\":{...}}" }
                },
                "required": ["data"]
            }
        },
        {
            "name": "media_info",
            "description": "读取音视频文件的媒体信息与标签：格式、时长、大小、码率、编码、采样率、声道、是否有封面，以及 title/artist/album 等标签。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "媒体文件绝对路径" }
                },
                "required": ["path"]
            }
        },
        {
            "name": "media_write_tags",
            "description": "写入音频标签（无损重封装），支持 title/artist/album/albumartist/genre/date/tracknumber/composer。只写传入的字段。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "音频文件绝对路径" },
                    "tags": { "type": "object", "description": "标签对象，例如 {\"title\":\"歌名\",\"artist\":\"歌手\"}" }
                },
                "required": ["path", "tags"]
            }
        },
        {
            "name": "media_read_cover",
            "description": "读取音频内嵌封面。默认只返回是否存在及字节数，include_data 为 true 时才返回可直接预览的 data URL。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "音频文件绝对路径" },
                    "include_data": { "type": "boolean", "description": "是否返回 data URL，默认 false" }
                },
                "required": ["path"]
            }
        },
        {
            "name": "media_set_cover",
            "description": "把一张图片写入/替换为音频的内嵌封面。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "音频文件绝对路径" },
                    "image": { "type": "string", "description": "封面图片绝对路径（jpg/png/bmp/webp）" }
                },
                "required": ["path", "image"]
            }
        },
        {
            "name": "media_remove_cover",
            "description": "删除音频的内嵌封面，保留全部音频流。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "音频文件绝对路径" }
                },
                "required": ["path"]
            }
        },
        {
            "name": "media_rename",
            "description": "重命名单个媒体文件（同目录内，扩展名保持不变），返回新路径。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "媒体文件绝对路径" },
                    "filename": { "type": "string", "description": "新文件名，不含扩展名" }
                },
                "required": ["path", "filename"]
            }
        },
        {
            "name": "media_scan_folder",
            "description": "扫描文件夹（不递归）里的音频文件，返回路径、文件名与各自的媒体信息。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "dir": { "type": "string", "description": "文件夹绝对路径" }
                },
                "required": ["dir"]
            }
        },
        {
            "name": "batch_rename_folder",
            "description": "按标签批量重命名文件夹里的音频。默认只预览（apply=false），确认无误后传 apply=true 真正执行。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "dir": { "type": "string", "description": "文件夹绝对路径" },
                    "pattern": {
                        "type": "string",
                        "enum": ["artist_title", "title_artist", "title_only", "artist_only"],
                        "description": "命名模板，默认 artist_title"
                    },
                    "apply": { "type": "boolean", "description": "是否真的执行重命名，默认 false 仅预览" }
                },
                "required": ["dir"]
            }
        },
        {
            "name": "convert_media",
            "description": "用 ffmpeg 转换音视频：编码器/质量/帧率/分辨率/采样率/声道/裁剪/流选择/字幕/元数据/两遍编码均可指定，未覆盖的参数走 extra_args 原样透传。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": { "type": "string", "description": "源文件绝对路径" },
                    "output": { "type": "string", "description": "输出文件绝对路径" },
                    "format": { "type": "string", "description": "输出容器（-f），如 mp4、matroska，留空按扩展名推断" },
                    "video_stream": { "type": "string", "description": "指定视频流，如 0:0（-map）；留空自动" },
                    "audio_stream": { "type": "string", "description": "指定音频流，如 0:1（-map）；留空自动" },
                    "subtitles": { "type": "string", "enum": ["copy", "none"], "description": "copy=复制字幕流，none=去掉字幕" },
                    "no_video": { "type": "boolean", "description": "只保留音频，去掉视频轨" },
                    "no_audio": { "type": "boolean", "description": "去掉音轨" },
                    "start": { "type": "number", "description": "裁剪起点（秒）" },
                    "duration": { "type": "number", "description": "裁剪时长（秒）" },
                    "video_codec": { "type": "string", "description": "空=保持原样，或 copy / h264 / hevc / vp9 / 任意 ffmpeg 编码器名" },
                    "preset": { "type": "string", "description": "编码速度档：ultrafast..placebo（x264/x265）" },
                    "tune": { "type": "string", "description": "如 film、animation、grain、zerolatency" },
                    "profile": { "type": "string", "description": "如 baseline、main、high、high10" },
                    "level": { "type": "string", "description": "如 4.1、5.1" },
                    "pix_fmt": { "type": "string", "description": "如 yuv420p、yuv420p10le、nv12" },
                    "crf": { "type": "integer", "description": "视频质量 0-51，越小越好（两遍编码时忽略）" },
                    "video_bitrate": { "type": "string", "description": "视频码率，如 2M" },
                    "maxrate": { "type": "string", "description": "最大码率，如 4M" },
                    "bufsize": { "type": "string", "description": "码率缓冲，如 8M" },
                    "fps": { "type": "string", "description": "帧率，如 30 或 30000/1001" },
                    "width": { "type": "integer", "description": "宽度，只给一边时另一边按比例自动" },
                    "height": { "type": "integer", "description": "高度，只给一边时另一边按比例自动" },
                    "video_filters": { "type": "string", "description": "视频滤镜链（-vf），接在缩放之后，如 crop=iw:ih-20:0:0,hqdn3d" },
                    "audio_codec": { "type": "string", "description": "空=保持原样，或 copy / aac / libmp3lame / pcm_s16le / none（去掉音轨）" },
                    "audio_bitrate": { "type": "string", "description": "音频码率，如 192k" },
                    "sample_rate": { "type": "integer", "description": "采样率，如 16000" },
                    "channels": { "type": "integer", "description": "声道数，如 1、2" },
                    "audio_filters": { "type": "string", "description": "音频滤镜链（-af），如 loudnorm=I=-16:TP=-1.5:LRA=11" },
                    "faststart": { "type": "boolean", "description": "mp4/mov 加 +faststart，网页和微信里秒开" },
                    "two_pass": { "type": "boolean", "description": "两遍编码，需要 video_bitrate" },
                    "overwrite": { "type": "boolean", "description": "覆盖已存在的输出文件，默认 true" },
                    "metadata": { "type": "object", "description": "写入输出的元数据，如 {\"title\":\"歌名\"}" },
                    "extra_args": {
                        "type": "array",
                        "items": { "type": "string" },
                        "description": "额外参数原样追加到 ffmpeg 命令行，如 [\"-movflags\",\"+faststart\"]"
                    }
                },
                "required": ["input", "output"]
            }
        },
        {
            "name": "list_convert_presets",
            "description": "列出格式转换的场景预设（提取音频、社交压缩、转 whisper 用 wav、GIF、响度归一化等）及其参数组合，可直接喂给 convert_media。",
            "inputSchema": { "type": "object", "properties": {} }
        },
        {
            "name": "ffmpeg_capabilities",
            "description": "盘点本机 ffmpeg 真实能力。不传 kind 只返回摘要（各类数量 / 硬件加速 / 预设档位）；传 kind 返回具体清单，可用 filter 做关键字筛选。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["encoders", "formats", "filters", "pixel_formats", "hwaccels", "all"],
                        "description": "要返回哪一类；留空=只返回摘要"
                    },
                    "filter": { "type": "string", "description": "按名称/描述做关键字筛选，如 h264、mp4、audio" }
                }
            }
        }
    ])
}

/* ---------------- 工具分发 ---------------- */

fn call_tool(params: &Value) -> Result<Value, String> {
    let name = params
        .get("name")
        .and_then(Value::as_str)
        .ok_or("缺少工具名".to_string())?;
    let args = params
        .get("arguments")
        .cloned()
        .unwrap_or_else(|| json!({}));

    let result = match name {
        "transcribe_audio" => {
            let input = PathBuf::from(req_str(&args, "input_path")?);
            let opts = job::TranscribeOpts::from_value(&args)?;
            job::transcribe(&input, &opts).map(tool_text)
        }
        "separate_vocals" => {
            let input = PathBuf::from(req_str(&args, "input_path")?);
            job::separate(&input, &mut |_| {}, &|_| {})
                .map(|path| tool_text(json!({ "vocals": path.display().to_string() })))
        }
        "export_transcript" => {
            let output = req_str(&args, "output_path")?;
            let format = opt_str(&args, "format").unwrap_or_else(|| "txt".to_string());
            let content = match format.as_str() {
                "txt" => req_str(&args, "text")?,
                "srt" => req_str(&args, "srt")?,
                "lrc" => srt_to_lrc(&req_str(&args, "srt")?),
                other => return Ok(tool_fail(format!("不支持的格式: {other}"))),
            };
            fs::write(&output, &content).map_err(|e| format!("写入失败: {e}"))?;
            Ok(tool_text(json!({
                "saved": output,
                "format": format,
                "bytes": content.len()
            })))
        }
        "list_models" => list_models().map(tool_text),
        "get_settings" => {
            let path = settings_path();
            match fs::read_to_string(&path) {
                Ok(raw) => serde_json::from_str::<Value>(&raw)
                    .map(tool_text)
                    .map_err(|e| format!("设置文件解析失败: {e}")),
                Err(_) => Ok(tool_text(json!({}))),
            }
        }
        "save_settings" => {
            let data = args
                .get("data")
                .cloned()
                .ok_or("缺少 data".to_string())?;
            if !data.is_object() {
                Err("data 必须是 JSON 对象".to_string())
            } else {
                let path = settings_path();
                if let Some(parent) = path.parent() {
                    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
                }
                let pretty = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
                let tmp = path.with_extension("json.tmp");
                fs::write(&tmp, pretty).map_err(|e| e.to_string())?;
                fs::rename(&tmp, &path).map_err(|e| e.to_string())?;
                Ok(tool_text(json!({ "saved": path.display().to_string() })))
            }
        }
        "media_info" => {
            let path = req_str(&args, "path")?;
            media::media_info(path).map(tool_text)
        }
        "media_write_tags" => {
            let path = req_str(&args, "path")?;
            let tags = args
                .get("tags")
                .cloned()
                .ok_or("缺少 tags".to_string())?;
            if !tags.is_object() {
                Err("tags 必须是 JSON 对象".to_string())
            } else {
                media::media_write_tags(path, tags)
                    .map(|_| tool_text(json!({ "written": true })))
            }
        }
        "media_read_cover" => {
            let path = req_str(&args, "path")?;
            let include_data = opt_bool(&args, "include_data").unwrap_or(false);
            media::media_read_cover(path).map(|cover| match cover {
                None => tool_text(json!({ "has_cover": false })),
                Some(data_url) => {
                    let mut payload = json!({
                        "has_cover": true,
                        "data_url_len": data_url.len()
                    });
                    if include_data {
                        payload["data_url"] = json!(data_url);
                    }
                    tool_text(payload)
                }
            })
        }
        "media_set_cover" => {
            let path = req_str(&args, "path")?;
            let image = req_str(&args, "image")?;
            media::media_set_cover(path, image).map(|_| tool_text(json!({ "written": true })))
        }
        "media_remove_cover" => {
            let path = req_str(&args, "path")?;
            media::media_remove_cover(path).map(|_| tool_text(json!({ "removed": true })))
        }
        "media_rename" => {
            let path = req_str(&args, "path")?;
            let filename = req_str(&args, "filename")?;
            media::media_rename(path, filename)
                .map(|next| tool_text(json!({ "path": next, "name": base_name(&next) })))
        }
        "media_scan_folder" => {
            let dir = req_str(&args, "dir")?;
            media::media_scan_folder(dir).map(|items| {
                let count = items.len();
                tool_text(json!({ "count": count, "items": items }))
            })
        }
        "batch_rename_folder" => {
            let dir = req_str(&args, "dir")?;
            let pattern =
                opt_str(&args, "pattern").unwrap_or_else(|| "artist_title".to_string());
            let apply = opt_bool(&args, "apply").unwrap_or(false);
            let items = media::media_scan_folder(dir)?;
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
                let artist = tags
                    .get("artist")
                    .and_then(Value::as_str)
                    .map(str::to_string);
                let target = media::media_build_name(title, artist, pattern.clone());
                let entry = match target {
                    None => json!({ "from": current, "skipped": true, "reason": "标签不足" }),
                    Some(target) => {
                        let ext = current
                            .rfind('.')
                            .map(|index| current[index..].to_string())
                            .unwrap_or_default();
                        let preview = format!("{target}{ext}");
                        if !apply {
                            json!({ "from": current, "to": preview })
                        } else if preview == current {
                            json!({ "from": current, "to": preview, "skipped": true, "reason": "同名" })
                        } else {
                            match media::media_rename(path, target) {
                                Ok(next) => {
                                    renamed += 1;
                                    json!({ "from": current, "to": base_name(&next), "path": next })
                                }
                                Err(err) => json!({ "from": current, "to": preview, "error": err }),
                            }
                        }
                    }
                };
                plan.push(entry);
            }
            Ok(tool_text(json!({
                "applied": apply,
                "pattern": pattern,
                "renamed": renamed,
                "items": plan
            })))
        }
        "convert_media" => {
            let conversion: convert::ConvertArgs = serde_json::from_value(args)
                .map_err(|e| format!("参数不合法: {e}"))?;
            let output = conversion.output.clone();
            convert::convert_with(&conversion, &mut |_| {}, &|| false)?;
            Ok(tool_text(json!({ "output": output, "done": true })))
        }
        "list_convert_presets" => Ok(tool_text(convert::presets())),
        "ffmpeg_capabilities" => {
            let caps = convert::capabilities();
            if let Some(error) = caps.get("error").and_then(Value::as_str) {
                return Ok(tool_fail(error.to_string()));
            }
            let kind = opt_str(&args, "kind");
            let needle = opt_str(&args, "filter").map(|text| text.to_lowercase());
            let list = |key: &str| -> Value {
                match &kind {
                    None => return json!([]),
                    Some(kind) if kind != "all" && kind != key => return json!([]),
                    _ => {}
                }
                let items = caps
                    .get(key)
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                let kept: Vec<Value> = items
                    .into_iter()
                    .filter(|item| match &needle {
                        None => true,
                        Some(text) => item.to_string().to_lowercase().contains(text),
                    })
                    .collect();
                json!({ "count": kept.len(), "items": kept })
            };
            let count = |key: &str| {
                caps.get(key)
                    .and_then(Value::as_array)
                    .map(|items| items.len())
                    .unwrap_or(0)
            };
            Ok(tool_text(json!({
                "version": caps.get("version").cloned().unwrap_or(json!("")),
                "counts": {
                    "encoders": count("encoders"),
                    "formats": count("formats"),
                    "filters": count("filters"),
                    "pixel_formats": count("pixel_formats"),
                },
                "hwaccels": caps.get("hwaccels").cloned().unwrap_or(json!([])),
                "presets": caps.get("presets").cloned().unwrap_or(json!([])),
                "tunes": caps.get("tunes").cloned().unwrap_or(json!([])),
                "profiles": caps.get("profiles").cloned().unwrap_or(json!([])),
                "levels": caps.get("levels").cloned().unwrap_or(json!([])),
                "encoders": list("encoders"),
                "formats": list("formats"),
                "filters": list("filters"),
                "pixel_formats": list("pixel_formats"),
            })))
        }
        other => Err(format!("未知工具: {other}")),
    };

    Ok(result.unwrap_or_else(tool_fail))
}

fn main() {
    // 定位随包的 ffmpeg / ffprobe，后续媒体与转换工具直接复用。
    tools::set_resources(job::resources_dir());
    // stdout 只能输出协议内容，日志一律走 stderr。
    eprintln!("whisper-studio-mcp 已启动（stdio）");
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    for line in stdin.lock().lines().map_while(Result::ok) {
        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }
        let request: Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(err) => {
                eprintln!("忽略无法解析的输入: {err}");
                continue;
            }
        };
        let Some(id) = request.get("id").cloned() else {
            // 通知（notifications/initialized 等）不需要回应。
            continue;
        };
        let method = request
            .get("method")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let params = request.get("params").cloned().unwrap_or_else(|| json!({}));

        let response = match method {
            "initialize" => {
                let version = params
                    .get("protocolVersion")
                    .and_then(Value::as_str)
                    .unwrap_or("2024-11-05");
                json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "protocolVersion": version,
                        "capabilities": { "tools": {} },
                        "serverInfo": { "name": "whisper-studio", "version": "0.1.0" }
                    }
                })
            }
            "ping" => json!({ "jsonrpc": "2.0", "id": id, "result": {} }),
            "tools/list" => json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": { "tools": tool_defs() }
            }),
            "tools/call" => match call_tool(&params) {
                Ok(result) => json!({ "jsonrpc": "2.0", "id": id, "result": result }),
                Err(err) => json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "error": { "code": -32602, "message": err }
                }),
            },
            other => json!({
                "jsonrpc": "2.0",
                "id": id,
                "error": { "code": -32601, "message": format!("未知方法: {other}") }
            }),
        };
        let _ = writeln!(stdout, "{response}");
        let _ = stdout.flush();
    }
}
