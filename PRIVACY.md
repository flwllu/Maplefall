# Privacy

Maplefall is a local desktop tool. All processing happens on your machine, and no user data is collected or uploaded anywhere.

**English** · [<u>简体中文</u>](PRIVACY.zh.md)

## 1. Local processing

- Nothing passes through a server: transcription, vocal separation, format conversion, tag and cover editing, and renaming all run locally.
- There is no account system, no telemetry, no crash reporting, no usage analytics, and no ad SDK.
- The app itself makes no network requests. The only listener is the built-in MCP server, bound to `127.0.0.1:17321` (loopback only); it disappears when the app closes and never accepts outside connections. Traffic appears only when you connect a client to it yourself.

## 2. Where data lives

| Location | Contents | Notes |
| --- | --- | --- |
| App data directory (macOS: `~/Library/Application Support/com.whisperstudio.desktop`) | `settings.json`, `tasks.json` — settings and your own task records, including local paths of processed files | Stays on this machine |
| App cache directory | Intermediate artifacts such as separation results | Safe to delete; recomputed when needed |
| App log directory | `runs/*.log` | Written only after you enable "Debug log"; off by default |

None of these files leave your device; remove them along with the app when you uninstall.

## 3. About logs

Debug logs are off by default. Once enabled, each run writes its own `.log` file containing startup arguments, whisper-cli output lines and failure reasons — which may include local file paths. Whether to enable it and when to delete the files is up to you.

## 4. The files you process

Audio, video, subtitles and metadata are read and written locally and are never sent anywhere. When you attach a third-party MCP client, data travels over the loopback address only; whether that client forwards it afterwards, and where to, is down to the client itself and outside this app's control.

## 5. Bundled third-party components

FFmpeg, whisper.cpp and the model weights shipped with the app are third-party works. Their sources, licenses and disclaimers are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`src-tauri/resources/models/README.md`](src-tauri/resources/models/README.md). None of them contains telemetry code.

## 6. Changes

Any update to this notice ships with a new version of the app.
