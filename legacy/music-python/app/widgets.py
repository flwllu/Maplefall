"""通用 UI 组件：玻璃卡片、页头、拖放区、封面视图、下拉框、提示条。"""

import os

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
    Property, Signal
)
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath
)
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget
)

from .icons import icon as make_icon
from .icons import pixmap as make_pixmap


# ============================ 基础控件 ============================

def make_button(text, icon_name=None, kind="ghost", on_click=None, parent=None):
    button = QPushButton(text, parent)
    names = {
        "primary": "primaryBtn",
        "ghost": "ghostBtn",
        "danger": "dangerBtn",
        "quiet": "quietBtn",
    }
    button.setObjectName(names.get(kind, "ghostBtn"))
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedHeight(36 if kind != "quiet" else 30)
    if icon_name:
        colors = {
            "primary": "#FFFFFF",
            "ghost": "#3A3A3C",
            "danger": "#B3261E",
            "quiet": "#6E6E73",
        }
        button.setIcon(make_icon(
            icon_name, colors.get(kind, "#3A3A3C"), 16,
            disabled_color="#B0B0B5"))
        button.setIconSize(QSize(16, 16))
    if on_click:
        button.clicked.connect(on_click)
    return button


def make_chip(text="", accent=False):
    label = QLabel(text)
    label.setObjectName("chipAccent" if accent else "chip")
    label.setFixedHeight(24)
    label.setAlignment(Qt.AlignCenter)
    return label


def make_separator():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background: #ECECF0;")
    return line


def section_title(text):
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def choose_directory(parent, title="选择文件夹", start=""):
    """使用 Qt 自绘目录对话框，避免原生对话框在无边框窗口后不显示。"""
    dialog = QFileDialog(parent.window() if parent is not None else None, title)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setLabelText(QFileDialog.DialogLabel.LookIn, "位置")
    dialog.setLabelText(QFileDialog.DialogLabel.FileName, "文件夹")
    dialog.setLabelText(QFileDialog.DialogLabel.FileType, "类型")
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, "选择")
    dialog.setLabelText(QFileDialog.DialogLabel.Reject, "取消")
    if start and os.path.isdir(start):
        dialog.setDirectory(start)
    dialog.resize(760, 520)
    if dialog.exec() and dialog.selectedFiles():
        return dialog.selectedFiles()[0]
    return ""


class GlassCard(QFrame):
    def __init__(self, parent=None, margins=(22, 20, 22, 20), spacing=14):
        super().__init__(parent)
        self.setObjectName("glassCard")
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(*margins)
        self.vbox.setSpacing(spacing)


class ToggleSwitch(QWidget):
    """轻量开关，自绘轨道与滑块，带短促动画。"""

    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = bool(checked)
        self._position = 1.0 if self._checked else 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked, emit=True):
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()
        if emit:
            self.toggled.emit(checked)

    def _get_position(self):
        return self._position

    def _set_position(self, value):
        self._position = float(value)
        self.update()

    position = Property(float, _get_position, _set_position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        track = QRectF(1, 2, self.width() - 2, self.height() - 4)
        radius = track.height() / 2
        if self._checked:
            painter.setBrush(QColor("#111111"))
            painter.setPen(Qt.NoPen)
        else:
            painter.setBrush(QColor("#E5E5EA"))
            painter.setPen(QColor("#D2D2D7"))
        painter.drawRoundedRect(track, radius, radius)

        knob = 18
        travel = track.width() - knob - 4
        x = track.left() + 2 + travel * self._position
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, track.top() + 2, knob, knob))
        painter.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)


