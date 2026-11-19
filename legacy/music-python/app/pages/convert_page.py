import os
import threading

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget
)

from ..convert import (
    AUDIO_CODEC_LABELS, AUDIO_LAYOUTS, CONTAINER_SPECS, SAMPLE_RATES,
    VIDEO_CODEC_LABELS, VIDEO_PRESETS, VIDEO_TUNES, ConvertError,
    ConversionCancelled, audio_sample_rates, available_audio_codecs,
    available_video_codecs, container_specs, convert_media,
    default_container_for, default_output_path, format_seconds, parse_time,
    pick_sample_rate, probe_media, video_pix_fmts
)
from ..widgets import (
    BasePage, DropZone, GlassCard, SelectBox, Toast, ToggleSwitch,
    choose_directory, make_button, make_chip, make_separator, section_title
)

MEDIA_EXTS = {
    ".mp3", ".flac", ".m4a", ".wav", ".aiff", ".aif", ".ogg", ".opus",
    ".wma", ".aac", ".alac", ".mka", ".mp4", ".mkv", ".mov", ".webm",
    ".avi", ".flv", ".ts", ".gif", ".m4v", ".wmv", ".mpg", ".mpeg",
}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".ts",
              ".gif", ".m4v", ".wmv", ".mpg", ".mpeg"}


# ============================ 后台任务 ============================

class ConvertWorker(QThread):
    progressed = Signal(int)
    succeeded = Signal(str)
    failed = Signal(str)
    aborted = Signal()

    def __init__(self, src, dst, config, parent=None):
        super().__init__(parent)
        self._src = src
        self._dst = dst
        self._config = config
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            convert_media(
                self._src, self._dst, self._config,
                progress=self.progressed.emit, cancel=self._cancel)
            self.succeeded.emit(self._dst)
        except ConversionCancelled:
            self._remove_partial()
            self.aborted.emit()
        except Exception as error:
            self._remove_partial()
            self.failed.emit(str(error) or error.__class__.__name__)

    def _remove_partial(self):
        try:
            if os.path.exists(self._dst):
                os.remove(self._dst)
        except OSError:
            pass


