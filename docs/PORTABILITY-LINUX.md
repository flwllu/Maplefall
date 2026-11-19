# 三平台方案 · Linux

> 三份文档各写一个平台，互不混写。共用约定与 macOS 基准见 `PORTABILITY-MACOS.md`。
> 硬约束：所有改动都用平台隔离，macOS 的代码与运行行为零影响。

## 现状

代码与打包配置已就绪，**二进制尚未就位**：仓库内 `src-tauri/resources/bin/whisper_cpp/` 目前只有 macOS 的 `whisper-cli` 与 `*.dylib`，没有 `linux-x64/`、`linux-arm64/`。补齐之前只能编译、不能完成转写。

## 需要的目录结构

```
src-tauri/resources/bin/whisper_cpp/
  whisper-cli + *.dylib     macOS（原有）
  linux-x64/                whisper-cli + libwhisper.so* + libggml*.so*
  linux-arm64/              whisper-cli + libwhisper.so* + libggml*.so*
  windows/                  （见 PORTABILITY-WINDOWS.md）
```

二进制来源：whisper.cpp 官方 release 的 Linux 构建（MIT），本项目不代为下载。

## 代码侧（已落地）

- `whisper_cli_path()` 统一在 `src-tauri/src/tools.rs`，主程序与 MCP 共用：
  - x86_64 → `bin/whisper_cpp/linux-x64/whisper-cli`
  - aarch64 → `bin/whisper_cpp/linux-arm64/whisper-cli`
- `engine.rs` 的 `build_command()` 在 Linux 上把 whisper-cli 所在目录追加进 `LD_LIBRARY_PATH`，避免上游构建没有 `$ORIGIN` rpath 时找不到同目录的 `.so`。
- `tauri.linux.conf.json` 覆盖 `bundle.targets`（deb / rpm / appimage）、`icon` 与 `bundle.resources`。

## 人声分离（可选）

`mdx.rs` 的 `model_path()` 支持环境变量 `UVR_MODEL_PATH`；设成 onnx 绝对路径即可。`separate=false` 时不触发。

## 资源目录（可选）

`resources_dir()` 支持 `WHISPER_STUDIO_RESOURCES` 显式指定资源目录；debug 构建在同机运行时无需设置。

## 验证清单（补齐二进制后逐项回归）

- `cargo build` / `npm run dev` 编译通过
- MCP `initialize` 返回 200（端口 17321）
- `transcribe_audio` 传 `separate=false` 返回 text / srt
- 界面窗口能显示
