"""各平台原生窗口效果：macOS Liquid Glass / Windows 11 Mica。

所有实现均为可选增强，失败时自动回退到自绘玻璃，不影响主流程。
"""

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass


@dataclass
class WindowEffects:
    native_glass: bool = False
    platform: str = "generic"


def apply_window_effects(window):
    if sys.platform == "darwin":
        return _apply_macos(window)
    if sys.platform == "win32":
        return _apply_windows(window)
    return WindowEffects()


def set_corner_radius(window, radius):
    """窗口最大化时把原生玻璃圆角归零。"""
    view = getattr(window, "_native_glass_view", None)
    if view is None:
        return
    try:
        view.setCornerRadius_(float(radius))
    except Exception:
        pass


# =========================== macOS ===========================

def _apply_macos(window):
    try:
        import objc
        import AppKit

        nswindow = objc.objc_object(c_void_p=int(window.winId())).window()
        if nswindow is None:
            return WindowEffects(False, "macos")

        AppKit.NSApplication.sharedApplication().setAppearance_(
            AppKit.NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))

        nswindow.setOpaque_(False)
        nswindow.setBackgroundColor_(AppKit.NSColor.clearColor())
        nswindow.setHasShadow_(True)

        # 保留边框拖拽能力（无边框窗口默认可能丢失边缘缩放）
        try:
            mask = nswindow.styleMask()
            nswindow.setStyleMask_(mask | (1 << 3))
        except Exception:
            pass

        nsview = objc.objc_object(c_void_p=int(window.winId()))
        container = nsview.superview()
        if container is None:
            return WindowEffects(False, "macos")

        frame = container.bounds()
        radius = 18.0

        if hasattr(AppKit, "NSGlassEffectView"):
            glass = AppKit.NSGlassEffectView.alloc().initWithFrame_(frame)
            glass.setCornerRadius_(radius)
            try:
                glass.setStyle_(AppKit.NSGlassEffectViewStyleRegular)
            except Exception:
                pass
        else:
            glass = AppKit.NSVisualEffectView.alloc().initWithFrame_(frame)
            glass.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
            glass.setBlendingMode_(
                AppKit.NSVisualEffectBlendingModeBehindWindow)
            glass.setState_(AppKit.NSVisualEffectStateActive)

        # 宽度与高度自适应
        glass.setAutoresizingMask_(2 | 16)
        container.addSubview_positioned_relativeTo_(
            glass, AppKit.NSWindowBelow, nsview)

        window._native_glass_view = glass
        return WindowEffects(True, "macos")
    except Exception:
        return WindowEffects(False, "macos")


# =========================== Windows ===========================

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_SYSTEMBACKDROP_TYPE = 38

_DWMWCP_ROUND = 2
_DWMSBT_MAINWINDOW = 2

_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_WCA_ACCENT_POLICY = 19


class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


def _apply_windows(window):
    try:
        hwnd = wintypes.HWND(int(window.winId()))
        dwmapi = ctypes.windll.dwmapi
        user32 = ctypes.windll.user32
        build = sys.getwindowsversion().build

        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        dwmapi.DwmExtendFrameIntoClientArea.argtypes = [
            wintypes.HWND, ctypes.POINTER(_MARGINS)]
        dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
        user32.SetWindowCompositionAttribute.argtypes = [
            wintypes.HWND, ctypes.POINTER(_WINDOWCOMPOSITIONATTRIBDATA)]
        user32.SetWindowCompositionAttribute.restype = wintypes.BOOL

        dark = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark), ctypes.sizeof(dark))

        if build >= 22000:
            corner = ctypes.c_int(_DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(
                hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(corner), ctypes.sizeof(corner))

        native = False
        if build >= 22621:
            backdrop = ctypes.c_int(_DWMSBT_MAINWINDOW)
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, _DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(backdrop), ctypes.sizeof(backdrop))
            if result == 0:
                native = True
                margins = _MARGINS(-1, -1, -1, -1)
                dwmapi.DwmExtendFrameIntoClientArea(
                    hwnd, ctypes.byref(margins))
        elif build >= 17763:
            # Windows 10 使用 Acrylic 近似，失败时回退自绘玻璃
            policy = _ACCENT_POLICY()
            policy.AccentState = _ACCENT_ENABLE_ACRYLICBLURBEHIND
            policy.AccentFlags = 2
            policy.GradientColor = 0xB2141926  # AABBGGRR
            data = _WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = _WCA_ACCENT_POLICY
            data.Data = ctypes.cast(
                ctypes.pointer(policy), ctypes.c_void_p)
            data.SizeOfData = ctypes.sizeof(policy)
            result = user32.SetWindowCompositionAttribute(
                hwnd, ctypes.byref(data))
            native = bool(result)

        return WindowEffects(native, "windows")
    except Exception:
        return WindowEffects(False, "windows")
