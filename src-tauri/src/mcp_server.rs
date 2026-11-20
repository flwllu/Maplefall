//! 应用内嵌的 MCP 端点：只在 whisper-studio 运行时监听 127.0.0.1:17321。
//! 每个请求临时拉起 whisper-studio-mcp 子进程转发，回答完立刻退出，不常驻空转。

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

const PORT: u16 = 17321;

/// 监听器的生命周期由状态持有：关闭时 drop 掉 listener 释放端口，
/// 代次（generation）用来让旧的接收循环自行退出。
struct State {
    enabled: bool,
    generation: u64,
    listener: Option<TcpListener>,
}

static STATE: OnceLock<Mutex<State>> = OnceLock::new();

fn state() -> &'static Mutex<State> {
    STATE.get_or_init(|| Mutex::new(State { enabled: false, generation: 0, listener: None }))
}

pub fn is_enabled() -> bool {
    state().lock().map(|s| s.enabled).unwrap_or(false)
}

/// 随应用启动：由设置里的开关决定是否监听。
pub fn start_if(enabled: bool) -> Result<(), String> {
    set_enabled(enabled)
}

/// 立即生效的开关；关闭后端口释放，MCP 客户端会显示未连接。
pub fn set_enabled(enabled: bool) -> Result<(), String> {
    let mut guard = state().lock().map_err(|_| "MCP 状态锁已损坏".to_string())?;
    if guard.enabled == enabled && (enabled == guard.listener.is_some()) {
        return Ok(());
    }
    guard.enabled = enabled;
    guard.generation += 1;
    let generation = guard.generation;
    guard.listener = None;

    if enabled {
        let listener = TcpListener::bind(("127.0.0.1", PORT))
            .map_err(|e| format!("MCP 端口 {PORT} 无法监听：{e}"))?;
        listener
            .set_nonblocking(true)
            .map_err(|e| format!("MCP 端口设置失败：{e}"))?;
        guard.listener = Some(listener);
        std::thread::spawn(move || accept_loop(generation));
    }
    Ok(())
}

fn accept_loop(generation: u64) {
    loop {
        std::thread::sleep(Duration::from_millis(100));
        let guard = match state().lock() {
            Ok(guard) => guard,
            Err(_) => return,
        };
        if guard.generation != generation || !guard.enabled {
            return;
        }
        let listener = match guard.listener.as_ref() {
            Some(listener) => listener,
            None => return,
        };
        match listener.accept() {
            Ok((stream, _)) => {
                std::thread::spawn(move || {
                    let _ = handle(stream);
                });
            }
            Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {}
            Err(err) => {
                eprintln!("MCP 接受连接失败：{err}");
                return;
            }
        }
    }
}

/// Windows 下子进程可执行文件必须带 .exe；其他平台保持原名。
fn mcp_binary_name() -> &'static str {
    if cfg!(windows) {
        "whisper-studio-mcp.exe"
    } else {
        "whisper-studio-mcp"
    }
}

fn mcp_binary() -> PathBuf {
    let name = mcp_binary_name();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let candidate = dir.join(name);
            if candidate.exists() {
                return candidate;
            }
        }
    }
    PathBuf::from(name)
}

fn handle(mut stream: TcpStream) -> std::io::Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut request_line = String::new();
    if reader.read_line(&mut request_line)? == 0 {
        return Ok(());
    }
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or_default().to_string();
    let path = parts.next().unwrap_or_default().to_string();

    let mut content_length = 0usize;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            break;
        }
        let trimmed = line.trim_end();
        if trimmed.is_empty() {
            break;
        }
        let lower = trimmed.to_ascii_lowercase();
        if let Some(value) = lower.strip_prefix("content-length:") {
            content_length = value.trim().parse().unwrap_or(0);
        }
    }

    if method == "OPTIONS" {
        return respond(&mut stream, 204, "", &[]);
    }
    if path.split('?').next().unwrap_or_default() != "/mcp" {
        return respond(&mut stream, 404, "not found", &[]);
    }
    if method != "POST" {
        // 不支持 SSE 长连接，只接受请求-响应模式。
        return respond(&mut stream, 405, "method not allowed", &[]);
    }

    let mut body = vec![0u8; content_length];
    if content_length > 0 {
        reader.read_exact(&mut body)?;
    }
    let body = String::from_utf8_lossy(&body).to_string();
    let parsed: Option<serde_json::Value> = serde_json::from_str(&body).ok();

    // 通知（notifications/initialized 等）没有 id，按协议回 202 即可。
    // 不能转发给子进程：通知不会产生输出，会一直卡在读取上。
    if parsed
        .as_ref()
        .map(|value| value.get("id").is_none())
        .unwrap_or(false)
    {
        return respond(&mut stream, 202, "", &[]);
    }

    let is_init = body.contains("\"initialize\"");

    // 转写提交给统一任务队列，立即返回任务 ID，不阻塞 MCP 客户端；其它工具照旧转发。
    if let Some(answer) = try_handle_transcribe(&parsed) {
        return respond(&mut stream, 200, &answer, &[]);
    }

    match forward(&body) {
        Ok(answer) => {
            let is_tools_list = parsed.as_ref()
                .and_then(|v| v.get("method"))
                .and_then(|m| m.as_str())
                == Some("tools/list");
            let answer = if is_tools_list {
                inject_task_tools(&answer)
            } else {
                answer
            };
            let extra: Vec<(&str, &str)> = if is_init {
                vec![("Mcp-Session-Id", "whisper-studio")]
            } else {
                Vec::new()
            };
            respond(&mut stream, 200, &answer, &extra)
        }
        Err(err) => {
            let payload = serde_json::json!({
                "jsonrpc": "2.0",
                "id": null,
                "error": { "code": -32603, "message": err }
            })
            .to_string();
            respond(&mut stream, 500, &payload, &[])
        }
    }
}

