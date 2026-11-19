import json
import os
import sys

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
)
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget
)

from .icons import icon as make_icon
from .icons import pixmap as make_pixmap
from .metadata import (
    FORMAT_DEFAULT, format_duration, format_file_size, generate_filename,
    get_all_metadata, get_audio_properties, get_cover_art,
    get_full_metadata, embed_cover_art, import_metadata_from_json,
    remove_cover_art, set_metadata
)
from .pages.batch_page import BatchPage
from .pages.cover_page import CoverPage
from .pages.convert_page import ConvertPage
from .pages.editor_page import EditorPage
from .pages.export_page import ExportPage
from .pages.intro_page import IntroPage
from .sidebar import Sidebar
from .styles import STYLESHEET
from .widgets import Toast

AUDIO_FILTER = (
    "音频文件 (*.mp3 *.flac *.m4a *.wav *.aiff *.aif *.ogg *.opus *.wma "
    "*.aac *.alac *.mka);;所有文件 (*)")

MEDIA_FILTER = (
    "媒体文件 (*.mp3 *.flac *.m4a *.wav *.aiff *.aif *.ogg *.opus *.wma "
    "*.aac *.alac *.mka *.mp4 *.mkv *.mov *.webm *.avi *.flv *.ts *.gif "
    "*.m4v *.wmv *.mpg *.mpeg);;"
    "音频文件 (*.mp3 *.flac *.m4a *.wav *.aiff *.aif *.ogg *.opus *.wma "
    "*.aac *.alac *.mka);;"
    "视频文件 (*.mp4 *.mkv *.mov *.webm *.avi *.flv *.ts *.gif *.m4v "
    "*.wmv *.mpg *.mpeg);;所有文件 (*)")

WINDOW_RADIUS = 18


# ============================ 无边框窗口控件 ============================

