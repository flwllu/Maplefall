# 三平台最小改动方案 · macOS

> 三份文档各写一个平台（MACOS / LINUX / WINDOWS），互不混写。分类标准：每份开头列出「共用约定」（三平台能复用的只维护一份），然后只写本平台必须改的地方。
> 原则：最小改动 = 能不动的就不动；必须动的才写。

## 共用约定（三平台一致，只维护一份）

- **模型文件共用一份**：`resources/models/ggml-large-v3-turbo-q5_0.bin`、`ggml-silero-v5.1.2.bin` 是 ggml 通用格式，三平台都用这一份，不按平台复制。
- **前端共用**：`src/` 纯 HTML/CSS/JS，三平台共用；`app.js:6` 的 `.is-mac` 只在 macOS 命中，其他平台自然跳过。
- **通用代码共用**：`engine.rs`（起 whisper-cli 进程）、`mcp_server.rs`（HTTP 端点）、`main.rs` 的设置/缓存/切片逻辑、`mdx.rs` 的 DSP 部分，均不因平台改动。
- **CoreML 编码器**：`resources/models/*.mlmodelc` 仅 macOS 加速用，其他平台忽略即可，不影响功能。

## 本平台改动

**无。** macOS 是基准平台：whisper-cli 是 Mac 二进制、MDX 模型随包放在 `resources/models/`、窗口特效与 dmg 打包都已就绪。

## 与其他平台的差异点（供另两份参考）

| 项 | macOS 现状 | 其他平台需要做的 |
|---|---|---|
| whisper-cli | `resources/bin/whisper_cpp/whisper-cli` + 14 个 `.dylib` | Linux/Windows 换成各自编译的二进制 |
| UVR 模型 | 随包 `resources/models/UVR-MDX-NET-Inst_HQ_3.onnx` | 无需处理，换模型用 `UVR_MODEL_PATH` |
| 窗口特效 | mica/underWindowBackground/Overlay 原生支持 | 忽略或降级 |

## 验证

- `npm run dev` 正常启动、MCP 端点可用。
