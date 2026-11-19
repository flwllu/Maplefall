//! 外部可执行文件的定位：优先用随包内置的副本，找不到再退回 PATH。
//!
//! 应用与 MCP 二进制都会在启动时调用 [`set_resources`] 告知资源目录，
//! 之后的 `ffmpeg()` / `ffprobe()` 就能解析到包内的静态构建。

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

static RESOURCES: OnceLock<PathBuf> = OnceLock::new();

/// 记录资源根目录（即包含 `models/`、`bin/` 的那一层）。重复调用会被忽略。
pub fn set_resources(dir: PathBuf) {
    let _ = RESOURCES.set(dir);
}

fn bundled(name: &str) -> Option<PathBuf> {
    let root = RESOURCES.get()?;
    let file = format!("{name}{}", std::env::consts::EXE_SUFFIX);
    let path = root.join("bin").join("ffmpeg").join(file);
    path.exists().then_some(path)
}

/// 随包的静态 ffmpeg；缺失时退回 `ffmpeg`（交给 PATH 解析）。
pub fn ffmpeg() -> PathBuf {
    bundled("ffmpeg").unwrap_or_else(|| PathBuf::from("ffmpeg"))
}

/// 随包的静态 ffprobe；缺失时退回 `ffprobe`。
pub fn ffprobe() -> PathBuf {
    bundled("ffprobe").unwrap_or_else(|| PathBuf::from("ffprobe"))
}

/// 按平台定位随包的 whisper-cli（主程序与 MCP 共用同一套规则）：
/// - macOS：`bin/whisper_cpp/whisper-cli`
/// - Windows：`bin/whisper_cpp/windows/whisper-cli.exe`
/// - Linux x86_64：`bin/whisper_cpp/linux-x64/whisper-cli`
/// - Linux aarch64：`bin/whisper_cpp/linux-arm64/whisper-cli`
pub fn whisper_cli_path(root: &Path) -> PathBuf {
    let base = root.join("bin").join("whisper_cpp");
    if cfg!(windows) {
        base.join("windows").join("whisper-cli.exe")
    } else if cfg!(target_os = "linux") {
        let dir = if cfg!(target_arch = "aarch64") {
            "linux-arm64"
        } else {
            "linux-x64"
        };
        base.join(dir).join("whisper-cli")
    } else {
        base.join("whisper-cli")
    }
}

/// whisper-cli 的库搜索目录：Linux 下同目录的 `.so` 未必有 `$ORIGIN` rpath，
/// 调用前把这一层挂到 `LD_LIBRARY_PATH` 就能兜住。其它平台返回 `None`。
pub fn cli_lib_dir(cli: &Path) -> Option<PathBuf> {
    if cfg!(target_os = "linux") {
        cli.parent().map(Path::to_path_buf)
    } else {
        None
    }
}