/// 把主程序层拦截的任务工具补进 tools/list，让 MCP 客户端能发现它们。
fn inject_task_tools(answer: &str) -> String {
    use serde_json::{json, Value};
    let extra = vec![
        json!({
            "name": "get_task_log",
            "description": "按任务 ID 获取该任务的运行日志（含进度、阶段、whisper 输出行）。任务提交后用它查看详细日志。",
            "inputSchema": { "type": "object", "properties": { "id": { "type": "string", "description": "transcribe_audio 返回的 task_id" } }, "required": ["id"] }
        }),
        json!({
            "name": "get_task",
            "description": "按任务 ID 获取任务完整信息，含状态、进度、转写文本 text、字幕 srt 与日志 log。",
            "inputSchema": { "type": "object", "properties": { "id": { "type": "string" } }, "required": ["id"] }
        }),
        json!({
            "name": "list_tasks",
            "description": "列出全部任务的状态、进度与来源（含日志）。",
            "inputSchema": { "type": "object", "properties": {} }
        }),
        json!({
            "name": "cancel_task",
            "description": "取消任务：真正杀掉运行中的子进程并把任务标记为已取消。",
            "inputSchema": { "type": "object", "properties": { "id": { "type": "string" } }, "required": ["id"] }
        }),
    ];
    let mut value: Value = match serde_json::from_str(answer) {
        Ok(value) => value,
        Err(_) => return answer.to_string(),
    };
    if let Some(tools) = value
        .get_mut("result")
        .and_then(|r| r.get_mut("tools"))
        .and_then(|t| t.as_array_mut())
    {
        for tool in extra {
            let name = tool.get("name").and_then(|n| n.as_str()).unwrap_or("");
            if !tools.iter().any(|t| t.get("name").and_then(|n| n.as_str()) == Some(name)) {
                tools.push(tool);
            }
        }
    }
    value.to_string()
}

