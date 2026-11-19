# 三平台方案 · Windows

> 三份文档各写一个平台，互不混写。共用约定与 macOS 基准见 `PORTABILITY-MACOS.md`。
> 硬约束：所有改动都用平台隔离，macOS 的代码与运行行为零影响。

## 现状

代码与打包配置已就绪，**二进制尚未就位**：仓库内 `src-tauri/resources/bin/whisper_cpp/` 目前只有 macOS 的 `whisper-cli` 与 `*.dylib`，没有 `windows/` 目录。在补齐 Windows 二进制之前，本平台只能编译、不能完成转写。

## 需要的目录结构

```
src-tauri/resources/bin/whisper_cpp/
  whisper-cli + *.dylib     macOS（原有）
  windows/                  whisper-cli.exe + ggml*.dll + whisper.dll
  linux-x64/                （见 PORTABILITY-LINUX.md）
  linux-arm64/
```

`whisper-cli.exe` 只在自身目录里找 DLL，因此 DLL 必须与它同目录。whisper-cli 运行必需的 DLL：`whisper.dll`、`ggml.dll`、`ggml-base.dll`、`ggml-cpu.dll`；`SDL2.dll`、`llama.dll`、`parakeet.dll` 属其它示例程序，可剔除。

二进制来源：whisper.cpp 官方 release 的 `whisper-bin-x64.zip`（MIT）。本项目不代为下载，放入上述目录后即可运行。

## 代码侧（已落地）

1. `whisper_cli_path()` 统一放在 `src-tauri/src/tools.rs`，主程序与 MCP 共用；Windows 分支返回 `bin/whisper_cpp/windows/whisper-cli.exe`。
2. `mcp_server.rs` 的 `mcp_binary_name()` 在 Windows 上返回 `whisper-studio-mcp.exe`。
3. `mcp.rs` 的 `settings_path()` 在 Windows 上用 `%APPDATA%`，不再依赖 `HOME`。
4. `tauri.windows.conf.json` 覆盖 `bundle.targets`（msi / nsis）、`icon`、`bundle.resources`（`windows/*`、`ffmpeg/*.exe`、`models/*.bin`、`models/*.onnx`），并把窗口设为不透明。

## 人声分离（可选）

`mdx.rs` 的 `model_path()` 支持 `UVR_MODEL_PATH`，Windows 上指向 onnx 绝对路径即可；不分离时不触发。

## 验证清单（补齐二进制后逐项回归）

- `cargo build` / `npm run dev` 编译通过
- MCP `initialize` 返回 200，且 `transcribe_audio` 能真正调用（验证 `.exe` 与 DLL 解析）
- `transcribe_audio` 传 `separate=false` 返回 text / srt
- 界面窗口能显示