class StatTile(QFrame):
    def __init__(self, caption, value="—", parent=None):
        super().__init__(parent)
        self.setObjectName("softCard")
        self.setMinimumHeight(64)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(3)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("statValue")
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("statLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(self.caption_label)

    def set_value(self, value):
        self.value_label.setText(value or "—")


class _ComboItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(option.rect).adjusted(3, 2, -3, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected or hovered:
            path = QPainterPath()
            path.addRoundedRect(rect, 6, 6)
            painter.fillPath(
                path, QColor("#EDEDF0" if selected else "#F5F5F7"))

        painter.setPen(QColor("#1D1D1F"))
        painter.setFont(option.font)
        text = str(index.data(Qt.DisplayRole) or "")
        painter.drawText(
            rect.adjusted(11, 0, -11, 0),
            Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(34)
        size.setWidth(size.width() + 26)
        return size


class SelectBox(QComboBox):
    """隐藏原生箭头，自己画统一风格的 chevron 和下拉菜单。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("select")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        self.setMinimumWidth(150)
        self.setMaxVisibleItems(8)

        self.setItemDelegate(_ComboItemDelegate(self))
        view = self.view()
        view.setMouseTracking(True)
        view.setStyleSheet(
            "QListView { background: #FFFFFF;"
            "border: 1px solid #E5E5EA;"
            "border-radius: 8px; padding: 5px; outline: 0; }")
        container = view.window()
        if container is not None:
            container.setStyleSheet("QFrame { background: transparent; border: none; }")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        color = "#B0B0B5" if not self.isEnabled() else "#8E8E93"
        pm = make_pixmap("chevronDown", color, 14)
        painter.drawPixmap(
            self.width() - 24, (self.height() - 14) // 2 - 1, pm)
        painter.end()


class CoverView(QWidget):
    """圆角裁切 + 居中填充的封面展示。"""

    def __init__(self, size=108, radius=16, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._radius = radius
        self.setFixedSize(size, size)

    def set_cover(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def clear_cover(self):
        self._pixmap = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        painter.setClipPath(path)
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation)
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2, scaled)
        else:
            painter.fillPath(path, QColor("#F2F2F7"))
            pm = make_pixmap("note", "#B0B0B5", 34)
            painter.drawPixmap(
                (self.width() - 34) // 2, (self.height() - 34) // 2, pm)

        painter.setClipping(False)
        painter.setPen(QColor("#E5E5EA"))
        painter.drawPath(path)
        painter.end()


# ============================ 页头 ============================

class PageHeader(QWidget):
    def __init__(self, title, subtitle, icon_name, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        badge = QLabel()
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignCenter)
        badge.setPixmap(make_pixmap(icon_name, "#3A3A3C", 22))
        badge.setStyleSheet(
            "background: #F2F2F7;"
            "border: 1px solid #E5E5EA;"
            "border-radius: 12px;")
        layout.addWidget(badge)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        text_box.addWidget(title_label)
        text_box.addWidget(subtitle_label)
        layout.addLayout(text_box)
        layout.addStretch()

        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(10)
        layout.addLayout(self.actions)

    def add_action(self, widget):
        self.actions.addWidget(widget)


class DropZone(QFrame):
    def __init__(self, title, hint, icon_name="note", on_browse=None, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setMinimumHeight(250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 34, 40, 34)
        layout.setSpacing(10)
        layout.addStretch()

        badge = QLabel()
        badge.setFixedSize(66, 66)
        badge.setAlignment(Qt.AlignCenter)
        badge.setPixmap(make_pixmap(icon_name, "#6E6E73", 30))
        badge.setStyleSheet(
            "background: #F2F2F7;"
            "border: 1px solid #E5E5EA;"
            "border-radius: 18px;")
        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge_row.addWidget(badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: #111111;")
        layout.addWidget(title_label)

        hint_label = QLabel(hint)
        hint_label.setObjectName("hint")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        if on_browse:
            browse_row = QHBoxLayout()
            browse_row.addStretch()
            browse_row.addWidget(make_button(
                "浏览文件", "folderOpen", "ghost", on_browse))
            browse_row.addStretch()
            layout.addSpacing(6)
            layout.addLayout(browse_row)

        layout.addStretch()


# ============================ 页面基类 ============================

class BasePage(QWidget):
    def __init__(self, title, subtitle, icon_name, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 10, 30, 26)
        outer.setSpacing(18)

        self.header = PageHeader(title, subtitle, icon_name)
        outer.addWidget(self.header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(16)
        outer.addLayout(self.body, 1)

    def add_action(self, widget):
        self.header.add_action(widget)

    def on_drop_path(self, path):
        """子类按需覆盖：接收拖入的文件或目录。"""

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and (os.path.isfile(path) or os.path.isdir(path)):
                self.on_drop_path(path)
                break


# ============================ 悬浮提示 ============================

class Toast(QFrame):
    _active = {}

    def __init__(self, parent, text, kind="success"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        colors = {
            "success": ("check", "#1B7F4B"),
            "warning": ("alert", "#B25000"),
            "error": ("alert", "#C0392B"),
            "info": ("sparkle", "#111111"),
        }
        icon_name, color = colors.get(kind, colors["info"])
        self.setStyleSheet(
            "QFrame { background: #FFFFFF;"
            "border: 1px solid #E5E5EA;"
            "border-radius: 10px; }"
            "QLabel { background: transparent; border: none; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 16, 9)
        layout.setSpacing(9)
        icon_label = QLabel()
        icon_label.setPixmap(make_pixmap(icon_name, color, 16))
        icon_label.setFixedSize(16, 16)
        layout.addWidget(icon_label)
        text_label = QLabel(text)
        text_label.setStyleSheet(
            "font-size: 12px; color: #1D1D1F; background: transparent;")
        layout.addWidget(text_label)

        self.adjustSize()
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._animation = QPropertyAnimation(self._opacity, b"opacity", self)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    @classmethod
    def show_message(cls, parent, text, kind="success"):
        window = parent.window()
        old = cls._active.pop(window, None)
        if old is not None:
            old.deleteLater()

        toast = cls(window, text, kind)
        cls._active[window] = toast
        toast._present()
        return toast

    def _present(self):
        parent = self.parentWidget()
        self.adjustSize()
        x = max(16, (parent.width() - self.width()) // 2)
        y = parent.height() - self.height() - 28
        self.move(QPoint(x, y))
        self.show()
        self.raise_()

        self._animation.stop()
        self._animation.setDuration(180)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()

        QTimer.singleShot(2200, self._dismiss)

    def _dismiss(self):
        self._animation.stop()
        self._animation.setDuration(260)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.finished.connect(self._cleanup)
        self._animation.start()

    def _cleanup(self):
        window = self.parentWidget()
        if self._active.get(window) is self:
            self._active.pop(window, None)
        self.deleteLater()
