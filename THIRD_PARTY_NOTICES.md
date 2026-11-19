# Third-Party Components and Licenses

Maplefall itself is released under the MIT license (see `LICENSE`, Copyright © 2026 flwllu). This document lists every third-party component that ships with the app or is relied on at runtime, together with its license.

**English** · [<u>简体中文</u>](THIRD_PARTY_NOTICES.zh.md)

Ship this file with any distributed build (inside a macOS `.app` it can live in `Contents/Resources/`).

> Maintenance note: `src-tauri/resources/licenses/THIRD_PARTY_NOTICES.md` and its `.zh.md` counterpart are the bundled copies of this file, packed into the installer via `bundle.resources`. Overwrite those copies whenever this file changes, otherwise the shipped notice drifts from the repo.

## 1. Components bundled with the app

Every weight file under `resources/models/` is a **third-party work**, not code from this project. The installer (the dmg attached to a Release) ships three of them: `ggml-large-v3-turbo-q5_0.bin`, `ggml-silero-v5.1.2.bin` and `UVR-MDX-NET-Inst_HQ_3.onnx`. The repository contains none of these model files — a source build fetches them from the official upstream addresses listed under "Models: where to get them" in the README. `ggml-large-v3-turbo-encoder.mlmodelc` ships neither in the repo nor in the installer; anyone who wants it generates it with whisper.cpp's upstream script. Per-file provenance, license and disclaimer are in the bundled [`src-tauri/resources/models/README.md`](src-tauri/resources/models/README.md).

| Component | Purpose | License | Source |
| --- | --- | --- | --- |
| FFmpeg / ffprobe (static build 7.1.1, `--enable-gpl`, with libx264 / libx265) | Media info, tags, covers, format conversion | GPL-2.0-or-later | https://ffmpeg.org |
| whisper.cpp (with `whisper-cli`, `libwhisper`, `libggml*`) | Speech transcription inference | MIT | https://github.com/ggml-org/whisper.cpp |
| ggml | Tensor and backend library used by whisper.cpp | MIT | Distributed with whisper.cpp |
| ggml-large-v3-turbo-q5_0 (quantized weights) | Transcription model | MIT (OpenAI Whisper weights) | https://github.com/openai/whisper |
| ggml-silero-v5.1.2 | Silero VAD voice activity detection | MIT | https://github.com/snakers4/silero-vad |
| UVR-MDX-NET-Inst_HQ_3.onnx | Vocal / instrumental separation model (UVR MDX-Net) | MIT (rights held by the UVR project — see section 4) | https://github.com/Anjok07/ultimatevocalremovergui |

The MIT license requires that the original copyright notice and the full license text be kept on redistribution.

Provenance, attribution, disclaimer and removal instructions for the model weights are in **section 4, "MDX separation model attribution and notice"**.

## 2. Rust dependencies compiled into the app

Main dependencies and their licenses (run `cargo license` for the full list):

| Dependency | License |
| --- | --- |
| tauri, tauri-plugin-dialog | MIT OR Apache-2.0 |
| serde, serde_json | MIT OR Apache-2.0 |
| ort (ONNX Runtime bindings) | MIT |
| realfft | MIT OR Apache-2.0 |
| hound | Apache-2.0 |
| symphonia (audio decoding) | MPL-2.0 |

Notes:

- **MPL-2.0 is a file-level weak copyleft.** Using it as a linked dependency does not affect this project's MIT release; only if you modify symphonia's own source files do you have to publish those modified files.
- The remaining dependencies use permissive licenses (MIT / Apache-2.0 / BSD / ISC / Zlib / Unicode) and impose no copyleft obligations.
- None of the linked Rust dependencies contains GPL / AGPL / SSPL code. The bundled FFmpeg binary is a separate GPL executable invoked as a child process and does not enter this project's code; its obligations are in section 3.

## 3. FFmpeg redistribution obligations (GPL-2.0-or-later)

The app bundles a statically linked FFmpeg / ffprobe 7.1.1 (built with `--enable-gpl`, embedding GPL components such as libx264 and libx265). It is invoked as a child process and is not linked against this project's code. The binary is released under **GPL-2.0-or-later**, so redistribution must satisfy:

