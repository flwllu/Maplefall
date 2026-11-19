# 第三方组件与许可证声明

枫落工具本体以 MIT 许可证发布（见 `LICENSE`，Copyright © 2026 flwllu）。本文件列出随应用分发、或运行时所依赖的第三方组件及其许可证。

[<u>English</u>](THIRD_PARTY_NOTICES.md) · **中文**

打包分发时请把本文件一并附上（macOS `.app` 内可放在 `Contents/Resources/`）。

> 维护提醒：`src-tauri/resources/licenses/THIRD_PARTY_NOTICES.zh.md` 是本文件的随包副本（英文版对应 `THIRD_PARTY_NOTICES.md`），已由 `bundle.resources` 打进安装包。修改本文件后请同步覆盖那份副本，否则随包声明会与仓库不一致。

## 一、随包分发的组件

`resources/models/` 下的权重文件**全部是第三方作品**，不是本项目的代码。随安装包（Release 的 dmg）分发的 3 个为 `ggml-large-v3-turbo-q5_0.bin`、`ggml-silero-v5.1.2.bin`、`UVR-MDX-NET-Inst_HQ_3.onnx`；仓库本身不包含这些模型文件，从源码构建时按 README 的「模型获取与配置」从上游官方地址获取。`ggml-large-v3-turbo-encoder.mlmodelc` 既不随仓库也不随安装包，由需要者自行用 whisper.cpp 上游脚本生成。逐文件的来源、许可与免责见随包文件 [`src-tauri/resources/models/README.md`](src-tauri/resources/models/README.md)。

| 组件 | 用途 | 许可证 | 来源 |
| --- | --- | --- | --- |
| FFmpeg / ffprobe（静态构建 7.1.1，`--enable-gpl`，含 libx264 / libx265） | 媒体信息、标签、封面、格式转换 | GPL-2.0-or-later | https://ffmpeg.org |
| whisper.cpp（含 `whisper-cli`、`libwhisper`、`libggml*`） | 语音转写推理 | MIT | https://github.com/ggml-org/whisper.cpp |
| ggml | whisper.cpp 的张量/后端库 | MIT | 随 whisper.cpp 分发 |
| ggml-large-v3-turbo-q5_0（量化权重） | 转写模型 | MIT（OpenAI Whisper 权重） | https://github.com/openai/whisper |
| ggml-silero-v5.1.2 | Silero VAD 语音活动检测 | MIT | https://github.com/snakers4/silero-vad |
| UVR-MDX-NET-Inst_HQ_3.onnx | 人声/伴奏分离模型（UVR MDX-Net） | MIT（版权归 UVR 项目，详见第四节） | https://github.com/Anjok07/ultimatevocalremovergui |

MIT 许可证要求：再分发时保留原版权声明与许可全文。

模型权重的来源、署名、免责与可移除方式见 **第四节「MDX 分离模型署名与声明」**。

## 二、编译进应用的 Rust 依赖

主要依赖及其许可证（完整列表可由 `cargo license` 生成）：

| 依赖 | 许可证 |
| --- | --- |
| tauri、tauri-plugin-dialog | MIT OR Apache-2.0 |
| serde、serde_json | MIT OR Apache-2.0 |
| ort（ONNX Runtime 绑定） | MIT |
| realfft | MIT OR Apache-2.0 |
| hound | Apache-2.0 |
| symphonia（音频解码） | MPL-2.0 |

说明：

- **MPL-2.0 是文件级弱 copyleft**。以依赖形式链接使用不影响本项目的 MIT 发布；仅当你修改了 symphonia 自身的源文件时，才需要公开被修改的那部分文件。
- 其余依赖均为 MIT / Apache-2.0 / BSD / ISC / Zlib / Unicode 等宽松许可证，不产生传染性义务。
- 本项目链接的 Rust 依赖里没有任何 GPL / AGPL / SSPL 代码。随包的 FFmpeg 二进制是独立的 GPL 可执行文件，以子进程调用，不进入本项目代码，义务见第三节。

## 三、FFmpeg 再分发义务（GPL-2.0-or-later）

应用随包分发的是静态链接的 FFmpeg / ffprobe 7.1.1（构建参数含 `--enable-gpl`，内嵌 libx264、libx265 等 GPL 组件），以子进程方式调用，不与本项目代码链接。该二进制以 **GPL-2.0-or-later** 发布，因此再分发时必须满足：

1. 附上 GPL 全文（见 https://www.gnu.org/licenses/old-licenses/gpl-2.0.html 或发行包内的 `licenses/`）。
2. 提供**对应源码**的获取方式：FFmpeg 源码可从 https://ffmpeg.org/download.html 取得对应 7.1.1 版本；所用外部库（x264、x265 等）源码以各自上游仓库为准。若不便随包附带源码，须在文档中给出有效期不少于三年的**书面要约**（written offer），承诺向任何第三方提供对应源码。

   本项目据此给出的书面要约为：本安装包内的 FFmpeg / ffprobe 为对应版本的**未修改预编译静态构建**，其源码可直接从上述公开地址取得（外部库源码以各自上游为准，构建参数见 `ffmpeg -version` 输出中的 `configuration:` 行）。若上述地址不可用，可到本项目的代码托管页面提交 issue 索取完整对应源码；该要约自对应版本发布之日起三年内有效，除实际分发成本外不收取任何费用。
