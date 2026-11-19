import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from ..metadata import format_duration
from ..widgets import (
    BasePage, CoverView, DropZone, GlassCard, StatTile, make_button,
    make_chip, make_separator
)


class IntroPage(BasePage):
    def __init__(self, on_select_file, on_export_json):
        super().__init__("歌曲简介", "查看音频标签与音质信息", "note")
        self.on_select_file = on_select_file
        self.on_export_json = on_export_json

        self.export_btn = make_button(
            "导出 JSON", "download", "ghost", lambda: self.on_export_json())
        self.export_btn.hide()
        self.add_action(self.export_btn)
        self.add_action(make_button(
            "选择音频文件", "plus", "primary",
            lambda: self.on_select_file(None)))

        self.drop = DropZone(
            "把音频文件拖到这里", "支持 MP3 / FLAC / M4A / WAV / OGG / WMA",
            "note", lambda: self.on_select_file(None))
        self.body.addWidget(self.drop, 1)

        self.card = self._build_card()
        self.card.hide()
        self.body.addWidget(self.card)
        self.body.addStretch()

    # ------------------------------------------------------------------

    def _build_card(self):
        card = GlassCard(margins=(24, 22, 24, 20), spacing=18)

        hero = QHBoxLayout()
        hero.setSpacing(18)
        self.cover = CoverView(108, 16)
        hero.addWidget(self.cover)

        info = QVBoxLayout()
        info.setSpacing(4)
        info.addStretch()
        self.title_label = QLabel("未知歌曲")
        self.title_label.setObjectName("songTitle")
        self.title_label.setWordWrap(True)
        self.artist_label = QLabel("未知艺术家")
        self.artist_label.setObjectName("songArtist")
        self.album_label = QLabel("—")
        self.album_label.setObjectName("songAlbum")
        info.addWidget(self.title_label)
        info.addWidget(self.artist_label)
        info.addWidget(self.album_label)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.format_chip = make_chip("—")
        self.duration_chip = make_chip("—", accent=True)
        chips.addWidget(self.format_chip)
        chips.addWidget(self.duration_chip)
        chips.addStretch()
        info.addSpacing(6)
        info.addLayout(chips)
        info.addStretch()
        hero.addLayout(info, 1)
        card.vbox.addLayout(hero)

        card.vbox.addWidget(make_separator())

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.tile_format = StatTile("文件格式")
        self.tile_duration = StatTile("时长")
        self.tile_bitrate = StatTile("比特率")
        self.tile_samplerate = StatTile("采样率")
        self.tile_channels = StatTile("声道")
        self.tile_size = StatTile("文件大小")
        for index, tile in enumerate((
                self.tile_format, self.tile_duration, self.tile_bitrate,
                self.tile_samplerate, self.tile_channels, self.tile_size)):
            grid.addWidget(tile, index // 3, index % 3)
        card.vbox.addLayout(grid)

        card.vbox.addWidget(make_separator())

        file_row = QHBoxLayout()
        file_row.setSpacing(12)
        file_label = QLabel("当前文件")
        file_label.setObjectName("fieldLabel")
        file_label.setFixedWidth(60)
        self.file_label = QLabel("—")
        self.file_label.setObjectName("valueLabel")
        self.file_label.setWordWrap(True)
        self.file_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        file_row.addWidget(file_label)
        file_row.addWidget(self.file_label, 1)
        card.vbox.addLayout(file_row)

        return card

    # ------------------------------------------------------------------

    def show_info(self, file_name, title, artist, album, fmt, size,
                  props=None, cover=None):
        self.drop.hide()
        self.card.show()
        self.export_btn.show()

        self.cover.set_cover(cover)

        self.title_label.setText(title or "未知歌曲")
        self.title_label.setStyleSheet(
            "" if title else "color: #6E6E73;")
        self.artist_label.setText(artist or "未知艺术家")
        self.artist_label.setStyleSheet(
            "" if artist else "color: #6E6E73;")
        self.album_label.setText(album or "未填写专辑")

        props = props or {}
        duration = format_duration(props.get("length")) \
            if props.get("length") else "—"
        self.format_chip.setText(f"{fmt}  ·  {size}")
        self.duration_chip.setText(duration)

        self.tile_format.set_value(fmt)
        self.tile_duration.set_value(duration)
        self.tile_bitrate.set_value(
            f"{props['bitrate'] // 1000} kbps" if props.get("bitrate") else "—")
        self.tile_samplerate.set_value(
            f"{props['sample_rate'] / 1000:.1f} kHz"
            if props.get("sample_rate") else "—")
        channels = props.get("channels")
        channel_map = {1: "单声道", 2: "立体声", 0: "—", None: "—"}
        self.tile_channels.set_value(
            channel_map.get(channels, f"{channels} 声道"))
        self.tile_size.set_value(size)

        self.file_label.setText(file_name)
        self.file_label.setToolTip(file_name)

    def show_empty(self):
        self.card.hide()
        self.export_btn.hide()
        self.drop.show()

    def on_drop_path(self, path):
        if os.path.isfile(path):
            self.on_select_file(path)