1. Include the full GPL text (see https://www.gnu.org/licenses/old-licenses/gpl-2.0.html, or the `licenses/` folder in the distribution).
2. Provide a way to obtain the **corresponding source**: FFmpeg source for 7.1.1 is available at https://ffmpeg.org/download.html, and the bundled external libraries (x264, x265, …) follow their own upstream repositories. If shipping the source alongside is impractical, the documentation must contain a **written offer** valid for at least three years, promising the corresponding source to any third party.

   The written offer given by this project on that basis: the FFmpeg / ffprobe in this installer are **unmodified prebuilt static builds** of the corresponding version, and their source is obtainable directly from the public addresses above (external libraries follow their own upstreams; the build configuration is the `configuration:` line in `ffmpeg -version` output). If those addresses become unavailable, open an issue on this project's code hosting page to request the complete corresponding source. The offer is valid for three years from the release date of the corresponding version and costs nothing beyond the actual cost of distribution.
3. Keep the original copyright notices and impose no further restrictions on recipients' redistribution of the GPL components.

This project's **own code** remains MIT. It relates to the FFmpeg binary only through process invocation and forms no derivative work; the obligations above apply to the FFmpeg binary alone.

The repository (source) contains **no** binaries from `resources/bin/`, so the repository as a whole carries MIT and nothing else. The GPL obligations above arise only when an installer (dmg) is distributed.

## 4. MDX separation model attribution and notice

### 4.1 Model information

| Item | Details |
| --- | --- |
| File name | `UVR-MDX-NET-Inst_HQ_3.onnx` (about 64 MB) |
| Purpose | Vocal / instrumental separation (the instrumental branch; vocals are derived as "original mix − instrumental") |
| Trained and distributed by | The Ultimate Vocal Remover project (Anjok07, aufr33 and contributors) |
| Upstream | https://github.com/Anjok07/ultimatevocalremovergui |
| Upstream license | MIT (the UVR distribution as a whole is MIT; the model file ships with it) |

### 4.2 Ownership

This app claims **no** copyright, ownership or exclusive right over the model weights. Rights in the file and in the trained result belong to the Ultimate Vocal Remover project and its authors. As part of an integrated feature, this app simply redistributes the file unmodified under the upstream MIT terms — no modification, no retraining, no additional data injected.

To satisfy MIT's "keep the copyright notice and full license text" requirement, place the upstream `LICENSE` in `licenses/UVR-LICENSE.txt` before release (fetch it from https://github.com/Anjok07/ultimatevocalremovergui). If that file is missing, the reference here and the upstream repository govern.

### 4.3 Credits

Vocal separation is built entirely on Ultimate Vocal Remover's MDX-Net implementation and models. Our thanks in particular to **Anjok07**, **aufr33** and all UVR contributors — without the models they trained and the open separation implementation they published, this feature would not exist.

### 4.4 No affiliation

This is an independent project with **no** affiliation, sponsorship, agency or official endorsement from the Ultimate Vocal Remover project or the model authors. "UVR", "Ultimate Vocal Remover" and the model names appear only to state provenance and give credit.

### 4.5 Disclaimer and rights in outputs

The model is provided "**as is**", without any express or implied warranty, including but not limited to merchantability, fitness for a particular purpose and non-infringement. Users judge the quality, stability and usefulness of separation results themselves and bear the risk.

This app claims no rights over input audio or over the separated stems; rights in that content remain with the owners of the original audio. Users must make sure they are entitled to process the audio they feed in.

### 4.6 Replaceable and removable

The model is loosely coupled to the code: `UVR_MODEL_PATH` can point at any other MDX-Net ONNX model, and deleting `resources/models/*.onnx` before repackaging yields a build without the weights — transcription, format conversion and the other features keep working.

## 5. Packaging notes

- `bundle.resources` in `src-tauri/tauri.conf.json` lists what travels with the app: `resources/bin/whisper_cpp/**` (whisper-cli and its dylibs), `resources/bin/ffmpeg/*` (static ffmpeg / ffprobe), `resources/models/*.bin` (whisper / VAD weights) and `resources/models/*.onnx` (MDX separation model).
- The default slim package is roughly whisper model 550 MB + MDX 64 MB + static FFmpeg 96 MB + other binaries 47 MB, giving a dmg of about 640 MB.
- The bundled `whisper-cli` is built with `WHISPER_COREML_ALLOW_FALLBACK` (checked by `build.command` via `resources/bin/whisper_cpp/.fallback-ready`), so it falls back to Metal + CPU when `ggml-large-v3-turbo-encoder.mlmodelc` is absent — which is why that 1.2 GB is not included by default. A stock upstream build without that flag requires the encoder to be bundled, otherwise whisper-cli exits with code 3.
- The CoreML encoder is generated by whoever needs it, using whisper.cpp's `models/generate-coreml-model.sh`, and placed in `resources/models/` — the repo does not ship it.
- `bundle.resources` for each platform lives in `tauri.conf.json` (macOS), `tauri.linux.conf.json` and `tauri.windows.conf.json`; the resource globs follow the platform you package on.
- To shrink the installer further, download the MDX model on first use or let users import their own (`UVR_MODEL_PATH` already supports it); FFmpeg can also fall back to a system install (delete `resources/bin/ffmpeg/` and the code automatically uses `ffmpeg` from `PATH`).