class BatchConvertWorker(QThread):
    progressed = Signal(int)
    file_started = Signal(str, int, int)
    succeeded = Signal(int, list)
    aborted = Signal()

    def __init__(self, jobs, config, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self._config = config
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        total = len(self._jobs)
        errors = []
        done = 0
        for index, (src, dst) in enumerate(self._jobs):
            if self._cancel.is_set():
                self.aborted.emit()
                return
            self.file_started.emit(os.path.basename(src), index + 1, total)

            def report(percent, current=index):
                overall = (current + percent / 100.0) / max(1, total)
                self.progressed.emit(min(99, int(overall * 100)))

            try:
                convert_media(
                    src, dst, self._config,
                    progress=report, cancel=self._cancel)
                done += 1
            except ConversionCancelled:
                self._remove(dst)
                self.aborted.emit()
                return
            except Exception as error:
                self._remove(dst)
                errors.append(
                    f"{os.path.basename(src)}：{error}")
            self.progressed.emit(int((index + 1) / max(1, total) * 100))

        self.succeeded.emit(done, errors)

    @staticmethod
    def _remove(path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


# ============================ 参数编辑器 ============================

class KeyValueEditor(QWidget):
    """可增减的 key=value 参数列表。"""

    def __init__(self, key_hint="参数名", value_hint="值", parent=None):
        super().__init__(parent)
        self._key_hint = key_hint
        self._value_hint = value_hint
        self._rows = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        self._rows_box = QVBoxLayout()
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(7)
        layout.addLayout(self._rows_box)

        add = QPushButton("+ 添加参数")
        add.setObjectName("miniBtn")
        add.setFixedHeight(27)
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(lambda: self.add_row())
        layout.addWidget(add, 0, Qt.AlignLeft)

        self.add_row()

    def add_row(self, key="", value=""):
        row = QFrame()
        row.setObjectName("kvRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        key_edit = QLineEdit(key)
        key_edit.setObjectName("fieldInput")
        key_edit.setPlaceholderText(self._key_hint)
        key_edit.setFixedHeight(32)
        value_edit = QLineEdit(value)
        value_edit.setObjectName("fieldInput")
        value_edit.setPlaceholderText(self._value_hint)
        value_edit.setFixedHeight(32)

        remove = make_button("", "trash", "quiet", lambda: self._remove_row(row))
        remove.setFixedSize(30, 30)
        remove.setToolTip("删除这一项")

        layout.addWidget(key_edit, 2)
        layout.addWidget(value_edit, 3)
        layout.addWidget(remove)
        self._rows_box.addWidget(row)
        self._rows.append((row, key_edit, value_edit))
        return row

    def _remove_row(self, row):
        for item in list(self._rows):
            if item[0] is row:
                self._rows.remove(item)
                break
        row.setParent(None)
        row.deleteLater()
        if not self._rows:
            self.add_row()

    def values(self):
        data = {}
        for _, key_edit, value_edit in self._rows:
            key = key_edit.text().strip()
            if key:
                data[key] = value_edit.text().strip()
        return data

    def clear(self):
        for row, _, _ in list(self._rows):
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        self.add_row()


# ============================ 转换页 ============================

class ConvertPage(BasePage):
    SEGMENTS = ("基础", "视频", "音频", "滤镜", "高级")

    def __init__(self, on_select_file):
        super().__init__(
            "格式转换",
            "PyAV 内置 FFmpeg 库 · 容器、编码器、滤镜与高级参数完整可调",
            "swap")
        self.on_select_file = on_select_file
        self._src_path = None
        self._info = None
        self._worker = None
        self._running = False
        self._custom_name = False
        self._loading = False
        self._last_output = None
        self._batch_paths = []
        self._batch_folder = None
        self._has_subtitles = False

        self.select_btn = make_button(
            "选择媒体文件", "plus", "primary",
            lambda: self.on_select_file(None, "media"))
        self.add_action(self.select_btn)

        self.folder_btn = make_button(
            "选择文件夹", "folderOpen", "ghost", self._choose_input_folder)
        self.add_action(self.folder_btn)

        self.drop = DropZone(
            "把音频、视频或文件夹拖到这里",
            "支持单个文件，也支持整个文件夹批量转换",
            "swap", lambda: self.on_select_file(None, "media"))
        self.body.addWidget(self.drop, 1)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.horizontalScrollBar().setEnabled(False)
        self.workbench = QWidget()
        self._build_workbench()
        self.scroll.setWidget(self.workbench)
        self.body.addWidget(self.scroll, 1)

        self._build_footer()
        self.scroll.hide()
        self.footer.hide()

    # ------------------------------------------------------------------
    # 构建界面
    # ------------------------------------------------------------------

    def _build_workbench(self):
        layout = QVBoxLayout(self.workbench)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(12)

        layout.addWidget(self._build_source_card())

        tabs_card = GlassCard(margins=(18, 14, 18, 14), spacing=10)
        segment_row = QHBoxLayout()
        segment_row.setContentsMargins(0, 0, 0, 0)
        segment_row.setSpacing(4)
        self._segment_buttons = []
        for index, name in enumerate(self.SEGMENTS):
            button = QPushButton(name)
            button.setObjectName("segBtn")
            button.setCheckable(True)
            button.setFixedHeight(30)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, i=index: self._switch_segment(i))
            segment_row.addWidget(button)
            self._segment_buttons.append(button)
        segment_row.addStretch()
        tabs_card.vbox.addLayout(segment_row)
        tabs_card.vbox.addWidget(make_separator())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_basic_tab())
        self.stack.addWidget(self._build_video_tab())
        self.stack.addWidget(self._build_audio_tab())
        self.stack.addWidget(self._build_filter_tab())
        self.stack.addWidget(self._build_advanced_tab())
        self.stack.setMinimumHeight(292)
        tabs_card.vbox.addWidget(self.stack, 1)

        layout.addWidget(tabs_card)
        layout.addStretch()
        self._switch_segment(0)

    def _build_source_card(self):
        card = GlassCard(margins=(20, 12, 20, 12), spacing=7)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.source_name = QLabel("—")
        self.source_name.setObjectName("sourceName")
        self.source_path = QLabel("")
        self.source_path.setObjectName("hint")
        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        text_box.addWidget(self.source_name)
        text_box.addWidget(self.source_path)
        row.addLayout(text_box, 1)

        self.replace_btn = make_button(
            "更换文件", "folderOpen", "ghost", self._replace_source)
        self.replace_btn.setFixedHeight(32)
        row.addWidget(self.replace_btn)
        card.vbox.addLayout(row)

        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(8)
        self.chips_row.addStretch()
        card.vbox.addLayout(self.chips_row)
        return card

    def _tab_shell(self):
        scroll = QScrollArea()
        scroll.setObjectName("tabScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.horizontalScrollBar().setEnabled(False)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(13)
        scroll.setWidget(content)
        return scroll, layout

    def _field(self, text, widget, hint=None):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        layout.addWidget(widget)
        if hint:
            note = QLabel(hint)
            note.setObjectName("hint")
            note.setWordWrap(True)
            layout.addWidget(note)
        return box

    def _line(self, placeholder="", text=""):
        edit = QLineEdit(text)
        edit.setObjectName("fieldInput")
        edit.setPlaceholderText(placeholder)
        edit.setFixedHeight(36)
        return edit

    def _build_basic_tab(self):
        scroll, layout = self._tab_shell()

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        self.container_combo = SelectBox()
        self.container_combo.setMinimumWidth(190)
        for key, spec in container_specs().items():
            kind = "视频" if spec["kind"] == "video" else "音频"
            self.container_combo.addItem(
                f"{spec['label']} · {kind}", key)
        self.container_combo.currentIndexChanged.connect(
            self._on_container_changed)
        grid.addWidget(self._field("输出容器", self.container_combo), 0, 0)

        self.container_note = QLabel("")
        self.container_note.setObjectName("hint")
        self.container_note.setWordWrap(True)
        grid.addWidget(self._field("容器说明", self.container_note), 0, 1)

        self.video_combo = SelectBox()
        self.video_combo.setMinimumWidth(170)
        self.video_combo.currentIndexChanged.connect(
            self._on_video_codec_changed)
        grid.addWidget(self._field("视频编码", self.video_combo), 1, 0)

        self.audio_combo = SelectBox()
        self.audio_combo.setMinimumWidth(160)
        self.audio_combo.currentIndexChanged.connect(
            self._on_audio_codec_changed)
        grid.addWidget(self._field("音频编码", self.audio_combo), 1, 1)

        self.subtitle_combo = SelectBox()
        self.subtitle_combo.setMinimumWidth(140)
        grid.addWidget(self._field("字幕", self.subtitle_combo), 1, 2)
        layout.addLayout(grid)

        stream_grid = QGridLayout()
        stream_grid.setContentsMargins(0, 0, 0, 0)
        stream_grid.setHorizontalSpacing(14)
        stream_grid.setVerticalSpacing(12)

        self.video_stream_combo = SelectBox()
        self.video_stream_combo.setMinimumWidth(170)
        stream_grid.addWidget(
            self._field("视频流", self.video_stream_combo), 0, 0)

        self.audio_stream_combo = SelectBox()
        self.audio_stream_combo.setMinimumWidth(160)
        stream_grid.addWidget(
            self._field("音频流", self.audio_stream_combo), 0, 1)

        self.subtitle_stream_combo = SelectBox()
        self.subtitle_stream_combo.setMinimumWidth(140)
        stream_grid.addWidget(
            self._field("字幕流", self.subtitle_stream_combo), 0, 2)
        self.stream_grid_widget = QWidget()
        self.stream_grid_widget.setLayout(stream_grid)
        layout.addWidget(self.stream_grid_widget)

        layout.addWidget(make_separator())

        trim_grid = QGridLayout()
        trim_grid.setContentsMargins(0, 0, 0, 0)
        trim_grid.setHorizontalSpacing(14)
        trim_grid.setVerticalSpacing(12)
        self.start_edit = self._line("留空从头开始，例如 00:00:12.5")
        self.duration_edit = self._line("留空到结尾，例如 30 或 1:20")
        trim_grid.addWidget(
            self._field("起始时间", self.start_edit), 0, 0)
        trim_grid.addWidget(
            self._field("截取时长", self.duration_edit), 0, 1)
        layout.addLayout(trim_grid)

        layout.addWidget(make_separator())

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.dir_edit = self._line("与源文件同目录")
        self.browse_btn = make_button(
            "浏览…", "folderOpen", "ghost", self._choose_dir)
        self.browse_btn.setFixedHeight(36)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(self.browse_btn)
        dir_box = QWidget()
        dir_box.setLayout(dir_row)
        self.dir_field = self._field("输出目录", dir_box)

        name_grid = QGridLayout()
        name_grid.setContentsMargins(0, 0, 0, 0)
        name_grid.setHorizontalSpacing(14)
        self.name_edit = self._line("输出文件名")
        self.name_edit.textEdited.connect(self._on_name_edited)
        name_grid.addWidget(self.dir_field, 0, 0)
        name_grid.addWidget(self._field("文件名", self.name_edit), 0, 1)
        layout.addLayout(name_grid)
        layout.addStretch()
        return scroll

    def _build_video_tab(self):
        scroll, layout = self._tab_shell()

        note = QLabel(
            "参数留空表示自动。编码器选择“复制原流”或“移除视频”时，本页参数不生效。")
        note.setObjectName("sectionNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.video_controls = []

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        self.rate_mode_combo = SelectBox()
        self.rate_mode_combo.addItem("自动", "auto")
        self.rate_mode_combo.addItem("恒定质量 CRF", "crf")
        self.rate_mode_combo.addItem("目标码率 ABR", "abr")
        self.rate_mode_combo.currentIndexChanged.connect(
            self._refresh_enabled)
        grid.addWidget(
            self._field("码率控制", self.rate_mode_combo), 0, 0)

        self.crf_edit = self._line("例如 23")
        grid.addWidget(self._field("CRF 质量", self.crf_edit), 0, 1)

        self.vbitrate_edit = self._line("例如 4000（kbps）")
        grid.addWidget(
            self._field("目标码率", self.vbitrate_edit, "单位 kbps"), 0, 2)

        self.maxrate_edit = self._line("例如 6000（kbps）")
        grid.addWidget(
            self._field("最大码率", self.maxrate_edit, "单位 kbps"), 1, 0)

        self.res_combo = SelectBox()
        for label, size in (
                ("原始分辨率", None),
                ("3840 × 2160", (3840, 2160)),
                ("2560 × 1440", (2560, 1440)),
                ("1920 × 1080", (1920, 1080)),
                ("1280 × 720", (1280, 720)),
                ("854 × 480", (854, 480)),
                ("640 × 360", (640, 360)),
                ("自定义", "custom")):
            self.res_combo.addItem(label, size)
        self.res_combo.currentIndexChanged.connect(self._on_resolution_changed)
        grid.addWidget(
            self._field("分辨率预设", self.res_combo), 1, 1)

        self.scale_mode_combo = SelectBox()
        self.scale_mode_combo.addItem("等比缩放 + 黑边", "fit")
        self.scale_mode_combo.addItem("拉伸填满", "stretch")
        grid.addWidget(
            self._field("缩放方式", self.scale_mode_combo), 1, 2)

        self.width_edit = self._line("宽，留空自动")
        grid.addWidget(self._field("宽度", self.width_edit), 2, 0)

        self.height_edit = self._line("高，留空自动")
        grid.addWidget(self._field("高度", self.height_edit), 2, 1)

        self.fps_edit = self._line("例如 29.97")
        grid.addWidget(self._field("帧率", self.fps_edit), 2, 2)

        self.pixfmt_combo = SelectBox()
        grid.addWidget(
            self._field("像素格式", self.pixfmt_combo), 3, 0)

        self.preset_combo = SelectBox()
        self.preset_combo.addItem("自动", None)
        for name in VIDEO_PRESETS:
            self.preset_combo.addItem(name, name)
        grid.addWidget(self._field("编码预设", self.preset_combo), 3, 1)

        self.tune_combo = SelectBox()
        self.tune_combo.addItem("自动", None)
        for name in VIDEO_TUNES:
            self.tune_combo.addItem(name, name)
        grid.addWidget(self._field("Tune 调优", self.tune_combo), 3, 2)

        self.profile_edit = self._line("例如 high / main10")
        grid.addWidget(self._field("编码档次", self.profile_edit), 4, 0)

        self.gop_edit = self._line("例如 250")
        grid.addWidget(self._field("关键帧间隔", self.gop_edit), 4, 1)

        self.bframes_edit = self._line("例如 3")
        grid.addWidget(self._field("最大 B 帧", self.bframes_edit), 4, 2)

        self.threads_edit = self._line("例如 0（自动）")
        grid.addWidget(self._field("线程数", self.threads_edit), 5, 0)

        layout.addLayout(grid)

        self.video_controls += [
            self.rate_mode_combo, self.crf_edit, self.vbitrate_edit,
            self.maxrate_edit, self.res_combo, self.scale_mode_combo,
            self.width_edit, self.height_edit, self.fps_edit,
            self.pixfmt_combo, self.preset_combo, self.tune_combo,
            self.profile_edit, self.gop_edit, self.bframes_edit,
            self.threads_edit,
        ]

        layout.addWidget(section_title("编码器参数覆盖"))
        self.video_options = KeyValueEditor(
            "参数名，例如 x264-params", "值，例如 ref=4")
        layout.addWidget(self.video_options)
        layout.addStretch()
        return scroll

    def _build_audio_tab(self):
        scroll, layout = self._tab_shell()

        note = QLabel(
            "采样率会自动适配编码器；例如 Opus 会优先使用 48 kHz。")
        note.setObjectName("sectionNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.audio_controls = []

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        self.abitrate_edit = self._line("例如 192（kbps）")
        grid.addWidget(
            self._field("音频码率", self.abitrate_edit, "单位 kbps"), 0, 0)

        self.sample_rate_combo = SelectBox()
        self.sample_rate_combo.addItem("保持原样", None)
        for rate in SAMPLE_RATES:
            self.sample_rate_combo.addItem(f"{rate} Hz", rate)
        grid.addWidget(
            self._field("采样率", self.sample_rate_combo), 0, 1)

        self.layout_combo = SelectBox()
        for label, value in AUDIO_LAYOUTS:
            self.layout_combo.addItem(label, value)
        grid.addWidget(
            self._field("声道", self.layout_combo), 0, 2)

        self.volume_edit = self._line("100")
        self.volume_edit.setText("100")
        grid.addWidget(
            self._field("音量", self.volume_edit, "100 = 原始音量，200 = 两倍"), 1, 0)

        layout.addLayout(grid)
        self.audio_controls += [
            self.abitrate_edit, self.sample_rate_combo, self.layout_combo,
            self.volume_edit,
        ]

        layout.addWidget(section_title("编码器参数覆盖"))
        self.audio_options = KeyValueEditor(
            "参数名，例如 vbr", "值，例如 4")
        layout.addWidget(self.audio_options)
        layout.addStretch()
        return scroll

    def _build_filter_tab(self):
        scroll, layout = self._tab_shell()

        layout.addWidget(section_title("视频滤镜"))
        self.video_filter_edit = self._line(
            "例如 hflip; scale=1280:-2; unsharp=5:5:1.0")
        layout.addWidget(self.video_filter_edit)
        video_presets = (
            ("水平翻转", "hflip"), ("垂直翻转", "vflip"),
            ("旋转 90°", "transpose=1"), ("去隔行", "yadif"),
            ("锐化", "unsharp=5:5:1.0"), ("轻微降噪", "hqdn3d"),
            ("裁剪 16:9", "crop=iw:iw*9/16"),
        )
        layout.addLayout(self._preset_row(
            self.video_filter_edit, video_presets))

        layout.addSpacing(4)
        layout.addWidget(section_title("音频滤镜"))
        self.audio_filter_edit = self._line(
            "例如 loudnorm=I=-16:TP=-1.5:LRA=11")
        layout.addWidget(self.audio_filter_edit)
        audio_presets = (
            ("响度标准化", "loudnorm=I=-16:TP=-1.5:LRA=11"),
            ("高通 80Hz", "highpass=f=80"),
            ("低通 12kHz", "lowpass=f=12000"),
            ("淡入 2 秒", "afade=t=in:st=0:d=2"),
            ("1.25 倍速", "atempo=1.25"),
        )
        layout.addLayout(self._preset_row(
            self.audio_filter_edit, audio_presets))

        note = QLabel(
            "多个滤镜用分号分隔，参数中的逗号会原样保留；滤镜顺序按填写顺序执行。")
        note.setObjectName("sectionNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return scroll

    def _preset_row(self, edit, presets):
        row = QHBoxLayout()
        row.setSpacing(6)
        for label, expression in presets:
            button = QPushButton(label)
            button.setObjectName("miniBtn")
            button.setFixedHeight(26)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, text=expression, target=edit:
                self._append_filter(target, text))
            row.addWidget(button)
        row.addStretch()
        return row

    def _append_filter(self, edit, expression):
        current = edit.text().strip()
        if not current:
            edit.setText(expression)
        elif expression not in current:
            edit.setText(current.rstrip("; ") + "; " + expression)

    def _build_advanced_tab(self):
        scroll, layout = self._tab_shell()

        self.metadata_toggle = self._toggle_row(
            layout, "复制元数据",
            "把标题、艺术家、专辑等标签写入输出文件。", True)
        self.chapters_toggle = self._toggle_row(
            layout, "复制章节", "保留章节标记（容器支持时）。", True)
        self.shortest_toggle = self._toggle_row(
            layout, "最短流优先",
            "以最短的音视频流为准结束输出，对应 -shortest。", False)
        self.faststart_toggle = self._toggle_row(
            layout, "快速启动",
            "MP4 / MOV 把索引写到文件头，便于网页边下边播。", True)

        layout.addWidget(make_separator())
        layout.addWidget(section_title("容器参数覆盖"))
        self.container_options = KeyValueEditor(
            "参数名，例如 movflags", "值，例如 +faststart")
        layout.addWidget(self.container_options)

        note = QLabel(
            "自定义参数会直接传给 FFmpeg；不同容器/编码器支持的键不同，"
            "遇到不支持的值时会在状态栏提示错误。")
        note.setObjectName("sectionNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return scroll

    def _toggle_row(self, layout, title, note, checked):
        row = QHBoxLayout()
        row.setSpacing(12)
        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("valueLabel")
        hint = QLabel(note)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        text_box.addWidget(label)
        text_box.addWidget(hint)
        row.addLayout(text_box, 1)
        toggle = ToggleSwitch(checked)
        row.addWidget(toggle)
        layout.addLayout(row)
        return toggle

    def _build_footer(self):
        self.footer = GlassCard(margins=(20, 13, 20, 13), spacing=9)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        self.footer.vbox.addWidget(self.progress)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.status_label = QLabel("准备就绪")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        row.addWidget(self.status_label, 1)

        self.open_dir_btn = make_button(
            "打开目录", "folderOpen", "quiet", self._open_output_dir)
        self.open_dir_btn.hide()
        row.addWidget(self.open_dir_btn)

        self.cancel_btn = make_button(
            "取消", "close", "ghost", self._cancel_convert)
        self.cancel_btn.hide()
        row.addWidget(self.cancel_btn)

        self.convert_btn = make_button(
            "开始转换", "swap", "primary", self._start_convert)
        row.addWidget(self.convert_btn)
        self.footer.vbox.addLayout(row)
        self.body.addWidget(self.footer)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _switch_segment(self, index):
        for i, button in enumerate(self._segment_buttons):
            button.setChecked(i == index)
        self.stack.setCurrentIndex(index)

    def _on_name_edited(self, text):
        self._custom_name = bool(text.strip())

    def _set_status(self, text, name="muted"):
        self.status_label.setText(text)
        self.status_label.setObjectName(name)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setToolTip(text)

    def _set_controls_enabled(self, enabled):
        for widget in (self.select_btn, self.replace_btn,
                       self.container_combo, self.video_combo,
                       self.audio_combo, self.subtitle_combo,
                       self.video_stream_combo, self.audio_stream_combo,
                       self.subtitle_stream_combo, self.start_edit,
                       self.duration_edit, self.dir_edit, self.name_edit,
                       self.browse_btn,
                       self.video_filter_edit, self.audio_filter_edit,
                       self.convert_btn):
            widget.setEnabled(enabled)
        for widget in self.video_controls + self.audio_controls:
            widget.setEnabled(enabled)
        for editor in (self.video_options, self.audio_options,
                       self.container_options):
            editor.setEnabled(enabled)
        for toggle in (self.metadata_toggle, self.chapters_toggle,
                       self.shortest_toggle, self.faststart_toggle):
            toggle.setEnabled(enabled)
        if enabled:
            self._refresh_enabled()

    def _refresh_enabled(self):
        if self._loading or not self._info:
            return
        video_codec = self.video_combo.currentData()
        audio_codec = self.audio_combo.currentData()
        video_active = video_codec not in (None, "none", "copy")
        audio_active = audio_codec not in (None, "none", "copy")

        for widget in self.video_controls:
            widget.setEnabled(video_active)
        for widget in self.audio_controls:
            widget.setEnabled(audio_active)

        rate_mode = self.rate_mode_combo.currentData()
        self.crf_edit.setEnabled(video_active and rate_mode == "crf")
        self.vbitrate_edit.setEnabled(video_active and rate_mode == "abr")
        self.maxrate_edit.setEnabled(video_active and rate_mode == "abr")

        custom_size = self.res_combo.currentData() == "custom"
        self.width_edit.setEnabled(video_active and custom_size)
        self.height_edit.setEnabled(video_active and custom_size)

        self.video_stream_combo.setEnabled(
            not self._batch_paths and video_codec not in (None, "none"))
        self.audio_stream_combo.setEnabled(
            not self._batch_paths and audio_codec not in (None, "none"))
        self.subtitle_stream_combo.setEnabled(
            not self._batch_paths
            and self.subtitle_combo.currentData() == "copy")
        self.subtitle_combo.setEnabled(self._has_subtitles)
        self.faststart_toggle.setEnabled(
            bool(CONTAINER_SPECS[self._container_key()].get("faststart")))
        self.name_edit.setEnabled(
            not self._running and not self._batch_paths)

    def _container_key(self):
        return self.container_combo.currentData() or "mp4"

    def _on_container_changed(self):
        if self._loading or not self._info:
            return
        key = self._container_key()
        spec = CONTAINER_SPECS[key]
        self.container_note.setText(spec["note"])
        self._populate_codec_combos(key)
        if key == "gif":
            if not self.fps_edit.text().strip():
                self.fps_edit.setText("10")
            if not self.width_edit.text().strip() \
                    and not self.height_edit.text().strip():
                self.width_edit.setText("640")
                self.height_edit.setText("360")
        self._sync_output_name()
        self._refresh_enabled()

    def _on_video_codec_changed(self):
        if self._loading or not self._info:
            return
        codec = self.video_combo.currentData()
        self.pixfmt_combo.blockSignals(True)
        self.pixfmt_combo.clear()
        self.pixfmt_combo.addItem("自动", None)
        if codec not in (None, "none", "copy"):
            for name in video_pix_fmts(codec):
                self.pixfmt_combo.addItem(name, name)
        self.pixfmt_combo.blockSignals(False)
        self._refresh_enabled()

    def _on_audio_codec_changed(self):
        if self._loading or not self._info:
            return
        codec = self.audio_combo.currentData()
        self._refresh_enabled()
        if codec in (None, "none", "copy"):
            return
        rates = audio_sample_rates(codec)
        if rates:
            current = self.sample_rate_combo.currentData()
            if current and current not in rates:
                adjusted = pick_sample_rate(codec, current)
                index = self.sample_rate_combo.findData(adjusted)
                if index >= 0:
                    self.sample_rate_combo.setCurrentIndex(index)
        self.abitrate_edit.setEnabled(True)

    def _on_resolution_changed(self):
        value = self.res_combo.currentData()
        if value == "custom":
            self._refresh_enabled()
            return
        if value is None:
            self.width_edit.clear()
            self.height_edit.clear()
        else:
            self.width_edit.setText(str(value[0]))
            self.height_edit.setText(str(value[1]))
        self._refresh_enabled()

    def _choose_dir(self):
        start = self.dir_edit.text().strip()
        if not start and self._src_path:
            start = os.path.dirname(self._src_path)
        folder = choose_directory(self, "选择输出目录", start)
        if folder:
            self.dir_edit.setText(folder)
            self._sync_output_name(keep_dir=True)

    def _choose_input_folder(self):
        start = self._batch_folder or (
            os.path.dirname(self._src_path) if self._src_path else "")
        folder = choose_directory(self, "选择要转换的文件夹", start)
        if folder:
            self.load_folder(folder)

    def _replace_source(self):
        if self._batch_paths:
            self._choose_input_folder()
        else:
            self.on_select_file(None, "media")

    def _sync_output_name(self, keep_dir=False):
        if not self._src_path:
            return
        if self._batch_paths:
            self.name_edit.blockSignals(True)
            self.name_edit.setText("按原文件名自动命名")
            self.name_edit.setToolTip(
                "批量模式下每个文件保留原文件名，只替换为输出格式的扩展名")
            self.name_edit.blockSignals(False)
            self._refresh_enabled()
            return
        spec = CONTAINER_SPECS[self._container_key()]
        stem = os.path.splitext(os.path.basename(self._src_path))[0]
        if not keep_dir:
            folder = self.dir_edit.text().strip() or os.path.dirname(
                self._src_path)
            self.dir_edit.setText(folder)
        if self._custom_name and self.name_edit.text().strip():
            base = os.path.splitext(self.name_edit.text().strip())[0]
            self.name_edit.setText(base + spec["ext"])
        else:
            self.name_edit.setText(stem + spec["ext"])
            self._custom_name = False

    # ------------------------------------------------------------------
    # 载入文件
    # ------------------------------------------------------------------

    def _populate_source(self, info):
        self.source_name.setText(os.path.basename(info["path"]))
        self.source_path.setText(info["path"])
        self.source_path.setToolTip(info["path"])

        chips = [os.path.splitext(info["path"])[1].upper().lstrip(".")
                 or info["format"].upper() or "未知容器",
                 format_seconds(info["duration"]),
                 self._size_text(info["size"])]
        videos = [s for s in info["streams"] if s["type"] == "video"]
        audios = [s for s in info["streams"] if s["type"] == "audio"]
        if videos:
            stream = videos[0]
            chips.append(
                f"{stream['codec'].upper()} · {stream['width']}×"
                f"{stream['height']} · {stream['fps']:g} fps")
        if audios:
            stream = audios[0]
            chips.append(
                f"{stream['codec'].upper()} · "
                f"{stream['sample_rate'] / 1000:g} kHz · "
                f"{stream['channels']} ch")
        subtitles = [s for s in info["streams"] if s["type"] == "subtitle"]
        if subtitles:
            chips.append(f"{len(subtitles)} 条字幕")
        self._set_chips(chips)

    def _set_chips(self, texts):
        while self.chips_row.count():
            item = self.chips_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for text in texts:
            self.chips_row.addWidget(make_chip(text))
        self.chips_row.addStretch()

    @staticmethod
    def _size_text(size):
        value = float(size or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.0f} {unit}" if unit == "B" \
                    else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    def _populate_codec_combos(self, key):
        spec = CONTAINER_SPECS[key]
        self.container_note.setText(spec["note"])
        self._loading = True
        try:
            videos = [s for s in self._info["streams"] if s["type"] == "video"]
            audios = [s for s in self._info["streams"] if s["type"] == "audio"]
            subs = [s for s in self._info["streams"] if s["type"] == "subtitle"]

            self.video_combo.clear()
            if videos and spec["video"]:
                self.video_combo.addItem("复制原流（不重编码）", "copy")
            self.video_combo.addItem("移除视频", "none")
            video_codecs = available_video_codecs(key)
            for name in video_codecs:
                self.video_combo.addItem(
                    VIDEO_CODEC_LABELS.get(name, name), name)
            if videos and video_codecs:
                preferred = "libx264" if "libx264" in video_codecs \
                    else video_codecs[0]
                self.video_combo.setCurrentIndex(
                    self.video_combo.findData(preferred))

            self.audio_combo.clear()
            if audios and spec["audio"]:
                self.audio_combo.addItem("复制原流（不重编码）", "copy")
            self.audio_combo.addItem("移除音频", "none")
            audio_codecs = available_audio_codecs(key)
            for name in audio_codecs:
                self.audio_combo.addItem(
                    AUDIO_CODEC_LABELS.get(name, name), name)
            if audios and audio_codecs:
                preferred = "aac" if "aac" in audio_codecs \
                    else audio_codecs[0]
                self.audio_combo.setCurrentIndex(
                    self.audio_combo.findData(preferred))

            self.subtitle_combo.clear()
            if subs and spec.get("subtitles"):
                self.subtitle_combo.addItem("复制字幕", "copy")
            self.subtitle_combo.addItem("移除字幕", "none")
            self._has_subtitles = bool(subs and spec.get("subtitles"))

            self._fill_stream_combo(
                self.video_stream_combo, videos, "video")
            self._fill_stream_combo(
                self.audio_stream_combo, audios, "audio")
            self._fill_stream_combo(
                self.subtitle_stream_combo, subs, "subtitle")
            self.stream_grid_widget.setVisible(
                len(videos) > 1 or len(audios) > 1 or len(subs) > 1)
        finally:
            self._loading = False
        self._on_video_codec_changed()
        self._on_audio_codec_changed()

    def _fill_stream_combo(self, combo, streams, kind):
        combo.blockSignals(True)
        combo.clear()
        if not streams:
            combo.addItem("无", None)
            combo.blockSignals(False)
            return
        for stream in streams:
            if kind == "video":
                label = (f"#{stream['index']} · {stream['codec']} · "
                         f"{stream['width']}×{stream['height']}")
            elif kind == "audio":
                label = (f"#{stream['index']} · {stream['codec']} · "
                         f"{stream['sample_rate'] / 1000:g} kHz · "
                         f"{stream['channels']} ch")
            else:
                label = f"#{stream['index']} · {stream['codec']}"
            combo.addItem(label, stream["index"])
        combo.blockSignals(False)

    def show_empty(self):
        if self._running:
            return
        self._src_path = None
        self._info = None
        self._batch_paths = []
        self._batch_folder = None
        self.drop.show()
        self.scroll.hide()
        self.footer.hide()

    def show_file(self, file_path):
        if self._running or not file_path or not os.path.isfile(file_path):
            return
        self._batch_paths = []
        self._batch_folder = None
        try:
            info = probe_media(file_path)
        except Exception as error:
            self._src_path = None
            self._info = None
            self.drop.show()
            self.scroll.hide()
            self.footer.hide()
            Toast.show_message(self, str(error)[:80], "error")
            return

        self._src_path = file_path
        self._info = info
        self._custom_name = False
        self._last_output = None
        self.replace_btn.setText("更换文件")
        self._populate_source(info)

        self.dir_edit.setText(os.path.dirname(file_path))
        self.start_edit.clear()
        self.duration_edit.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_status("准备就绪")
        self.open_dir_btn.hide()
        self.convert_btn.setText("开始转换")
        self.convert_btn.setEnabled(True)

        key = default_container_for(info)
        index = self.container_combo.findData(key)
        if index < 0:
            index = 0
        self._loading = True
        self.container_combo.setCurrentIndex(index)
        self._loading = False
        self._populate_codec_combos(key)
        self._sync_output_name()
        self._reset_quality_defaults()
        self._refresh_enabled()

        self.drop.hide()
        self.scroll.show()
        self.footer.show()
        self.scroll.verticalScrollBar().setValue(0)
        self._switch_segment(0)
        for index in range(self.stack.count()):
            tab = self.stack.widget(index)
            if isinstance(tab, QScrollArea):
                tab.verticalScrollBar().setValue(0)

    @staticmethod
    def _scan_media(folder):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return []
        paths = []
        for name in names:
            if name.startswith("."):
                continue
            path = os.path.join(folder, name)
            if os.path.isfile(path) and \
                    os.path.splitext(name)[1].lower() in MEDIA_EXTS:
                paths.append(path)
        return paths

    def load_folder(self, folder):
        if self._running:
            return
        paths = self._scan_media(folder)
        if not paths:
            Toast.show_message(self, "文件夹内没有可转换的媒体文件", "warning")
            return

        self.show_file(paths[0])
        if self._src_path != paths[0]:
            return
        self._batch_paths = paths
        self._batch_folder = folder
        self.replace_btn.setText("更换文件夹")

        has_video = any(
            os.path.splitext(path)[1].lower() in VIDEO_EXTS for path in paths)
        if has_video:
            key = "mp4"
            index = self.container_combo.findData(key)
            if index >= 0 and self._container_key() != key:
                self._loading = True
                self.container_combo.setCurrentIndex(index)
                self._loading = False
                self._populate_codec_combos(key)
            if self.video_combo.currentData() in (None, "none"):
                codecs = available_video_codecs(key)
                if codecs:
                    preferred = "libx264" if "libx264" in codecs \
                        else codecs[0]
                    found = self.video_combo.findData(preferred)
                    if found >= 0:
                        self.video_combo.setCurrentIndex(found)

        total_size = sum(os.path.getsize(path) for path in paths)
        self.source_name.setText(
            f"{os.path.basename(folder)} · {len(paths)} 个文件")
        self.source_path.setText(folder)
        self.source_path.setToolTip(folder)
        self._set_chips([
            "批量模式",
            f"{len(paths)} 个文件",
            self._size_text(total_size),
            CONTAINER_SPECS[self._container_key()]["label"],
        ])

        output_dir = os.path.join(folder, "转换输出")
        self.dir_edit.setText(output_dir)
        self._sync_output_name()
        self.stream_grid_widget.hide()
        self._set_status(f"批量模式 · 点击开始转换将处理 {len(paths)} 个文件")
        self._refresh_enabled()
        self.scroll.verticalScrollBar().setValue(0)

    def _reset_quality_defaults(self):
        self.rate_mode_combo.setCurrentIndex(
            self.rate_mode_combo.findData("crf"))
        self.crf_edit.setText("23")
        self.vbitrate_edit.clear()
        self.maxrate_edit.clear()
        self.res_combo.setCurrentIndex(0)
        self.width_edit.clear()
        self.height_edit.clear()
        self.fps_edit.clear()
        self.preset_combo.setCurrentIndex(
            self.preset_combo.findData("veryfast"))
        self.tune_combo.setCurrentIndex(0)
        self.profile_edit.clear()
        self.gop_edit.clear()
        self.bframes_edit.clear()
        self.threads_edit.clear()
        self.abitrate_edit.setText("192")
        self.sample_rate_combo.setCurrentIndex(0)
        self.layout_combo.setCurrentIndex(0)
        self.volume_edit.setText("100")
        self.video_filter_edit.clear()
        self.audio_filter_edit.clear()
        self.video_options.clear()
        self.audio_options.clear()
        self.container_options.clear()
        self.metadata_toggle.setChecked(True, emit=False)
        self.chapters_toggle.setChecked(True, emit=False)
        self.shortest_toggle.setChecked(False, emit=False)
        self.faststart_toggle.setChecked(True, emit=False)

    # ------------------------------------------------------------------
    # 转换
    # ------------------------------------------------------------------

    @staticmethod
    def _number(edit):
        text = edit.text().strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            raise ConvertError(f"“{text}”不是有效的数字")

    def _collect_config(self):
        if not self._info:
            raise ConvertError("请先选择文件")
        key = self._container_key()
        spec = CONTAINER_SPECS[key]

        start = parse_time(self.start_edit.text())
        if self.start_edit.text().strip() and start is None:
            raise ConvertError("起始时间格式不正确")
        duration = parse_time(self.duration_edit.text())
        if self.duration_edit.text().strip() and duration is None:
            raise ConvertError("截取时长格式不正确")
        if duration is not None and duration <= 0:
            raise ConvertError("截取时长必须大于 0")
        if start and self._info["duration"] and start >= self._info["duration"]:
            raise ConvertError("起始时间超过了文件时长")

        width = self._number(self.width_edit)
        height = self._number(self.height_edit)
        crf = self._number(self.crf_edit)
        vbitrate = self._number(self.vbitrate_edit)
        maxrate = self._number(self.maxrate_edit)
        fps = self._number(self.fps_edit)
        gop = self._number(self.gop_edit)
        bframes = self._number(self.bframes_edit)
        threads = self._number(self.threads_edit)
        abitrate = self._number(self.abitrate_edit)
        volume = self._number(self.volume_edit)

        video_codec = self.video_combo.currentData() or "none"
        audio_codec = self.audio_combo.currentData() or "none"
        subtitle_codec = self.subtitle_combo.currentData() or "none"
        if spec["kind"] == "audio":
            video_codec = "none"
        if not spec["audio"]:
            audio_codec = "none"

        if video_codec == "none" and audio_codec == "none" \
                and subtitle_codec == "none":
            raise ConvertError("请至少保留视频或音频")

        rate_mode = self.rate_mode_combo.currentData()
        if rate_mode == "auto":
            crf = None
            vbitrate = None
        elif rate_mode == "crf":
            vbitrate = None
        elif rate_mode == "abr":
            crf = None

        video = {
            "codec": video_codec,
            "stream": self.video_stream_combo.currentData(),
            "crf": int(crf) if crf is not None else None,
            "bitrate": vbitrate,
            "maxrate": maxrate,
            "width": int(width) if width else None,
            "height": int(height) if height else None,
            "scale_mode": self.scale_mode_combo.currentData(),
            "fps": fps,
            "pix_fmt": self.pixfmt_combo.currentData(),
            "preset": self.preset_combo.currentData(),
            "tune": self.tune_combo.currentData(),
            "profile": self.profile_edit.text().strip(),
            "gop": int(gop) if gop else None,
            "bframes": int(bframes) if bframes is not None else None,
            "threads": int(threads) if threads is not None else None,
            "filter": self.video_filter_edit.text().strip(),
            "options": self.video_options.values(),
        }
        audio = {
            "codec": audio_codec,
            "stream": self.audio_stream_combo.currentData(),
            "bitrate": abitrate,
            "sample_rate": self.sample_rate_combo.currentData(),
            "layout": self.layout_combo.currentData(),
            "volume": volume,
            "filter": self.audio_filter_edit.text().strip(),
            "options": self.audio_options.values(),
        }
        subtitle = {
            "codec": subtitle_codec,
            "stream": self.subtitle_stream_combo.currentData(),
        }
        config = {
            "container_key": key,
            "container": spec["format"],
            "video": video,
            "audio": audio,
            "subtitle": subtitle,
            "start": start or 0.0,
            "duration": duration,
            "metadata": self.metadata_toggle.isChecked(),
            "chapters": self.chapters_toggle.isChecked(),
            "shortest": self.shortest_toggle.isChecked(),
            "faststart": self.faststart_toggle.isChecked(),
            "container_options": self.container_options.values(),
        }
        return config

    def _output_path(self, spec):
        folder = self.dir_edit.text().strip() or os.path.dirname(self._src_path)
        name = self.name_edit.text().strip()
        if not name:
            name = os.path.basename(default_output_path(
                self._src_path, self._container_key()))
        if not name.lower().endswith(spec["ext"].lower()):
            name += spec["ext"]
        return os.path.join(folder, name)

    def _start_convert(self):
        if self._running or not self._src_path:
            return
        try:
            config = self._collect_config()
        except ConvertError as error:
            Toast.show_message(self, str(error), "warning")
            return

        if self._batch_paths:
            self._start_batch(config)
            return

        key = self._container_key()
        spec = CONTAINER_SPECS[key]
        dst = self._output_path(spec)
        folder = os.path.dirname(dst)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as error:
            Toast.show_message(self, f"无法创建目录：{error}", "error")
            return

        if os.path.exists(dst):
            reply = QMessageBox.question(
                self, "文件已存在",
                f"「{os.path.basename(dst)}」已存在，是否覆盖？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        self._last_output = dst
        self._running = True
        self._set_controls_enabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.show()
        self.open_dir_btn.hide()
        self.convert_btn.setText("正在转换…")
        self._set_status(f"正在转换 → {os.path.basename(dst)}")

        worker = ConvertWorker(
            self._src_path, dst, config, self)
        worker.progressed.connect(self._on_progress)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.aborted.connect(self._on_aborted)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _batch_jobs(self, spec):
        folder = self.dir_edit.text().strip() or os.path.join(
            self._batch_folder or os.path.dirname(self._src_path), "转换输出")
        os.makedirs(folder, exist_ok=True)
        jobs = []
        used = set()
        for src in self._batch_paths:
            stem = os.path.splitext(os.path.basename(src))[0]
            dst = os.path.join(folder, stem + spec["ext"])
            counter = 1
            while os.path.exists(dst) or dst in used \
                    or os.path.abspath(dst) == os.path.abspath(src):
                dst = os.path.join(
                    folder, f"{stem} ({counter}){spec['ext']}")
                counter += 1
            used.add(dst)
            jobs.append((src, dst))
        return jobs

    def _start_batch(self, config):
        spec = CONTAINER_SPECS[self._container_key()]
        try:
            jobs = self._batch_jobs(spec)
        except OSError as error:
            Toast.show_message(self, f"无法创建目录：{error}", "error")
            return
        if not jobs:
            Toast.show_message(self, "没有可转换的文件", "warning")
            return

        self._last_output = jobs[0][1]
        self._running = True
        self._set_controls_enabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.show()
        self.open_dir_btn.hide()
        self.convert_btn.setText("正在转换…")
        self._set_status(f"准备转换 {len(jobs)} 个文件…")

        worker = BatchConvertWorker(jobs, config, self)
        worker.file_started.connect(self._on_batch_file)
        worker.progressed.connect(self._on_batch_progress)
        worker.succeeded.connect(self._on_batch_success)
        worker.aborted.connect(self._on_aborted)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _on_progress(self, percent):
        self.progress.setValue(percent)
        if percent > 0:
            self._set_status(f"正在转换… {percent}%")

    def _on_batch_progress(self, percent):
        self.progress.setValue(percent)

    def _on_batch_file(self, name, index, total):
        self._set_status(f"正在转换 {index}/{total} · {name}")

    def _on_success(self, dst):
        self._running = False
        self.progress.setValue(100)
        size_text = self._size_text(
            os.path.getsize(dst) if os.path.exists(dst) else 0)
        name = os.path.basename(dst)
        self._set_status(f"已完成 · {name} · {size_text}", "okText")
        self.convert_btn.setText("再次转换")
        self.cancel_btn.hide()
        self.open_dir_btn.show()
        self._set_controls_enabled(True)
        Toast.show_message(self, "转换完成", "success")

    def _on_batch_success(self, done, errors):
        self._running = False
        if not errors:
            self.progress.setValue(100)
            self._set_status(f"已完成 {done} 个文件", "okText")
            Toast.show_message(self, f"已完成 {done} 个文件", "success")
        else:
            self._set_status(
                f"完成 {done} 个，失败 {len(errors)} 个", "warnText")
            self.status_label.setToolTip("\n".join(errors))
            Toast.show_message(
                self, f"完成 {done} 个，失败 {len(errors)} 个", "warning")
        self.convert_btn.setText("再次转换")
        self.cancel_btn.hide()
        self.open_dir_btn.show()
        self._set_controls_enabled(True)

    def _on_failure(self, message):
        self._running = False
        self.progress.setValue(0)
        self._set_status(f"转换失败：{message}", "errorText")
        self.convert_btn.setText("重新转换")
        self.cancel_btn.hide()
        self.open_dir_btn.hide()
        self._set_controls_enabled(True)
        Toast.show_message(self, "转换失败，详情见状态栏", "error")

    def _on_aborted(self):
        self._running = False
        self.progress.setValue(0)
        if self._batch_paths:
            self._set_status("已取消，已完成的文件会保留")
        else:
            self._set_status("已取消")
        self.convert_btn.setText("开始转换")
        self.cancel_btn.hide()
        self.open_dir_btn.hide()
        self._set_controls_enabled(True)

    def _on_worker_finished(self):
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self.cancel_btn.setEnabled(True)

    def _cancel_convert(self):
        if not self._running or self._worker is None:
            return
        self._worker.cancel()
        self.cancel_btn.setEnabled(False)
        self._set_status("正在取消…")

    def _open_output_dir(self):
        if not self._last_output:
            return
        folder = os.path.dirname(self._last_output)
        if os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def shutdown(self):
        """关闭窗口前停止转码线程，避免 QThread 被销毁时仍在运行。"""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(5000)

    def on_drop_path(self, path):
        if os.path.isdir(path):
            self.load_folder(path)
            return
        if os.path.isfile(path):
            self.on_select_file(path)
