import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout
)

from ..widgets import (
    BasePage, CoverView, DropZone, GlassCard, make_button, make_chip,
    section_title
)


class CoverPage(BasePage):
    def __init__(self, on_select_file, on_extract, on_embed, on_remove):
        super().__init__("封面管理", "查看、提取、替换或删除歌曲封面", "image")
        self.on_select_file = on_select_file
        self.on_extract_cover = on_extract
        self.on_embed_cover = on_embed
        self.on_remove_cover = on_remove

        self.add_action(make_button(
            "选择音频文件", "plus", "primary",
            lambda: self.on_select_file(None)))

        self.drop = DropZone(
            "把音频文件拖到这里", "支持查看和写入内嵌封面",
            "image", lambda: self.on_select_file(None))
        self.body.addWidget(self.drop, 1)

        self.cover_card = self._build_card()
        self.cover_card.hide()
        self.body.addWidget(self.cover_card)
        self.body.addStretch()

    # ------------------------------------------------------------------

    def _build_card(self):
        card = GlassCard(margins=(24, 22, 24, 22), spacing=20)

        row = QHBoxLayout()
        row.setSpacing(24)

        self.cover_view = CoverView(262, 20)
        row.addWidget(self.cover_view, 0, Qt.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(section_title("封面图片"))

        desc = QLabel("封面会写入音频文件的标签中，在播放器和系统中直接显示。")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        right.addWidget(desc)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.size_chip = make_chip("暂无封面")
        self.type_chip = make_chip("未内嵌", accent=True)
        chips.addWidget(self.size_chip)
        chips.addWidget(self.type_chip)
        chips.addStretch()
        right.addLayout(chips)

        right.addSpacing(4)
        self.embed_btn = make_button(
            "更换封面", "upload", "primary", self._on_embed_clicked)
        self.extract_btn = make_button(
            "提取封面", "download", "ghost", self.on_extract_cover)
        self.remove_btn = make_button(
            "删除封面", "trash", "danger", self._on_remove_clicked)
        for button in (self.embed_btn, self.extract_btn, self.remove_btn):
            button.setMinimumWidth(148)
            right.addWidget(button, 0, Qt.AlignLeft)

        hint = QLabel("建议使用正方形图片，支持 JPG / PNG / BMP / GIF")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        right.addSpacing(4)
        right.addWidget(hint)
        right.addStretch()

        row.addLayout(right, 1)
        card.vbox.addLayout(row)
        return card

    # ------------------------------------------------------------------

    def _on_embed_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择封面图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp *.gif);;所有文件 (*)")
        if path:
            self.on_embed_cover(path)

    def _on_remove_clicked(self):
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这首歌的封面图片吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.on_remove_cover()

    def show_empty(self):
        self.drop.show()
        self.cover_card.hide()

    def show_cover(self, pixmap, has_cover):
        self.drop.hide()
        self.cover_card.show()
        if has_cover and pixmap and not pixmap.isNull():
            self.cover_view.set_cover(pixmap)
            self.size_chip.setText(f"{pixmap.width()} × {pixmap.height()}")
            self.type_chip.setText("已内嵌")
            self.extract_btn.setEnabled(True)
            self.remove_btn.setEnabled(True)
        else:
            self.cover_view.clear_cover()
            self.size_chip.setText("暂无封面")
            self.type_chip.setText("未内嵌")
            self.extract_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)

    def on_drop_path(self, path):
        if os.path.isfile(path):
            self.on_select_file(path)
