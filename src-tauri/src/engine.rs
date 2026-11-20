//! 转写引擎：把 whisper-cli 的调用集中在这里，主程序和 MCP 共用。
//! 长音频按固定时长切片逐块识别，每块都带上初始提示和上一块的结尾，
//! 避免长上下文漂移（重复段整段崩、末尾幻觉）。

use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

pub struct Options {
    pub cli: PathBuf,
    pub model: PathBuf,
    pub vad_model: Option<PathBuf>,
    pub language: String,
    pub threads: i32,
    pub suppress_ns: bool,
    pub vad: bool,
    pub prompt: Option<String>,
    pub no_context: bool,
    pub entropy_thold: f64,
    pub no_fallback: bool,
    pub beam_size: Option<u32>,
    pub best_of: Option<u32>,
    pub no_speech_thold: Option<f64>,
    pub logprob_thold: Option<f64>,
    pub word_thold: Option<f64>,
    pub max_len: Option<u32>,
    /// 单块时长（毫秒），0 表示不切片
    pub chunk_ms: u64,
}

pub struct Output {
    pub text: String,
    pub srt: String,
}

fn percent_of(line: &str) -> Option<u32> {
    let marker = line.find("progress")?;
    let rest = &line[marker..];
    let digits: String = rest
        .chars()
        .skip_while(|c| !c.is_ascii_digit())
        .take_while(|c| c.is_ascii_digit())
        .collect();
    digits.parse().ok()
}

fn build_command(opts: &Options, audio: &Path, prefix: &Path) -> Command {
    let mut cmd = Command::new(&opts.cli);
    // Linux 下同目录的 .so 未必带 $ORIGIN rpath，这里补一层库搜索路径。
    if let Some(dir) = crate::tools::cli_lib_dir(&opts.cli) {
        let mut paths = vec![dir];
        if let Some(existing) = std::env::var_os("LD_LIBRARY_PATH") {
            paths.extend(std::env::split_paths(&existing));
        }
        if let Ok(joined) = std::env::join_paths(paths) {
            cmd.env("LD_LIBRARY_PATH", joined);
        }
    }
    cmd.arg("-m")
        .arg(&opts.model)
        .arg("-f")
        .arg(audio)
        .arg("-l")
        .arg(&opts.language)
        .arg("-t")
        .arg(opts.threads.to_string())
        .arg("--print-progress")
        .arg("--entropy-thold")
        .arg(opts.entropy_thold.to_string())
        .arg("-otxt")
        .arg("-osrt")
        .arg("-of")
        .arg(prefix)
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    if opts.vad {
        if let Some(model) = &opts.vad_model {
            cmd.arg("--vad").arg("-vm").arg(model);
        }
    }
    if opts.suppress_ns {
        cmd.arg("--suppress-nst");
    }
    if opts.no_fallback {
        cmd.arg("-nf");
    }
    if let Some(v) = opts.beam_size {
        cmd.arg("-bs").arg(v.to_string());
    }
    if let Some(v) = opts.best_of {
        cmd.arg("-bo").arg(v.to_string());
    }
    if let Some(v) = opts.no_speech_thold {
        cmd.arg("-nth").arg(v.to_string());
    }
    if let Some(v) = opts.logprob_thold {
        cmd.arg("-lpt").arg(v.to_string());
    }
    if let Some(v) = opts.word_thold {
        cmd.arg("-wt").arg(v.to_string());
    }
    if let Some(v) = opts.max_len {
        cmd.arg("-ml").arg(v.to_string());
    }
    cmd
}

fn parse_time(text: &str) -> Option<u64> {
    let mut parts = text.split(':');
    let h: u64 = parts.next()?.parse().ok()?;
    let m: u64 = parts.next()?.parse().ok()?;
    let rest = parts.next()?;
    let (s, ms) = rest.split_once(',')?;
    Some(((h * 60 + m) * 60 + s.parse::<u64>().ok()?) * 1000 + ms.parse::<u64>().ok()?)
}

fn format_timestamp(ms: u64) -> String {
    let millis = ms % 1000;
    let secs = (ms / 1000) % 60;
    let mins = (ms / 60000) % 60;
    let hours = ms / 3600000;
    format!("{hours:02}:{mins:02}:{secs:02},{millis:03}")
}

/// 重新编号单块产出的 SRT。
/// whisper-cli 写入的时间戳已经包含 `-ot` 偏移（实测 `-ot 20000` 的首条就是 00:00:20,000），
/// 这里不能再平移，否则整条时间轴会成倍后移。
fn merge_srt(srt: &str, start_index: u32) -> (String, u32) {
    let mut index = start_index;
    let mut out: Vec<String> = Vec::new();
    for block in srt.trim().split("\n\n") {
        let lines: Vec<&str> = block.lines().collect();
        if lines.len() < 3 {
            continue;
        }
        let Some((from, to)) = lines[1].split_once("-->") else {
            continue;
        };
        let (Some(from), Some(to)) = (parse_time(from.trim()), parse_time(to.trim())) else {
            continue;
        };
        index += 1;
        let mut shifted = vec![
            index.to_string(),
            format!(
                "{} --> {}",
                format_timestamp(from),
                format_timestamp(to)
            ),
        ];
        shifted.extend(lines[2..].iter().map(|line| line.to_string()));
        out.push(shifted.join("\n"));
    }
    (out.join("\n\n"), index)
}

