#!/usr/bin/env python3
"""在当前系统上打包「音律工具箱」。

macOS   生成 dist/MusicAssistant.app（可选 --dmg 生成安装镜像）
Windows 生成 dist/MusicAssistant/MusicAssistant.exe 以及 zip 压缩包

转码依赖 PyAV：pip 安装的 PyAV 自带 FFmpeg 动态库，
打包时会一并收集，不依赖系统里的 ffmpeg 可执行文件。

用法：
    python build.py            # 打包
    python build.py --dmg      # macOS 额外生成 dmg
"""

import argparse
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "build_assets"
APP_NAME = "MusicAssistant"
DISPLAY_NAME = "音律工具箱"

EXCLUDES = [
    "tkinter",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "PySide6.QtSql",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtNetworkAuth",
]


def _prepare_icons():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    from app.icons import logo_image

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    ASSETS.mkdir(parents=True, exist_ok=True)
    iconset = ASSETS / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    sizes = {
        16: ["icon_16x16.png"],
        24: [],
        32: ["icon_16x16@2x.png", "icon_32x32.png"],
        64: ["icon_32x32@2x.png"],
        128: ["icon_128x128.png"],
        256: ["icon_128x128@2x.png", "icon_256x256.png"],
        512: ["icon_256x256@2x.png", "icon_512x512.png"],
        1024: ["icon_512x512@2x.png"],
    }
    png_by_size = {}
    for size, names in sizes.items():
        target = ASSETS / f"logo_{size}.png"
        logo_image(size).save(str(target), "PNG")
        png_by_size[size] = target
        for name in names:
            shutil.copyfile(target, iconset / name)

    result = {"png": png_by_size}
    if sys.platform == "darwin" and shutil.which("iconutil"):
        icns = ASSETS / "icon.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
            check=True)
        result["icns"] = icns
    if sys.platform == "win32":
        ico = ASSETS / "icon.ico"
        _write_ico(
            [png_by_size[size] for size in (16, 24, 32, 48, 64, 128, 256)],
            ico)
        result["ico"] = ico
    return result


def _write_ico(png_paths, target):
    images = []
    for path in png_paths:
        data = path.read_bytes()
        size = int(path.stem.split("_")[-1])
        images.append((size, data))

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    payload = b""
    for size, data in images:
        width = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", width, width, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data
    target.write_bytes(header + entries + payload)


def build(dmg=False, skip_icons=False, universal2=False):
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先执行：pip install pyinstaller")
        return 1

    icons = {} if skip_icons else _prepare_icons()

    args = [
        sys.executable, "-m", "PyInstaller",
        str(ROOT / "music_renamer.py"),
        "--name", APP_NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
        "--collect-submodules", "mutagen",
        "--collect-all", "av",
    ]
    for module in EXCLUDES:
        args += ["--exclude-module", module]

    if "icns" in icons:
        args += ["--icon", str(icons["icns"])]
        args += ["--osx-bundle-identifier", "com.musicassistant.app"]
        args += ["--hidden-import", "objc", "--hidden-import", "AppKit"]
        if universal2:
            args += ["--target-arch", "universal2"]
    elif "ico" in icons:
        args += ["--icon", str(icons["ico"])]

    print("开始打包（已内置 PyAV / FFmpeg 动态库）…")
    subprocess.run(args, check=True, cwd=ROOT)

    if sys.platform == "darwin":
        app_bundle = ROOT / "dist" / f"{APP_NAME}.app"
        if not app_bundle.exists():
            print("打包失败：没有找到 .app")
            return 1
        _patch_plist(app_bundle)
        print(f"\n完成：{app_bundle}")
        if dmg:
            _make_dmg(app_bundle)
    elif sys.platform == "win32":
        folder = ROOT / "dist" / APP_NAME
        archive = ROOT / "dist" / f"{APP_NAME}-windows.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in folder.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(folder.parent))
        print(f"\n完成：{folder / (APP_NAME + '.exe')}")
        print(f"压缩包：{archive}")
    else:
        print(f"\n完成：{ROOT / 'dist' / APP_NAME}")
    return 0


def _patch_plist(app_bundle):
    plist_path = app_bundle / "Contents" / "Info.plist"
    with open(plist_path, "rb") as handle:
        data = plistlib.load(handle)
    data["CFBundleDisplayName"] = DISPLAY_NAME
    data["CFBundleName"] = DISPLAY_NAME
    data["CFBundleShortVersionString"] = "3.0.0"
    data["CFBundleVersion"] = "3.0.0"
    data["NSHighResolutionCapable"] = True
    data["LSApplicationCategoryType"] = "public.app-category.music"
    data["NSHumanReadableCopyright"] = "Media Toolbox"
    data["NSSupportsAutomaticGraphicsSwitching"] = True
    with open(plist_path, "wb") as handle:
        plistlib.dump(data, handle)


def _make_dmg(app_bundle):
    stage = ROOT / "build" / "dmg"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copytree(app_bundle, stage / app_bundle.name, symlinks=True)
    (stage / "Applications").symlink_to("/Applications")

    dmg_path = ROOT / "dist" / f"{APP_NAME}.dmg"
    if dmg_path.exists():
        dmg_path.unlink()
    subprocess.run([
        "hdiutil", "create", "-volname", DISPLAY_NAME,
        "-srcfolder", str(stage), "-ov", "-format", "UDZO",
        str(dmg_path),
    ], check=True)
    print(f"安装镜像：{dmg_path}")


def main():
    parser = argparse.ArgumentParser(description="打包音律工具箱")
    parser.add_argument("--dmg", action="store_true", help="macOS 生成 dmg")
    parser.add_argument("--skip-icons", action="store_true", help="跳过图标生成")
    parser.add_argument(
        "--universal2", action="store_true",
        help="macOS 生成 Intel + Apple Silicon 通用包（需 universal2 Python）")
    options = parser.parse_args()
    if sys.platform not in ("darwin", "win32"):
        print("提示：macOS / Windows 上才能打包对应平台的应用。")
    sys.exit(build(
        dmg=options.dmg, skip_icons=options.skip_icons,
        universal2=options.universal2))


if __name__ == "__main__":
    main()
