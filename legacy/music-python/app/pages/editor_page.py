import os

from PySide6.QtWidgets import (
    QGridLayout, QLabel, QLineEdit, QVBoxLayout
)

from ..widgets import BasePage, DropZone, GlassCard, make_button, section_title

FIELDS = [
    ("歌曲名称", "title"),
    ("艺术家", "artist"),
    ("专辑名称", "album"),
    ("专辑艺术家", "albumartist"),
    ("音乐风格", "genre"),
    ("发行年份", "date"),
    ("曲目序号", "tracknumber"),
    ("作曲", "composer"),
]


class EditorPage(BasePage):
    def __init__(self, on_select_file, on_save, on_import_json):
        super().__init__("编辑元数据", "直接修改并写回音频文件标签", "edit")
        self.on_select_file = on_select_file
        self.on_save = on_save
        self.on_import_json = on_import_json
        self.inputs = {}

        self.select_btn = make_button(
            "选择文件", "plus", "ghost", lambda: self.on_select_file(None))
        self.import_btn = make_button(
            "从 JSON 导入", "download", "ghost", self.on_import_json)
        self.save_btn = make_button(
            "保存更改", "save", "primary", self._on_save_clicked)
        self.import_btn.hide()
        self.save_btn.hide()
        self.add_action(self.select_btn)
        self.add_action(self.import_btn)
        self.add_action(self.save_btn)

        self.drop = DropZone(
            "把音频文件拖到这里", "选择文件后即可编辑标题、艺术家、专辑等信息",
            "edit", lambda: self.on_select_file(None))
        self.body.addWidget(self.drop, 1)

        self.edit_card = self._build_card()
        self.edit_card.hide()
        self.body.addWidget(self.edit_card)
        self.body.addStretch()

    # ------------------------------------------------------------------

    def _build_card(self):
        card = GlassCard(margins=(24, 20, 24, 22), spacing=16)
        card.vbox.addWidget(section_title("标签信息"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(14)
        for index, (label_text, key) in enumerate(FIELDS):
            holder = QVBoxLayout()
            holder.setSpacing(6)

            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            holder.addWidget(label)

            line_edit = QLineEdit()
            line_edit.setObjectName("fieldInput")
            line_edit.setFixedHeight(36)
            line_edit.setPlaceholderText(f"输入{label_text}…")
            line_edit.setClearButtonEnabled(False)
            holder.addWidget(line_edit)

            grid.addLayout(holder, index // 2, index % 2)
            self.inputs[key] = line_edit

        card.vbox.addLayout(grid)

        hint = QLabel("保存后会立即写入文件，原始封面与音质参数不受影响")
        hint.setObjectName("hint")
        card.vbox.addWidget(hint)
        return card

    # ------------------------------------------------------------------

    def _on_save_clicked(self):
        fields = {}
        for key, line_edit in self.inputs.items():
            value = line_edit.text().strip()
            if value:
                fields[key] = value
        self.on_save(fields)

    def show_empty(self):
        self.drop.show()
        self.edit_card.hide()
        self.save_btn.hide()
        self.import_btn.hide()

    def populate(self, metadata):
        self.drop.hide()
        self.edit_card.show()
        for key, line_edit in self.inputs.items():
            line_edit.setText(metadata.get(key) or "")
        self.save_btn.show()
        self.import_btn.show()

    def on_drop_path(self, path):
        if os.path.isfile(path):
            self.on_select_file(path)