struct Pass<'a> {
    opts: &'a Options,
    on_progress: &'a mut dyn FnMut(u32),
    on_line: &'a mut dyn FnMut(&str),
    cancelled: &'a dyn Fn() -> bool,
}

impl Pass<'_> {
    fn run_chunk(
        &mut self,
        audio: &Path,
        prefix: &Path,
        start_ms: u64,
        duration_ms: u64,
        prompt: Option<&str>,
        progress_base: u32,
        progress_span: u32,
    ) -> Result<(String, String), String> {
        let mut cmd = build_command(self.opts, audio, prefix);
        cmd.arg("-ot").arg(start_ms.to_string());
        if duration_ms > 0 {
            cmd.arg("-d").arg(duration_ms.to_string());
        }
        match prompt {
            Some(prompt) => {
                cmd.arg("--prompt").arg(prompt);
            }
            None => {
                // 没有提示词时关闭跨窗口上下文，减少长音频漂移。
                if self.opts.no_context {
                    cmd.arg("-mc").arg("0");
                }
            }
        }
        let mut child = cmd.spawn().map_err(|e| format!("启动失败: {e}"))?;
        if let Some(stderr) = child.stderr.take() {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                if (self.cancelled)() {
                    let _ = child.kill();
                    break;
                }
                if let Some(percent) = percent_of(&line) {
                    (self.on_progress)(progress_base + percent * progress_span / 100);
                } else {
                    (self.on_line)(&line);
                }
            }
        }
        let status = child.wait().map_err(|e| e.to_string())?;
        if (self.cancelled)() {
            return Err("已停止".into());
        }
        if !status.success() {
            return Err(format!("whisper-cli 退出码 {:?}", status.code()));
        }
        let text = fs::read_to_string(prefix.with_extension("txt")).unwrap_or_default();
        let srt = fs::read_to_string(prefix.with_extension("srt")).unwrap_or_default();
        let _ = fs::remove_file(prefix.with_extension("txt"));
        let _ = fs::remove_file(prefix.with_extension("srt"));
        Ok((text.trim().to_string(), srt))
    }
}

/// 取上一块最后若干字符作为下一块的衔接提示，控制在不超上下文一半的范围内。
fn tail_prompt(text: &str) -> String {
    let chars: Vec<char> = text.chars().filter(|c| *c != '\n').collect();
    let take = 60.min(chars.len());
    chars[chars.len() - take..].iter().collect()
}

pub fn run(
    audio: &Path,
    out_dir: &Path,
    stamp: u128,
    opts: &Options,
    on_progress: &mut dyn FnMut(u32),
    on_line: &mut dyn FnMut(&str),
    cancelled: &dyn Fn() -> bool,
) -> Result<Output, String> {
    if (cancelled)() {
        return Err("已停止".into());
    }
    let duration = crate::mdx::audio_duration_secs(audio)?;
    let chunk_ms = if opts.chunk_ms == 0 { 0 } else { opts.chunk_ms };
    let chunks = if chunk_ms > 0 {
        ((duration * 1000.0 / chunk_ms as f64).ceil() as u64).max(1)
    } else {
        1
    };

    let mut pass = Pass {
        opts,
        on_progress,
        on_line,
        cancelled,
    };
    let initial = opts
        .prompt
        .as_deref()
        .map(str::trim)
        .filter(|p| !p.is_empty());

    // 短视频或关闭切片：一次跑完，行为与之前一致。
    if chunks <= 1 {
        let prefix = out_dir.join(format!("transcript-{stamp}"));
        let (text, srt) = pass.run_chunk(audio, &prefix, 0, 0, initial, 0, 100)?;
        return Ok(Output { text, srt });
    }

    let mut texts: Vec<String> = Vec::new();
    let mut srt_parts: Vec<String> = Vec::new();
    let mut index = 0u32;
    let mut tail = String::new();
    for i in 0..chunks {
        if (cancelled)() {
            return Err("已停止".into());
        }
        let start_ms = i * chunk_ms;
        let prefix = out_dir.join(format!("transcript-{stamp}-{i}"));
        let mut prompt = initial.map(str::to_string).unwrap_or_default();
        if !tail.is_empty() {
            if !prompt.is_empty() {
                prompt.push(' ');
            }
            prompt.push_str(&tail);
        }
        let prompt_ref = if prompt.is_empty() {
            None
        } else {
            Some(prompt.as_str())
        };
        let base = (i * 100 / chunks) as u32;
        let span = (100 / chunks) as u32;
        let (text, srt) = pass.run_chunk(
            audio,
            &prefix,
            start_ms,
            chunk_ms,
            prompt_ref,
            base,
            span.max(1),
        )?;
        if !text.is_empty() {
            texts.push(text.clone());
            tail = tail_prompt(&text);
        }
        if !srt.trim().is_empty() {
            let (merged, next) = merge_srt(&srt, index);
            if !merged.is_empty() {
                srt_parts.push(merged);
                index = next;
            }
        }
    }
    (on_progress)(100);
    Ok(Output {
        text: texts.join("\n"),
        srt: srt_parts.join("\n\n"),
    })
}
