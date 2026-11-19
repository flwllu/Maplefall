//! 音视频元数据处理：读取 / 写入标签、封面增删、单文件重命名、文件夹扫描。
//! 基于随包的静态 ffprobe / ffmpeg（找不到时退回系统 PATH），不引入额外的 Rust 原生依赖。

use serde_json::{json, Map, Value};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

/// 支持的音频扩展名（用于文件夹扫描与类型判断）。
const AUDIO_EXTS: &[&str] = &[
    "mp3", "flac", "m4a", "wav", "aiff", "aif", "ogg", "opus", "wma", "aac", "m4b", "alac",
];

const TAG_KEYS: &[&str] = &[
    "title",
    "artist",
    "album",
    "albumartist",
    "genre",
    "date",
    "tracknumber",
    "composer",
    "lyrics",
];

fn ffprobe(path: &Path) -> Result<Value, String> {
    let output = Command::new(crate::tools::ffprobe())
        .args([
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
        ])
        .arg(path)
        .output()
        .map_err(|e| format!("找不到 ffprobe，请先安装 FFmpeg：{e}"))?;
    if !output.status.success() {
        return Err(format!(
            "无法解析媒体信息：{}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    serde_json::from_slice(&output.stdout).map_err(|e| format!("解析 ffprobe 输出失败：{e}"))
}

/// 在大小写不敏感的前提下从 tags 对象里取一个键。
fn lookup_tag(tags: &Map<String, Value>, key: &str) -> Option<Value> {
    let aliases: &[&str] = match key {
        "tracknumber" => &["track", "tracknumber"],
        "albumartist" => &["albumartist", "album_artist"],
        "date" => &["date", "year"],
        _ => &[key],
    };
    for (name, value) in tags {
        let lower = name.to_ascii_lowercase();
        if aliases.iter().any(|alias| lower == *alias) {
            return Some(value.clone());
        }
    }
    None
}

#[tauri::command]
pub fn media_info(path: String) -> Result<Value, String> {
    let p = PathBuf::from(&path);
    if !p.is_file() {
        return Err("文件不存在".into());
    }
    let probe = ffprobe(&p)?;
    let format = probe.get("format").cloned().unwrap_or_else(|| json!({}));
    let empty = Vec::new();
    let streams = probe
        .get("streams")
        .and_then(|s| s.as_array())
        .unwrap_or(&empty);

    let audio = streams
        .iter()
        .find(|s| s.get("codec_type").and_then(|c| c.as_str()) == Some("audio"));
    let has_cover = streams.iter().any(|s| {
        s.get("codec_type").and_then(|c| c.as_str()) == Some("video")
            && s.get("disposition")
                .and_then(|d| d.get("attached_pic"))
                .and_then(|v| v.as_i64())
                == Some(1)
    });

    let num = |v: Option<&Value>| -> f64 {
        match v {
            Some(Value::String(s)) => s.parse().unwrap_or(0.0),
            Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0),
            _ => 0.0,
        }
    };

    let tags_obj = format
        .get("tags")
        .and_then(|t| t.as_object())
        .cloned()
        .unwrap_or_default();
    let mut tags = Map::new();
    for key in TAG_KEYS {
        tags.insert(
            (*key).to_string(),
            lookup_tag(&tags_obj, key).unwrap_or(Value::Null),
        );
    }

    // 全量流清单：格式转换页据此生成"选哪条视频/音频流"的下拉。
    let stream_list: Vec<Value> = streams
        .iter()
        .map(|s| {
            json!({
                "index": s.get("index").and_then(|v| v.as_i64()).unwrap_or(-1),
                "type": s.get("codec_type").and_then(|v| v.as_str()).unwrap_or(""),
                "codec": s.get("codec_name").cloned().unwrap_or(Value::Null),
                "language": s
                    .get("tags")
                    .and_then(|t| t.get("language"))
                    .cloned()
                    .unwrap_or(Value::Null),
                "channels": s.get("channels").cloned().unwrap_or(Value::Null),
                "width": s.get("width").cloned().unwrap_or(Value::Null),
                "height": s.get("height").cloned().unwrap_or(Value::Null),
                "attached_pic": s
                    .get("disposition")
                    .and_then(|d| d.get("attached_pic"))
                    .and_then(|v| v.as_i64())
                    == Some(1),
            })
        })
        .collect();

    Ok(json!({
        "path": path,
        "format": format.get("format_name").cloned().unwrap_or(Value::Null),
        "format_long": format.get("format_long_name").cloned().unwrap_or(Value::Null),
        "duration": num(format.get("duration")),
        "size": num(format.get("size")),
        "bit_rate": num(format.get("bit_rate")),
        "codec": audio.and_then(|s| s.get("codec_name")).cloned().unwrap_or(Value::Null),
        "sample_rate": num(audio.and_then(|s| s.get("sample_rate"))),
        "channels": num(audio.and_then(|s| s.get("channels"))),
        "tags": tags,
        "has_cover": has_cover,
        "streams": stream_list,
    }))
}

/// 轻量探测：只看这个文件里有没有音频流 / 视频流。
/// 选文件不再靠扩展名白名单（`.MOV` 这种大写后缀会被漏判），改成选完让 ffprobe 说话。
#[tauri::command]
pub fn media_probe(path: String) -> Result<Value, String> {
    let p = PathBuf::from(&path);
    if !p.is_file() {
        return Err("文件不存在".into());
    }
    let probe = ffprobe(&p)?;
    let empty = Vec::new();
    let streams = probe
        .get("streams")
        .and_then(|s| s.as_array())
        .unwrap_or(&empty);
    let has = |kind: &str| {
        streams
            .iter()
            .any(|s| s.get("codec_type").and_then(|c| c.as_str()) == Some(kind))
    };
    let format = probe
        .get("format")
        .and_then(|f| f.get("format_name"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    Ok(json!({
        "audio": has("audio"),
        "video": has("video"),
        "format": format,
    }))
}

/// 写入标签：先写到同目录临时文件，成功后再原子替换，避免写坏原文件。
#[tauri::command]
pub fn media_write_tags(path: String, tags: Value) -> Result<(), String> {
    let src = PathBuf::from(&path);
    if !src.is_file() {
        return Err("文件不存在".into());
    }
    let ext = src.extension().and_then(|e| e.to_str()).unwrap_or("");
    let tmp = src.with_file_name(format!(".media-studio-tmp-{}.{}", std::process::id(), ext));

    let mut cmd = Command::new(crate::tools::ffmpeg());
    cmd.arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-i")
        .arg(&src)
        .arg("-map")
        .arg("0")
        .arg("-c")
        .arg("copy");
    // 苹果「音乐」对 ID3v2.4 的歌词帧兼容性差，MP3 统一写 v2.3。
    if ext.eq_ignore_ascii_case("mp3") {
        cmd.arg("-id3v2_version").arg("3");
    }
    if let Some(obj) = tags.as_object() {
        for (key, value) in obj {
            if let Some(text) = value.as_str() {
                cmd.arg("-metadata").arg(format!("{key}={text}"));
            }
        }
    }
    cmd.arg(&tmp);

    let output = cmd
        .output()
        .map_err(|e| format!("无法执行内置 ffmpeg：{e}"))?;
    if !output.status.success() {
        let _ = std::fs::remove_file(&tmp);
        return Err(format!(
            "写入标签失败：{}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    std::fs::rename(&tmp, &src).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("替换原文件失败：{e}")
    })?;
    Ok(())
}

/// 老歌词文件常见 GBK 编码，先验 UTF-8，失败再用系统 iconv 转码。
fn decode_text(bytes: &[u8]) -> Result<String, String> {
    if let Ok(text) = String::from_utf8(bytes.to_vec()) {
        return Ok(text);
    }
    let mut child = Command::new("iconv")
        .args(["-f", "GB18030", "-t", "UTF-8"])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .map_err(|_| "歌词文件不是 UTF-8，系统又没有 iconv，请另存为 UTF-8 后重试".to_string())?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(bytes)
            .map_err(|e| format!("歌词转码失败：{e}"))?;
    }
    let output = child
        .wait_with_output()
        .map_err(|e| format!("歌词转码失败：{e}"))?;
    if !output.status.success() {
        return Err("歌词文件既不是 UTF-8 也不是 GBK，请另存为 UTF-8".into());
    }
    String::from_utf8(output.stdout).map_err(|_| "歌词转码结果异常".into())
}

/// 读取用户选中的歌词文件（LRC / SRT / VTT / TXT），交给前端解析。
#[tauri::command]
pub fn media_read_text(path: String) -> Result<String, String> {
    let bytes = std::fs::read(&path).map_err(|e| format!("读取歌词文件失败：{e}"))?;
    if bytes.len() > 2 * 1024 * 1024 {
        return Err("歌词文件超过 2 MB，请检查选错文件".into());
    }
    let text = decode_text(&bytes)?;
    Ok(text.trim_start_matches('\u{feff}').replace("\r\n", "\n"))
}

/// 极简 base64 编码，避免为一个封面预览引入额外依赖。
fn base64_encode(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = *chunk.get(1).unwrap_or(&0) as u32;
        let b2 = *chunk.get(2).unwrap_or(&0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(TABLE[((n >> 18) & 63) as usize] as char);
        out.push(TABLE[((n >> 12) & 63) as usize] as char);
        out.push(if chunk.len() > 1 {
            TABLE[((n >> 6) & 63) as usize] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            TABLE[(n & 63) as usize] as char
        } else {
            '='
        });
    }
    out
}

/// 读取内嵌封面，返回可直接给 `<img src>` 使用的 data URL；没有封面返回 None。
#[tauri::command]
pub fn media_read_cover(path: String) -> Result<Option<String>, String> {
    let src = PathBuf::from(&path);
    if !src.is_file() {
        return Err("文件不存在".into());
    }
    let probe = ffprobe(&src)?;
    let empty = Vec::new();
    let streams = probe
        .get("streams")
        .and_then(|s| s.as_array())
        .unwrap_or(&empty);
    let cover = streams.iter().find(|s| {
        s.get("codec_type").and_then(|c| c.as_str()) == Some("video")
            && s.get("disposition")
                .and_then(|d| d.get("attached_pic"))
                .and_then(|v| v.as_i64())
                == Some(1)
    });
    let Some(cover) = cover else {
        return Ok(None);
    };
    let codec = cover
        .get("codec_name")
        .and_then(|c| c.as_str())
        .unwrap_or("mjpeg");
    let mime = match codec {
        "png" => "png",
        "bmp" => "bmp",
        "gif" => "gif",
        "webp" => "webp",
        _ => "jpeg",
    };

    let output = Command::new(crate::tools::ffmpeg())
        .args(["-y", "-v", "error", "-i"])
        .arg(&src)
        .args([
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "pipe:1",
        ])
        .output()
        .map_err(|e| format!("找不到 ffmpeg：{e}"))?;
    if !output.status.success() || output.stdout.is_empty() {
        return Ok(None);
    }
    Ok(Some(format!(
        "data:image/{mime};base64,{}",
        base64_encode(&output.stdout)
    )))
}

/// 写入（替换）封面。先写临时文件再原子替换。
#[tauri::command]
pub fn media_set_cover(path: String, image: String) -> Result<(), String> {
    let src = PathBuf::from(&path);
    let img = PathBuf::from(&image);
    if !src.is_file() {
        return Err("音频文件不存在".into());
    }
    if !img.is_file() {
        return Err("封面图片不存在".into());
    }
    let ext = src.extension().and_then(|e| e.to_str()).unwrap_or("");
    let tmp = src.with_file_name(format!(".media-studio-tmp-{}.{}", std::process::id(), ext));

    let mut cmd = Command::new(crate::tools::ffmpeg());
    cmd.arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-i")
        .arg(&src)
        .arg("-i")
        .arg(&img);

    if ext.eq_ignore_ascii_case("mp3") || ext.eq_ignore_ascii_case("wav") || ext.eq_ignore_ascii_case("aiff") || ext.eq_ignore_ascii_case("aif") {
        // ID3 容器：音频 + 附加图片
        cmd.args(["-map", "0:a", "-map", "1:v", "-c", "copy", "-id3v2_version", "3"])
            .args(["-metadata:s:v", "title=Album cover"])
            .args(["-metadata:s:v", "comment=Cover (front)"])
            .args(["-disposition:v:0", "attached_pic"]);
    } else {
        // FLAC / M4A / 其它：整文件重封装，图片作为 attached_pic
        cmd.args(["-map", "0", "-map", "1:v", "-c", "copy"])
            .args(["-disposition:v:0", "attached_pic"]);
    }
    cmd.arg(&tmp);

    let output = cmd.output().map_err(|e| format!("找不到 ffmpeg：{e}"))?;
    if !output.status.success() {
        let _ = std::fs::remove_file(&tmp);
        return Err(format!(
            "写入封面失败：{}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    std::fs::rename(&tmp, &src).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("替换原文件失败：{e}")
    })?;
    Ok(())
}

/// 删除封面（保留全部音频流）。
#[tauri::command]
pub fn media_remove_cover(path: String) -> Result<(), String> {
    let src = PathBuf::from(&path);
    if !src.is_file() {
        return Err("文件不存在".into());
    }
    let ext = src.extension().and_then(|e| e.to_str()).unwrap_or("");
    let tmp = src.with_file_name(format!(".media-studio-tmp-{}.{}", std::process::id(), ext));

    let output = Command::new(crate::tools::ffmpeg())
        .args(["-y", "-v", "error", "-i"])
        .arg(&src)
        .args(["-map", "0:a", "-c", "copy"])
        .arg(&tmp)
        .output()
        .map_err(|e| format!("找不到 ffmpeg：{e}"))?;
    if !output.status.success() {
        let _ = std::fs::remove_file(&tmp);
        return Err(format!(
            "删除封面失败：{}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    std::fs::rename(&tmp, &src).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("替换原文件失败：{e}")
    })?;
    Ok(())
}

/// 重命名文件（同目录内），返回新路径。
#[tauri::command]
pub fn media_rename(path: String, filename: String) -> Result<String, String> {
    let src = PathBuf::from(&path);
    if !src.is_file() {
        return Err("文件不存在".into());
    }
    let folder = src.parent().ok_or("无法获取所在目录")?;
    let ext = src.extension().and_then(|e| e.to_str()).unwrap_or("");
    let safe: String = filename
        .chars()
        .map(|c| if "/\\:*?\"<>|".contains(c) { '_' } else { c })
        .collect();
    let file_name = if ext.is_empty() {
        safe
    } else {
        format!("{}.{}", safe.trim_end_matches('.').trim(), ext)
    };
    let dest = folder.join(file_name);
    if dest.exists() && dest != src {
        return Err(format!("目标文件已存在：{}", dest.display()));
    }
    std::fs::rename(&src, &dest).map_err(|e| format!("重命名失败：{e}"))?;
    Ok(dest.to_string_lossy().to_string())
}

/// 扫描文件夹内的音频文件（非递归）。
#[tauri::command]
pub fn media_scan_folder(dir: String) -> Result<Vec<Value>, String> {
    let folder = PathBuf::from(&dir);
    if !folder.is_dir() {
        return Err("目录不存在".into());
    }
    let mut items = Vec::new();
    let entries = std::fs::read_dir(&folder).map_err(|e| format!("读取目录失败：{e}"))?;
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let ext = path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        if !AUDIO_EXTS.contains(&ext.as_str()) {
            continue;
        }
        let info = media_info(path.to_string_lossy().to_string()).ok();
        items.push(json!({
            "path": path.to_string_lossy().to_string(),
            "name": path.file_name().and_then(|n| n.to_str()).unwrap_or(""),
            "info": info,
        }));
    }
    items.sort_by(|a, b| {
        let an = a.get("name").and_then(|v| v.as_str()).unwrap_or("");
        let bn = b.get("name").and_then(|v| v.as_str()).unwrap_or("");
        an.to_ascii_lowercase().cmp(&bn.to_ascii_lowercase())
    });
    Ok(items)
}

/// 根据标签生成文件名：{artist} - {title} 等模板。
#[tauri::command]
pub fn media_build_name(title: Option<String>, artist: Option<String>, pattern: String) -> Option<String> {
    let title = title.unwrap_or_default();
    let artist = artist.unwrap_or_default();
    let mut name = match pattern.as_str() {
        "title_only" => title.clone(),
        "artist_only" => artist.clone(),
        "title_artist" => format!("{} - {}", title, artist),
        _ => format!("{} - {}", artist, title),
    };
    name = name.trim_matches(|c| c == ' ' || c == '-').to_string();
    if name.is_empty() {
        return None;
    }
    let cleaned: String = name
        .chars()
        .map(|c| if "/\\:*?\"<>|".contains(c) { '_' } else { c })
        .collect();
    Some(cleaned)
}
