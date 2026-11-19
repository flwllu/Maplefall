import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QVBoxLayout
)

from ..metadata import FORMAT_DEFAULT, FORMAT_OPTIONS
from ..widgets import (
    BasePage, DropZone, GlassCard, SelectBox, make_button, make_separator,
    section_title
)


class ExportPage(BasePage):
    def __init__(self, on_select_file, on_rename, on_format_changed):
        super().__init__("单曲重命名", "按标签信息生成规范、整洁的新文件名", "tag")
        self.on_select_file = on_select_file
        self.on_rename = on_rename
        self.on_format_changed = on_format_changed

        format_label = QLabel("命名格式")
        format_label.setObjectName("fieldLabel")

        self.fmt_combo = SelectBox()
        self.fmt_combo.setFixedWidth(186)
        for key in FORMAT_OPTIONS:
            self.fmt_combo.addItem(FORMAT_OPTIONS[key][0], key)
        self.fmt_combo.setCurrentIndex(
            list(FORMAT_OPTIONS.keys()).index(FORMAT_DEFAULT))
        self.fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)

        self.rename_btn = make_button(
            "执行重命名", "tag", "primary", self.on_rename)
        self.rename_btn.hide()
        self.add_action(self.rename_btn)
        self.add_action(make_button(
            "选择文件", "plus", "ghost", lambda: self.on_select_file(None)))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        toolbar.addWidget(format_label)
        toolbar.addWidget(self.fmt_combo)
        toolbar_hint = QLabel("只影响文件名，不改动音频内容")
        toolbar_hint.setObjectName("hint")
        toolbar.addWidget(toolbar_hint)
        toolbar.addStretch()
        self.body.addLayout(toolbar)

        self.drop = DropZone(
            "把音频文件拖到这里", "根据标签自动生成「艺术家 - 歌曲名」等命名格式",
            "tag", lambda: self.on_select_file(None))
        self.body.addWidget(self.drop, 1)

        self.preview_card = self._build_card()
        self.preview_card.hide()
        self.body.addWidget(self.preview_card)
        self.body.addStretch()

    # ------------------------------------------------------------------

    def _build_card(self):
        card = GlassCard(margins=(24, 20, 24, 20), spacing=14)
        card.vbox.addWidget(section_title("文件名预览"))

        original_row = QHBoxLayout()
        original_row.setSpacing(12)
        original_label = QLabel("原始文件名")
        original_label.setObjectName("fieldLabel")
        original_label.setFixedWidth(68)
        self.original_value = QLabel("—")
        self.original_value.setObjectName("valueLabel")
        self.original_value.setWordWrap(True)
        original_row.addWidget(original_label, 0, Qt.AlignTop)
        original_row.addWidget(self.original_value, 1)
        card.vbox.addLayout(original_row)

        card.vbox.addWidget(make_separator())

        self.preview_panel = GlassCard(margins=(18, 15, 18, 15), spacing=0)
        self.preview_panel.setObjectName("previewPanel")
        self.preview_text = QLabel("—")
        self.preview_text.setObjectName("previewName")
        self.preview_text.setWordWrap(True)
        self.preview_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_panel.vbox.addWidget(self.preview_text)
        card.vbox.addWidget(self.preview_panel)

        self.warn_label = QLabel("")
        self.warn_label.setObjectName("warnText")
        self.warn_label.setWordWrap(True)
        self.warn_label.hide()
        card.vbox.addWidget(self.warn_label)

        hint = QLabel("重命名只修改文件名，不会改变音频内容与标签")
        hint.setObjectName("hint")
        card.vbox.addWidget(hint)
        return card

    # ------------------------------------------------------------------

    def _on_fmt_changed(self):
        key = self.fmt_combo.currentData()
        if key:
            self.on_format_changed(key)

    def get_format(self):
        return self.fmt_combo.currentData() or FORMAT_DEFAULT

    def get_format_label(self):
        key = self.fmt_combo.currentData() or FORMAT_DEFAULT
        return FORMAT_OPTIONS[key][0]

    def show_empty(self):
        self.preview_card.hide()
        self.rename_btn.hide()
        self.drop.show()

    def _refresh_panel_style(self, object_name):
        self.preview_panel.setObjectName(object_name)
        self.preview_panel.style().unpolish(self.preview_panel)
        self.preview_panel.style().polish(self.preview_panel)

    def show_preview(self, new_name_with_ext, has_meta, original_name=""):
        self.drop.hide()
        self.preview_card.show()
        self.original_value.setText(original_name or "—")
        self.original_value.setToolTip(original_name or "")

        if has_meta:
            self._refresh_panel_style("previewPanel")
            self.preview_text.setObjectName("previewName")
            self.preview_text.setStyleSheet("")
            self.preview_text.setText(new_name_with_ext)
            self.warn_label.hide()
            self.rename_btn.setEnabled(True)
            self.rename_btn.setText("执行重命名")
            self.rename_btn.setStyleSheet("")
            self.rename_btn.show()
        else:
            self._refresh_panel_style("previewPanelWarn")
            self.preview_text.setObjectName("previewNameWarn")
            self.preview_text.setStyleSheet("")
            self.preview_text.setText(new_name_with_ext)
            self.warn_label.setText("该文件缺少标签信息，请先在「编辑元数据」中补充")
            self.warn_label.show()
            self.rename_btn.hide()

        self.preview_text.style().unpolish(self.preview_text)
        self.preview_text.style().polish(self.preview_text)

    def mark_done(self, new_name_with_ext):
        self._refresh_panel_style("previewPanelDone")
        self.preview_text.setObjectName("previewNameDone")
        self.preview_text.setText(f"{new_name_with_ext}   ✓ 已完成")
        self.preview_text.style().unpolish(self.preview_text)
        self.preview_text.style().polish(self.preview_text)
        self.warn_label.hide()
        self.rename_btn.setText("已完成")
        self.rename_btn.setEnabled(False)

    def on_drop_path(self, path):
        if os.path.isfile(path):
            self.on_select_file(path)
