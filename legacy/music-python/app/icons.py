"""统一描边风格的矢量图标，可随主题任意着色。"""

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "note": '<path d="M9 17.5V6.2l9.5-1.9v11.2"/>'
            '<circle cx="6.5" cy="17.5" r="2.6"/>'
            '<circle cx="16" cy="15.5" r="2.6"/>',
    "edit": '<path d="M4.5 19.5h4L19 9a2.1 2.1 0 0 0-3-3L5.5 16.5v3z"/>'
            '<path d="M14.5 7.5l3 3"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/>'
             '<circle cx="9" cy="10" r="1.8"/>'
             '<path d="M4.5 17.5l5-5 3.8 3.8 2.7-2.7 4 4"/>',
    "tag": '<path d="M20 13.2l-6.8 6.8-9-9V4h7l8.8 9.2z"/><circle cx="8" cy="8" r="1.4"/>',
    "folder": '<path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h4.2l2 2.2H18a2.5 2.5 0 0 1 2.5 2.5v7.8A2.5 2.5 0 0 1 18 20H6a2.5 2.5 0 0 1-2.5-2.5V7.5z"/>',
    "swap": '<path d="M4 8.5h13.5l-3.2-3.2"/><path d="M20 15.5H6.5l3.2 3.2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "download": '<path d="M12 4v11"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M4.5 20h15"/>',
    "upload": '<path d="M12 20V9"/><path d="M7.5 13.5L12 9l4.5 4.5"/><path d="M4.5 4.5h15"/>',
    "save": '<path d="M5 4.5h10.5L19.5 8.5v11H5z"/><path d="M8 4.5v5h7"/>'
            '<path d="M8 19.5v-5.5h8v5.5"/>',
    "trash": '<path d="M4.5 7h15"/><path d="M9.5 7V4.5h5V7"/>'
             '<path d="M6.5 7l1 13h9l1-13"/>',
    "file": '<path d="M6 3.5h7.5L18 8v12.5H6z"/><path d="M13.5 3.5V8H18"/>',
    "check": '<path d="M4.5 12.5l5 5L20 6.5"/>',
    "alert": '<path d="M12 4.5l8.5 15h-17z"/><path d="M12 10v4"/>'
             '<circle cx="12" cy="16.8" r="0.9" fill="{color}" stroke="none"/>',
    "chevronDown": '<path d="M6.5 9.5l5.5 5.5 5.5-5.5"/>',
    "chevronRight": '<path d="M9.5 6.5l5.5 5.5-5.5 5.5"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "minus": '<path d="M5.5 12h13"/>',
    "maximize": '<rect x="5.5" y="5.5" width="13" height="13" rx="2.2"/>',
    "restore": '<rect x="4.5" y="8.5" width="11" height="11" rx="2"/>'
               '<path d="M8.5 8.5v-4h11v11h-4"/>',
    "sparkle": '<path d="M12 4l1.6 5.2L19 11l-5.4 1.8L12 18l-1.6-5.2L5 11l5.4-1.8z"/>'
               '<path d="M18.5 4.5l.6 1.9 1.9.6-1.9.6-.6 1.9-.6-1.9L16 6.9l1.9-.6z"/>',
    "shield": '<path d="M12 3.5l7 2.6v5.4c0 4.2-2.8 7.3-7 9-4.2-1.7-7-4.8-7-9V6.1z"/>'
              '<path d="M8.8 12l2.2 2.2 4.2-4.2"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
    "wave": '<path d="M3.5 12h2l1.6-4.5 2.4 9 2.2-12 2.3 15 2.1-10.5 1.7 3H21"/>',
    "folderOpen": '<path d="M3.5 8.5A2.5 2.5 0 0 1 6 6h4l2 2.2h7a2 2 0 0 1 2 2.2l-1 7.2A2.5 2.5 0 0 1 17.5 20H6a2.5 2.5 0 0 1-2.5-2.5z"/>',
}

_LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#A79BFF"/>
      <stop offset="0.55" stop-color="#7F8CFF"/>
      <stop offset="1" stop-color="#5FE2F0"/>
    </linearGradient>
    <linearGradient id="s" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect x="52" y="52" width="920" height="920" rx="228" fill="url(#g)"/>
  <rect x="52" y="52" width="920" height="460" rx="228" fill="url(#s)"/>
  <g fill="none" stroke="#0A0F20" stroke-width="58" stroke-linecap="round" stroke-linejoin="round">
    <path d="M600 722V330l212-42v314"/>
  </g>
  <circle cx="540" cy="736" r="64" fill="#0A0F20"/>
  <circle cx="752" cy="602" r="64" fill="#0A0F20"/>
</svg>"""


def _svg(name, color):
    if name == "logo":
        return _LOGO
    body = _PATHS[name].replace("{color}", color)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )


def pixmap(name, color, size, scale=2.0):
    """按物理像素渲染，保证高分屏下不模糊。"""
    px = max(1, int(round(size * scale)))
    image = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(QByteArray(_svg(name, color).encode("utf-8"))).render(painter)
    painter.end()

    pm = QPixmap.fromImage(image)
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name, color, size=18, disabled_color=None):
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(
        pixmap(name, disabled_color or "#5A6280", size), QIcon.Disabled, QIcon.Off)
    return ic


def logo_image(size):
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(QByteArray(_LOGO.encode("utf-8"))).render(painter)
    painter.end()
    return image


def app_icon():
    ic = QIcon()
    for size in (32, 64, 128, 256, 512):
        ic.addPixmap(pixmap("logo", "#ffffff", size, scale=1.0))
    return ic
