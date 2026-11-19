# 随包许可文件

本目录随安装包一起分发，对应项目根目录的 `THIRD_PARTY_NOTICES.md`。

| 文件 | 说明 |
| --- | --- |
| `THIRD_PARTY_NOTICES.md` | 第三方组件清单、许可证、来源，以及 FFmpeg 与 MDX 模型的再分发义务（英文） |
| `THIRD_PARTY_NOTICES.zh.md` | 同上，中文版 |
| `GPL-2.0.txt` | GNU General Public License version 2 全文，随包的 FFmpeg / ffprobe 二进制适用 |

## FFmpeg 对应源码（GPL-2.0-or-later）

随包的 `ffmpeg` / `ffprobe` 是静态构建的 7.1.1，构建参数含 `--enable-gpl`，
并链接了 libx264、libx265 等 GPL 组件。再分发时须提供对应源码的获取方式：

- FFmpeg 7.1.1：<https://ffmpeg.org/download.html>，或 <https://git.ffmpeg.org/ffmpeg.git> 的 `n7.1.1` 标签
- 外部库：x264 <https://code.videolan.org/videolan/x264>、x265 <https://bitbucket.org/multicoreware/x265_git> 等，
  具体启用了哪些以 `ffmpeg -version` 输出中的 `configuration:` 行为准
- 上述地址不可用时，可到本项目的代码托管页面提交 issue 索取对应源码（含所用外部库源码与本次构建配置）。
  该要约自本版本发布之日起**三年内有效**，除实际分发成本外不收取费用

## 其它组件的上游许可

whisper.cpp、Silero VAD、UVR-MDX-NET 模型均以 MIT 分发，版权归各自作者。
许可证原文见各自上游仓库的 `LICENSE`：

- whisper.cpp：<https://github.com/ggml-org/whisper.cpp>
- silero-vad：<https://github.com/snakers4/silero-vad>
- Ultimate Vocal Remover：<https://github.com/Anjok07/ultimatevocalremovergui>
- OpenAI Whisper（`ggml-large-v3-turbo` 权重来源）：<https://github.com/openai/whisper>