3. 保留原版权声明，不额外限制接收方对 GPL 组件的再分发。

本项目**自身代码**仍为 MIT，与 FFmpeg 二进制之间是进程调用关系，不构成衍生作品；上述义务仅适用于 FFmpeg 二进制本身。

仓库（源码）里**不包含** `resources/bin/` 下的任何二进制，因此仓库整体只有 MIT 一种许可；上述 GPL 义务只在分发安装包（dmg）时产生。

## 四、MDX 分离模型署名与声明

### 4.1 模型信息

| 项 | 内容 |
| --- | --- |
| 文件名 | `UVR-MDX-NET-Inst_HQ_3.onnx`（约 64 MB） |
| 用途 | 人声 / 伴奏分离（instrumental 分支，人声由「原混音 − 伴奏」推导） |
| 训练与分发方 | Ultimate Vocal Remover 项目（Anjok07、aufr33 及贡献者） |
| 上游地址 | https://github.com/Anjok07/ultimatevocalremovergui |
| 上游许可 | MIT（UVR 发行版整体以 MIT 发布，模型文件随其发行版分发） |

### 4.2 权利归属

本应用**不主张**对该模型权重文件的任何著作权、所有权或独占权利。权重文件及其训练成果的相关权利归 Ultimate Vocal Remover 项目及其作者所有。本应用仅作为整体功能的一部分，按上游的 MIT 条款原样附带（redistribute）该文件，不修改、不重新训练、不注入额外数据。

为确保 MIT 的「保留版权声明与许可全文」义务得到满足，发布前请把上游 `LICENSE` 原文放到 `licenses/UVR-LICENSE.txt`（从 https://github.com/Anjok07/ultimatevocalremovergui 获取）。若该文件缺失，以本文件中的引用与上游仓库为准。

### 4.3 致谢

人声分离功能完全建立在 Ultimate Vocal Remover 的 MDX-Net 实现与模型之上。特别感谢 **Anjok07**、**aufr33** 及 UVR 全体贡献者——没有他们训练的模型与公开的分离开源实现，本功能不存在。

### 4.4 无隶属关系

本项目是独立项目，与 Ultimate Vocal Remover 项目及模型作者之间**不存在**任何隶属、赞助、授权代理或官方背书关系。文中出现的 "UVR"、"Ultimate Vocal Remover"、模型名等仅用于如实标注来源与致谢。

### 4.5 免责与输出物权利

模型按「**原样**」（as is）提供，不附带任何明示或默示担保，包括但不限于适销性、特定用途适用性与不侵权担保。分离结果的音质、稳定性与可用性由使用者自行判断并承担风险。

本应用不对输入音频、分离输出的音轨主张任何权利；该类内容的权利始终归原音频的权利人。使用者应确保其对所处理音频拥有合法使用权。

### 4.6 可替换、可移除

模型与代码无强耦合：设置 `UVR_MODEL_PATH` 可指向任意其它 MDX-Net ONNX 模型；删除 `resources/models/*.onnx` 后重新打包即可得到一个不含该权重的版本，转写、格式转换等功能不受影响。

## 五、打包注意事项

- `src-tauri/tauri.conf.json` 的 `bundle.resources` 指定了随包资源：`resources/bin/whisper_cpp/**`（whisper-cli 与动态库）、`resources/bin/ffmpeg/*`（静态 ffmpeg / ffprobe）、`resources/models/*.bin`（whisper/VAD 权重）、`resources/models/*.onnx`（MDX 分离模型）。
- 默认的精简包体积约为 whisper 模型 550 MB + MDX 64 MB + 静态 FFmpeg 96 MB + 其它二进制 47 MB，dmg 约 640 MB。
- 当前随包的 `whisper-cli` 以 `WHISPER_COREML_ALLOW_FALLBACK` 构建（见 `build.command` 检查的 `resources/bin/whisper_cpp/.fallback-ready`），缺少 `ggml-large-v3-turbo-encoder.mlmodelc` 时会回落到 Metal + CPU，因此默认不含这 1.2 GB。若换成不带该开关的上游构建，则编码器必须随包，否则 whisper-cli 会以退出码 3 失败。
- CoreML 编码器需要者自行用 whisper.cpp 的 `models/generate-coreml-model.sh` 生成并放进 `resources/models/`，仓库不附带。
- 各平台的 `bundle.resources` 分别写在 `tauri.conf.json`（macOS）、`tauri.linux.conf.json`、`tauri.windows.conf.json` 里，换平台打包时资源 glob 会跟着换。
- 若需减小安装包体积，可把 MDX 模型改为应用内首次使用时下载，或让用户自行导入（`UVR_MODEL_PATH` 已支持）；FFmpeg 也可改为调用系统安装（删除 `resources/bin/ffmpeg/` 后代码会自动退回 PATH）。