/// 拦截 transcribe_audio：转成统一任务提交，返回任务 ID。非转写请求返回 None。
fn try_handle_transcribe(parsed: &Option<serde_json::Value>) -> Option<String> {
    use serde_json::{json, Value};
    let root = parsed.as_ref()?;
    let method = root.get("method")?.as_str()?;
    if method != "tools/call" {
        return None;
    }
    let params = root.get("params")?;
    let tool_name = params.get("name")?.as_str()?;
    if !matches!(tool_name, "transcribe_audio" | "cancel_task" | "list_tasks" | "get_task" | "get_task_log") {
        return None;
    }
    let args = params.get("arguments").cloned().unwrap_or_else(|| json!({}));
    let id = root.get("id").cloned().unwrap_or(Value::Null);

    let result_value = |payload: Value| -> String {
        json!({
            "jsonrpc": "2.0", "id": id,
            "result": {
                "content": [{ "type": "text", "text": payload.to_string() }],
                "isError": false
            }
        }).to_string()
    };

    if tool_name == "cancel_task" {
        let task_id = args.get("id").and_then(Value::as_str).unwrap_or("");
        let outcome = crate::task_manager::cancel(task_id);
        return Some(result_value(match outcome {
            Ok(()) => json!({ "cancelled": task_id }),
            Err(err) => json!({ "cancelled": false, "error": err }),
        }));
    }
    if tool_name == "list_tasks" {
        let tasks = crate::task_manager::list();
        return Some(result_value(json!({ "tasks": tasks })));
    }
    if tool_name == "get_task" || tool_name == "get_task_log" {
        let task_id = args.get("id").and_then(Value::as_str).unwrap_or("");
        let task = crate::task_manager::get(task_id);
        let payload = match task {
            Some(t) if tool_name == "get_task_log" => json!({
                "id": t.id, "status": t.status, "progress": t.progress, "log": t.log
            }),
            Some(t) => json!({ "task": t }),
            None => json!({ "error": "任务不存在" }),
        };
        return Some(result_value(payload));
    }

    let get_str = |key: &str, default: &str| -> String {
        args.get(key).and_then(Value::as_str).filter(|s| !s.is_empty()).unwrap_or(default).to_string()
    };
    let get_bool = |key: &str, default: bool| -> bool {
        args.get(key).and_then(Value::as_bool).unwrap_or(default)
    };
    let get_num_u = |key: &str| -> Option<u32> {
        args.get(key).and_then(Value::as_u64).map(|v| v as u32)
    };
    let get_num_f = |key: &str| -> Option<f64> {
        args.get(key).and_then(Value::as_f64)
    };

    let input_path = match args.get("input_path").and_then(Value::as_str) {
        Some(path) if !path.is_empty() => path.to_string(),
        _ => {
            return Some(json!({
                "jsonrpc": "2.0", "id": id,
                "error": { "code": -32602, "message": "缺少 input_path" }
            }).to_string());
        }
    };
    let title = PathBuf::from(&input_path)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "转写任务".into());

    let params = json!({
        "input_path": input_path,
        "model": get_str("model", "ggml-large-v3-turbo-q5_0.bin"),
        "language": get_str("language", "auto"),
        "separate": get_bool("separate", true),
        "vad": get_bool("vad", false),
        "suppress_ns": get_bool("suppress_ns", true),
        "coreml": get_bool("acceleration", true),
        "no_context": get_bool("no_context", true),
        "prompt": args.get("prompt").and_then(Value::as_str).map(str::to_string),
        "no_fallback": get_bool("no_fallback", false),
        "beam_size": get_num_u("beam_size"),
        "best_of": get_num_u("best_of"),
        "no_speech_thold": get_num_f("no_speech_thold"),
        "entropy_thold": get_num_f("entropy_thold").unwrap_or(2.8),
        "logprob_thold": get_num_f("logprob_thold"),
        "word_thold": get_num_f("word_thold"),
        "max_len": get_num_u("max_len"),
    });
    let task_id = crate::task_manager::submit("transcribe", params, "mcp", title);
    Some(result_value(json!({
        "task_id": task_id,
        "status": "queued",
        "message": "任务已提交，可通过任务列表查看进度与结果"
    })))
}

fn forward(body: &str) -> Result<String, String> {
    let binary = mcp_binary();
    let mut child = Command::new(&binary)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("启动 {} 失败: {e}", binary.display()))?;
    {
        let mut stdin = child.stdin.take().ok_or("无法写入子进程")?;
        writeln!(stdin, "{}", body.trim()).map_err(|e| e.to_string())?;
        // 关闭 stdin，让子进程处理完这一条后自然退出；否则读输出会一直阻塞。
        drop(stdin);
    }
    let stdout = child.stdout.take().ok_or("无法读取子进程输出")?;
    let mut line = String::new();
    BufReader::new(stdout)
        .read_line(&mut line)
        .map_err(|e| e.to_string())?;
    let _ = child.kill();
    let _ = child.wait();
    if line.trim().is_empty() {
        return Err("MCP 子进程没有返回结果".into());
    }
    Ok(line.trim().to_string())
}

fn respond(
    stream: &mut TcpStream,
    status: u16,
    body: &str,
    extra: &[(&str, &str)],
) -> std::io::Result<()> {
    let reason = match status {
        200 => "OK",
        202 => "Accepted",
        204 => "No Content",
        404 => "Not Found",
        405 => "Method Not Allowed",
        _ => "Internal Server Error",
    };
    let mut head = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: content-type, mcp-session-id\r\nAccess-Control-Allow-Methods: POST, OPTIONS\r\n",
        body.len()
    );
    for (key, value) in extra {
        head.push_str(&format!("{key}: {value}\r\n"));
    }
    head.push_str("\r\n");
    stream.write_all(head.as_bytes())?;
    stream.write_all(body.as_bytes())?;
    stream.flush()
}
