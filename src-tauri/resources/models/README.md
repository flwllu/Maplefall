# 第三方模型（非本项目所有）

本目录下的所有模型权重均为**第三方作品**，由本应用原样附带（redistribute），不做修改、不重新训练。本应用不主张任何著作权或所有权，全部权利归各自的训练方与作者。署名、许可与免责的完整说明见项目根目录的 [`THIRD_PARTY_NOTICES.md`](../../../THIRD_PARTY_NOTICES.md)。

| 文件 | 内容 | 训练 / 分发方 | 许可 |
| --- | --- | --- | --- |
| `ggml-large-v3-turbo-q5_0.bin` | Whisper large-v3-turbo 的 ggml q5_0 量化权重，语音转写主模型 | OpenAI Whisper（ggml 量化与转换由 whisper.cpp 项目提供） | MIT |
| `ggml-silero-v5.1.2.bin` | Silero VAD 语音活动检测权重 | snakers4 / silero-vad | MIT |
| `ggml-large-v3-turbo-encoder.mlmodelc/` | Whisper 编码器的 CoreML 转换版，仅 macOS 加速用；**不随仓库分发，需自行用 whisper.cpp 的 `models/generate-coreml-model.sh` 生成** | whisper.cpp 项目基于 OpenAI Whisper 权重的转换产物 | MIT |
| `UVR-MDX-NET-Inst_HQ_3.onnx` | MDX-Net 人声 / 伴奏分离模型 | Ultimate Vocal Remover（Anjok07、aufr33 及贡献者） | MIT |

官方下载地址（源码构建时自行获取，仓库不附带）：

- `ggml-large-v3-turbo-q5_0.bin` — https://huggingface.co/ggerganov/whisper.cpp （镜像：https://hf-mirror.com/ggerganov/whisper.cpp）
- `ggml-silero-v5.1.2.bin` — https://huggingface.co/ggml-org/whisper-vad （镜像：https://hf-mirror.com/ggml-org/whisper-vad）
- `UVR-MDX-NET-Inst_HQ_3.onnx` — https://github.com/TRvlvr/model_repo/releases/tag/all_public_uvr_models （UVR 官方模型仓库）
- `ggml-large-v3-turbo-encoder.mlmodelc/` — 用 whisper.cpp 的 `models/generate-coreml-model.sh` 自行生成

文件校验值（SHA-256）与具体命令见项目根目录 `README.md` 的「模型获取与配置」。

说明：

- 上表中的文件**不是**本项目的代码，按各自上游的 MIT 条款附带；再分发时须保留上游版权声明与许可全文。
- 本项目与上述项目及作者无任何隶属、赞助或官方背书关系，名称仅用于如实标注来源。
- `UVR-MDX-NET-Inst_HQ_3.onnx` 可用环境变量 `UVR_MODEL_PATH` 替换为任意其它 MDX-Net ONNX 模型；删除 `*.onnx` 后重新打包即可得到不含该权重的版本，转写等功能不受影响。
- 模型按「原样」（as is）提供，不附带任何明示或默示担保。输入音频与分离输出的权利归原音频权利人。
