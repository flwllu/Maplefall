#!/bin/zsh
# 双击即可在终端里运行；也可用 ./build.command 启动。
# 不安装任何东西，选择界面用 macOS 自带的 osascript 对话框。

set -u
ROOT="${0:A:h}"
cd "$ROOT" || exit 1

FULL_RESOURCES='[
  "resources/bin/whisper_cpp/*.dylib",
  "resources/bin/whisper_cpp/whisper-cli",
  "resources/models/*.bin",
  "resources/models/*.onnx",
  "resources/models/*.mlmodelc/**/*",
  "resources/bin/ffmpeg/*",
  "resources/licenses/*"
]'
SLIM_RESOURCES='[
  "resources/bin/whisper_cpp/*.dylib",
  "resources/bin/whisper_cpp/whisper-cli",
  "resources/models/*.bin",
  "resources/models/*.onnx",
  "resources/bin/ffmpeg/*",
  "resources/licenses/*"
]'

MENU_ITEMS=(
  "完整包（带 CoreML 加速，约 1.7 GB）"
  "精简包（不带 CoreML 编码器，约 640 MB）"
  "打开产物目录"
  "退出"
)

pick_dialog() {
  osascript <<'APPLE'
set choiceList to {"完整包（带 CoreML 加速，约 1.7 GB）", "精简包（不带 CoreML 编码器，约 640 MB）", "打开产物目录", "退出"}
set chosen to choose from list choiceList with title "Whisper Studio 打包" with prompt "选择打包方案：" OK button name "开始" cancel button name "取消"
if chosen is false then
	return "退出"
end if
return item 1 of chosen
APPLE
}

confirm_dialog() {
  osascript -e "display dialog \"$1\" buttons {\"取消\", \"继续\"} default button \"取消\"" >/dev/null 2>&1
}

notice_dialog() {
  osascript -e "display dialog \"$1\" buttons {\"好\"} default button \"好\"" >/dev/null 2>&1
}

pick_choice() {
  if [[ "$(uname -s)" == "Darwin" ]] && command -v osascript >/dev/null 2>&1; then
    local picked
    picked="$(pick_dialog 2>/dev/null)"
    if [[ -n "$picked" ]]; then
      printf '%s' "$picked"
      return 0
    fi
    return 1
  fi
  print -r -- "请选择打包方案："
  select item in "${MENU_ITEMS[@]}"; do
    [[ -n "$REPLY" ]] || return 1
    printf '%s' "$item"
    return 0
  done
  return 1
}

do_build() {
  local label="$1"
  local resources="$2"
  local override="$ROOT/src-tauri/target/build-resources.$$.json"

  if [[ ! -x "$ROOT/node_modules/.bin/tauri" ]]; then
    print -u2 -- "错误：找不到本地 Tauri CLI，请先在项目目录安装依赖。"
    notice_dialog "找不到本地 Tauri CLI，打包已取消。"
    return 1
  fi

  mkdir -p "${override:h}"
  printf '{"bundle":{"resources":%s}}\n' "$resources" > "$override"

  print -r -- "开始打包：$label"
  npx tauri build --config "$override"
  local status=$?
  rm -f "$override"

  if (( status != 0 )); then
    print -u2 -- "打包失败，退出码 $status"
    notice_dialog "打包失败（退出码 $status），请看终端日志。"
    return 1
  fi

  print -r -- "打包完成，产物："
  ls -lh "$ROOT/src-tauri/target/release/bundle/dmg/"*.dmg 2>/dev/null
  notice_dialog "打包完成，请看终端里的产物路径。"
}

while true; do
  choice="$(pick_choice)" || break

  case "$choice" in
    "完整包"*)
      do_build "完整包（含 CoreML 加速）" "$FULL_RESOURCES"
      ;;
    "精简包"*)
      if [[ ! -f "$ROOT/src-tauri/resources/bin/whisper_cpp/.fallback-ready" ]]; then
        print -u2 -- "通用版 CLI 尚未编译安装，暂不能打精简包。"
        notice_dialog "通用版 CLI 尚未编译安装，暂不能打精简包；请先用完整包。"
        continue
      fi
      do_build "精简包（不含 CoreML 编码器，自动回落到 Metal + CPU）" "$SLIM_RESOURCES"
      ;;
    "打开产物目录")
      open "$ROOT/src-tauri/target/release/bundle/dmg" 2>/dev/null || \
        print -r -- "产物目录：$ROOT/src-tauri/target/release/bundle/dmg"
      ;;
    *)
      break
      ;;
  esac
done
