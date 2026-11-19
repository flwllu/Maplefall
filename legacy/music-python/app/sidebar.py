from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from .icons import icon as make_icon
from .widgets import make_separator

NAV_ITEMS = [
    ("音乐", [
        ("intro", "note", "歌曲简介"),
        ("editor", "edit", "编辑元数据"),
        ("cover", "image", "封面管理"),
        ("export", "tag", "单曲重命名"),
        ("batch", "folder", "批量重命名"),
    ]),
    ("转换", [
        ("convert", "swap", "格式转换"),
    ]),
]


class Sidebar(QFrame):
    def __init__(self, on_nav_changed):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(224)
        self._buttons = []
        self._build(on_nav_changed)

    def _build(self, on_nav_changed):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 16)
        layout.setSpacing(3)

        for section, items in NAV_ITEMS:
            layout.addWidget(self._section(section))
            for key, icon_name, label in items:
                layout.addWidget(self._button(key, icon_name, label, on_nav_changed))

        layout.addStretch()
        layout.addWidget(make_separator())

        foot = QLabel("所有处理均在本地完成")
        foot.setObjectName("sidebarFoot")
        foot.setAlignment(Qt.AlignCenter)
        layout.addSpacing(10)
        layout.addWidget(foot)

        version = QLabel("Media Toolbox  ·  v3.0")
        version.setObjectName("sidebarFoot")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        if self._buttons:
            self._buttons[0].setChecked(True)
            self._sync_icon(self._buttons[0], True)

    def _section(self, text):
        label = QLabel(text)
        label.setObjectName("navSection")
        font = QFont(label.font())
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
        label.setFont(font)
        return label

    def _button(self, key, icon_name, label, on_nav_changed):
        button = QPushButton("  " + label)
        button.setObjectName("navBtn")
        button.setCheckable(True)
        button.setFixedHeight(38)
        button.setCursor(Qt.PointingHandCursor)
        button.setIcon(make_icon(icon_name, "#6E6E73", 18))
        button.setIconSize(QSize(18, 18))
        button.setProperty("iconName", icon_name)
        button.setProperty("navKey", key)
        button.clicked.connect(
            lambda checked=False, k=key: self._on_click(k, on_nav_changed))
        button.toggled.connect(
            lambda checked, b=button: self._sync_icon(b, checked))
        self._buttons.append(button)
        return button

    def _sync_icon(self, button, checked):
        name = button.property("iconName")
        color = "#111111" if checked else "#6E6E73"
        button.setIcon(make_icon(name, color, 18))

    def _on_click(self, key, on_nav_changed):
        for button in self._buttons:
            button.setChecked(button.property("navKey") == key)
        on_nav_changed(key)