class ResizeHandle(QWidget):
    """窗口边缘的透明拖拽条，优先交给系统处理，失败时手动缩放。"""

    def __init__(self, window, edges):
        super().__init__(window)
        self._window = window
        self._edges = edges
        self._origin = None
        self._geometry = None
        self.setObjectName("resizeHandle")

        cursors = {
            Qt.LeftEdge: Qt.SizeHorCursor,
            Qt.RightEdge: Qt.SizeHorCursor,
            Qt.TopEdge: Qt.SizeVerCursor,
            Qt.BottomEdge: Qt.SizeVerCursor,
            Qt.TopEdge | Qt.LeftEdge: Qt.SizeFDiagCursor,
            Qt.BottomEdge | Qt.RightEdge: Qt.SizeFDiagCursor,
            Qt.TopEdge | Qt.RightEdge: Qt.SizeBDiagCursor,
            Qt.BottomEdge | Qt.LeftEdge: Qt.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(edges, Qt.ArrowCursor))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        handle = self._window.windowHandle()
        if handle is not None and handle.startSystemResize(self._edges):
            event.accept()
            return
        self._origin = event.globalPosition().toPoint()
        self._geometry = self._window.geometry()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._origin is None or not (event.buttons() & Qt.LeftButton):
            return
        delta = event.globalPosition().toPoint() - self._origin
        geo = QRect(self._geometry)
        min_w = self._window.minimumWidth()
        min_h = self._window.minimumHeight()

        if self._edges & Qt.LeftEdge:
            geo.setLeft(min(geo.left() + delta.x(),
                            geo.right() - min_w + 1))
        if self._edges & Qt.RightEdge:
            geo.setRight(max(geo.right() + delta.x(),
                             geo.left() + min_w - 1))
        if self._edges & Qt.TopEdge:
            geo.setTop(min(geo.top() + delta.y(),
                           geo.bottom() - min_h + 1))
        if self._edges & Qt.BottomEdge:
            geo.setBottom(max(geo.bottom() + delta.y(),
                              geo.top() + min_h - 1))
        self._window.setGeometry(geo)

    def mouseReleaseEvent(self, event):
        self._origin = None
        self._geometry = None


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("titleBar")
        self.setFixedHeight(52)
        self._origin = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 10, 0)
        layout.setSpacing(10)

        self.is_mac = sys.platform == "darwin"
        self.max_button = None

        if self.is_mac:
            layout.addLayout(self._mac_controls())
            layout.addSpacing(8)

        logo = QLabel()
        logo.setFixedSize(26, 26)
        logo.setPixmap(make_pixmap("logo", "#111111", 26))
        logo.setStyleSheet("background: transparent;")
        layout.addWidget(logo)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        name = QLabel("音律工具箱")
        name.setObjectName("brandName")
        caption = QLabel("MEDIA TOOLBOX")
        caption.setObjectName("brandCaption")
        caption_font = QFont(caption.font())
        caption_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        caption.setFont(caption_font)
        brand.addWidget(name)
        brand.addWidget(caption)
        layout.addLayout(brand)

        divider = QLabel()
        divider.setObjectName("titleDivider")
        divider.setFixedSize(1, 18)
        layout.addSpacing(4)
        layout.addWidget(divider)

        self.file_chip = QLabel()
        self.file_chip.setObjectName("fileChip")
        self.file_chip.setFixedHeight(24)
        self.file_chip.hide()
        layout.addWidget(self.file_chip)
        layout.addStretch()

        if not self.is_mac:
            layout.addLayout(self._win_controls())

    # ------------------------------------------------------------------

    def _mac_controls(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        for object_name, tip, handler in (
                ("macClose", "关闭", self.window().close),
                ("macMin", "最小化", self.window().showMinimized),
                ("macMax", "缩放", self.window().toggle_maximized)):
            button = QPushButton()
            button.setObjectName(object_name)
            button.setFixedSize(14, 14)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tip)
            button.clicked.connect(handler)
            row.addWidget(button)
        return row

    def _win_controls(self):
        row = QHBoxLayout()
        row.setSpacing(2)

        minimize = self._win_button("minus", "最小化")
        minimize.clicked.connect(self.window().showMinimized)
        row.addWidget(minimize)

        self.max_button = self._win_button("maximize", "最大化")
        self.max_button.clicked.connect(self.window().toggle_maximized)
        row.addWidget(self.max_button)

        close = self._win_button("close", "关闭", close=True)
        close.clicked.connect(self.window().close)
        row.addWidget(close)
        return row

    def _win_button(self, icon_name, tip, close=False):
        button = QPushButton()
        button.setObjectName("closeBtn" if close else "winBtn")
        button.setFixedSize(36, 30)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tip)
        button.setIcon(make_icon(
            icon_name, "#FFFFFF" if close else "#6E6E73", 14))
        button.setIconSize(QSize(14, 14))
        return button

    # ------------------------------------------------------------------

    def set_current_file(self, name):
        if not name:
            self.file_chip.hide()
            return
        metrics = self.file_chip.fontMetrics()
        self.file_chip.setText(metrics.elidedText(name, Qt.ElideMiddle, 260))
        self.file_chip.setToolTip(name)
        self.file_chip.show()

    def set_maximized(self, maximized):
        if self.max_button is not None:
            self.max_button.setIcon(make_icon(
                "restore" if maximized else "maximize", "#6E6E73", 14))
            self.max_button.setToolTip("还原" if maximized else "最大化")

    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        handle = self.window().windowHandle()
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        self._origin = (
            event.globalPosition().toPoint()
            - self.window().frameGeometry().topLeft())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._origin is not None and event.buttons() & Qt.LeftButton:
            self.window().move(
                event.globalPosition().toPoint() - self._origin)

    def mouseReleaseEvent(self, event):
        self._origin = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window().toggle_maximized()


# ============================ 主窗口 ============================

class MusicRenamerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.file_path = None
        self.original_name = None
        self.title = None
        self.artist = None
        self.album = None
        self.new_filename = None
        self.fmt = FORMAT_DEFAULT
        self._cover_data_list = []
        self._cover_pixmap = None
        self._handles = {}

        self.setWindowTitle("音律工具箱")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("root")
        self.resize(1080, 760)
        self.setMinimumSize(940, 660)
        self.setStyleSheet(STYLESHEET)

        self._init_ui()
        self._init_handles()

    # ------------------------------------------------------------------

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.titlebar = TitleBar(self)
        layout.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = Sidebar(on_nav_changed=self._on_nav_changed)
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")

        self.intro_page = IntroPage(
            on_select_file=self._on_select_file,
            on_export_json=self._export_json)
        self.editor_page = EditorPage(
            on_select_file=self._on_select_file,
            on_save=self._save_metadata,
            on_import_json=self._import_metadata_json)
        self.cover_page = CoverPage(
            on_select_file=self._on_select_file,
            on_extract=self._extract_cover,
            on_embed=self._embed_cover,
            on_remove=self._remove_cover)
        self.export_page = ExportPage(
            on_select_file=self._on_select_file,
            on_rename=self._do_rename,
            on_format_changed=self._on_format_changed)
        self.batch_page = BatchPage()
        self.convert_page = ConvertPage(on_select_file=self._on_select_file)

        for page in (self.intro_page, self.editor_page, self.cover_page,
                     self.export_page, self.batch_page, self.convert_page):
            self.stack.addWidget(page)

        body.addWidget(self.stack, 1)
        layout.addLayout(body, 1)

    def _init_handles(self):
        definitions = {
            "top": Qt.TopEdge,
            "bottom": Qt.BottomEdge,
            "left": Qt.LeftEdge,
            "right": Qt.RightEdge,
            "top_left": Qt.TopEdge | Qt.LeftEdge,
            "top_right": Qt.TopEdge | Qt.RightEdge,
            "bottom_left": Qt.BottomEdge | Qt.LeftEdge,
            "bottom_right": Qt.BottomEdge | Qt.RightEdge,
        }
        for name, edges in definitions.items():
            handle = ResizeHandle(self, edges)
            handle.hide()
            self._handles[name] = handle
        self._layout_handles()

    def _layout_handles(self):
        maximized = self.isMaximized() or self.isFullScreen()
        for handle in self._handles.values():
            handle.setVisible(not maximized)
        if maximized:
            return

        width = self.width()
        height = self.height()
        thick = 6
        corner = 12

        self._handles["top"].setGeometry(
            corner, 0, max(0, width - corner * 2), thick)
        self._handles["bottom"].setGeometry(
            corner, height - thick, max(0, width - corner * 2), thick)
        self._handles["left"].setGeometry(
            0, corner, thick, max(0, height - corner * 2))
        self._handles["right"].setGeometry(
            width - thick, corner, thick, max(0, height - corner * 2))
        self._handles["top_left"].setGeometry(0, 0, corner, corner)
        self._handles["top_right"].setGeometry(
            width - corner, 0, corner, corner)
        self._handles["bottom_left"].setGeometry(
            0, height - corner, corner, corner)
        self._handles["bottom_right"].setGeometry(
            width - corner, height - corner, corner, corner)

        for handle in self._handles.values():
            handle.raise_()

    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_handles()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_handles()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            maximized = self.isMaximized() or self.isFullScreen()
            self._layout_handles()
            self.titlebar.set_maximized(maximized)
            self.update()

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = 0 if (self.isMaximized() or self.isFullScreen()) \
            else WINDOW_RADIUS
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        painter.fillPath(path, QColor("#FFFFFF"))

        painter.setClipping(False)
        painter.setPen(QPen(QColor("#DCDCE1"), 1))
        painter.drawPath(path)
        painter.end()

    # ------------------------------------------------------------------

    def _on_nav_changed(self, key):
        pages = {
            "intro": self.intro_page,
            "editor": self.editor_page,
            "cover": self.cover_page,
            "export": self.export_page,
            "batch": self.batch_page,
            "convert": self.convert_page,
        }
        if key in pages:
            self.stack.setCurrentWidget(pages[key])

    # ------------------------------------------------------------------

    def _on_select_file(self, path=None, kind="audio"):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择媒体文件" if kind == "media" else "选择音频文件",
                "", MEDIA_FILTER if kind == "media" else AUDIO_FILTER)
        if path:
            self._load_file(path)

    def _load_file(self, file_path):
        if not os.path.isfile(file_path):
            QMessageBox.critical(self, "错误", f"文件不存在：\n{file_path}")
            return

        self.file_path = file_path
        self.original_name = os.path.basename(file_path)
        meta = get_full_metadata(file_path)
        self.title = meta["title"]
        self.artist = meta["artist"]
        self.album = meta["album"]

        self.new_filename = generate_filename(
            self.title, self.artist, self.fmt)

        ext_fmt = os.path.splitext(self.original_name)[1].upper().lstrip(".")
        size_str = format_file_size(file_path)
        props = get_audio_properties(file_path)

        self._cover_data_list = get_cover_art(file_path)
        self._cover_pixmap = None
        if self._cover_data_list:
            pixmap = QPixmap()
            if pixmap.loadFromData(self._cover_data_list[0]["data"]):
                self._cover_pixmap = pixmap

        self.intro_page.show_info(
            self.original_name, self.title, self.artist, self.album,
            ext_fmt, size_str, props, self._cover_pixmap)

        self.editor_page.populate(get_all_metadata(file_path))
        self.cover_page.show_cover(
            self._cover_pixmap, bool(self._cover_data_list))
        self.convert_page.show_file(file_path)

        ext = os.path.splitext(self.original_name)[1]
        preview = (self.new_filename + ext) if self.new_filename else \
            "无法生成（缺少标签）"
        self.export_page.show_preview(
            preview, bool(self.title or self.artist), self.original_name)

        self.titlebar.set_current_file(self.original_name)
        self.setWindowTitle(f"{self.original_name} · 音律工具箱")

    # ------------------------------------------------------------------

    def _export_json(self):
        if not self.file_path:
            return
        ext_fmt = os.path.splitext(self.original_name)[1].upper().lstrip(".")
        size_str = format_file_size(self.file_path)
        props = get_audio_properties(self.file_path)
        data = {
            "file": self.original_name,
            "title": self.title or None,
            "artist": self.artist or None,
            "album": self.album or None,
            "format": ext_fmt,
            "size": size_str,
            "duration": format_duration(props.get("length")),
            "bitrate": f"{props.get('bitrate', 0) // 1000} kbps"
            if props.get("bitrate") else None,
            "sample_rate": f"{props.get('sample_rate', 0) / 1000:.1f} kHz"
            if props.get("sample_rate") else None,
            "channels": props.get("channels"),
        }
        default_name = os.path.splitext(self.original_name)[0] + ".json"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出 JSON", default_name,
            "JSON 文件 (*.json);;所有文件 (*)")
        if not save_path:
            return
        try:
            with open(save_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            Toast.show_message(self, "JSON 已导出", "success")
        except OSError as error:
            QMessageBox.critical(self, "导出失败", f"{error}")

    def _on_format_changed(self, fmt):
        self.fmt = fmt
        if self.file_path:
            self.new_filename = generate_filename(
                self.title, self.artist, self.fmt)
            ext = os.path.splitext(self.original_name)[1]
            preview = (self.new_filename + ext) if self.new_filename else \
                "无法生成（缺少标签）"
            self.export_page.show_preview(
                preview, bool(self.title or self.artist), self.original_name)

    # ------------------------------------------------------------------

    def _save_metadata(self, fields):
        if not self.file_path:
            QMessageBox.critical(self, "错误", "没有选中的文件")
            return
        if set_metadata(self.file_path, fields):
            Toast.show_message(self, "元数据已保存", "success")
            self._load_file(self.file_path)
        else:
            QMessageBox.critical(
                self, "保存失败", "该格式暂时无法写入标签，或文件被占用。")

    def _import_metadata_json(self):
        if not self.file_path:
            QMessageBox.critical(self, "错误", "请先选择一个音频文件")
            return
        json_path, _ = QFileDialog.getOpenFileName(
            self, "选择 JSON 文件", "",
            "JSON 文件 (*.json);;所有文件 (*)")
        if not json_path:
            return
        if import_metadata_from_json(self.file_path, json_path):
            Toast.show_message(self, "元数据已导入", "success")
            self._load_file(self.file_path)
        else:
            QMessageBox.critical(
                self, "导入失败", "无法读取 JSON 或写入元数据。")

    # ------------------------------------------------------------------

    def _extract_cover(self):
        if not self._cover_data_list or not self.file_path:
            QMessageBox.critical(self, "错误", "该文件没有封面数据")
            return
        cover = self._cover_data_list[0]
        ext_map = {
            "image/jpeg": ".jpg", "image/png": ".png",
            "image/bmp": ".bmp", "image/gif": ".gif"}
        ext = ext_map.get(cover["mime"], ".jpg")
        default_name = os.path.splitext(self.original_name)[0] + ext
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存封面", default_name,
            f"图片文件 (*{ext});;所有文件 (*)")
        if not save_path:
            return
        try:
            with open(save_path, "wb") as handle:
                handle.write(cover["data"])
            Toast.show_message(self, "封面已提取", "success")
        except OSError as error:
            QMessageBox.critical(self, "保存失败", str(error))

    def _embed_cover(self, image_path):
        if not self.file_path:
            return
        if embed_cover_art(self.file_path, image_path):
            Toast.show_message(self, "封面已更新", "success")
            self._load_file(self.file_path)
        else:
            QMessageBox.critical(self, "嵌入失败", "写入封面时发生错误。")

    def _remove_cover(self):
        if not self.file_path:
            return
        if remove_cover_art(self.file_path):
            Toast.show_message(self, "封面已删除", "success")
            self._load_file(self.file_path)
        else:
            QMessageBox.critical(self, "删除失败", "该文件没有可删除的封面。")

    # ------------------------------------------------------------------

    def _do_rename(self):
        if not self.new_filename or not self.file_path:
            QMessageBox.critical(self, "错误", "无法生成新文件名")
            return

        folder = os.path.dirname(self.file_path)
        ext = os.path.splitext(self.original_name)[1]
        new_path = os.path.join(folder, self.new_filename + ext)

        if os.path.exists(new_path) and new_path != self.file_path:
            reply = QMessageBox.question(
                self, "文件已存在",
                f"目标文件「{self.new_filename}{ext}」已存在，是否覆盖？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        try:
            os.replace(self.file_path, new_path)
            self.file_path = new_path
            self.original_name = os.path.basename(new_path)

            self.export_page.mark_done(self.new_filename + ext)
            self.titlebar.set_current_file(self.original_name)
            self.setWindowTitle(f"{self.original_name} · 音律工具箱")

            ext_fmt = os.path.splitext(self.original_name)[1].upper().lstrip(".")
            size_str = format_file_size(new_path)
            props = get_audio_properties(new_path)
            self.intro_page.show_info(
                self.original_name, self.title, self.artist, self.album,
                ext_fmt, size_str, props, self._cover_pixmap)

            Toast.show_message(self, "重命名完成", "success")
        except OSError as error:
            QMessageBox.critical(self, "重命名失败", f"发生错误：\n{error}")

    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self.convert_page.shutdown()
        super().closeEvent(event)

    def open_file(self, path):
        self._load_file(path)
