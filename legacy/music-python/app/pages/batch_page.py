import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QVBoxLayout
)

from ..icons import icon as make_icon
from ..metadata import (
    FORMAT_DEFAULT, FORMAT_OPTIONS, generate_filename, get_full_metadata,
    scan_folder
)
from ..widgets import (
    BasePage, DropZone, SelectBox, choose_directory, make_button, make_chip
)


class BatchPage(BasePage):
    def __init__(self):
        super().__init__("批量重命名", "一次整理整个文件夹中的歌曲", "folder")
        self.files = []

        format_label = QLabel("命名格式")
        format_label.setObjectName("fieldLabel")

        self.fmt_combo = SelectBox()
        self.fmt_combo.setFixedWidth(180)
        for key in FORMAT_OPTIONS:
            self.fmt_combo.addItem(FORMAT_OPTIONS[key][0], key)
        self.fmt_combo.setCurrentIndex(
            list(FORMAT_OPTIONS.keys()).index(FORMAT_DEFAULT))
        self.fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)

        self.folder_btn = make_button(
            "选择文件夹", "folderOpen", "ghost", self._select_folder)
        self.add_action(self.folder_btn)

        self.batch_rename_btn = make_button(
            "批量重命名", "tag", "primary", self._do_batch_rename)
        self.batch_rename_btn.hide()
        self.add_action(self.batch_rename_btn)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        toolbar.addWidget(format_label)
        toolbar.addWidget(self.fmt_combo)
        toolbar_hint = QLabel("无标签的文件会自动跳过")
        toolbar_hint.setObjectName("hint")
        toolbar.addWidget(toolbar_hint)
        toolbar.addStretch()
        self.body.addLayout(toolbar)

        self.drop = DropZone(
            "把文件夹或音频拖到这里", "自动读取标签并按所选格式批量生成文件名",
            "folder", self._select_folder)
        self.body.addWidget(self.drop, 1)

        self.list_panel = self._build_list_panel()
        self.list_panel.hide()
        self.body.addWidget(self.list_panel, 1)

    # ------------------------------------------------------------------

    def _build_list_panel(self):
        from PySide6.QtWidgets import QFrame
        panel = QFrame()
        panel.setObjectName("glassCard")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)

        summary = QHBoxLayout()
        summary.setSpacing(8)
        self.count_chip = make_chip("共 0 首")
        self.valid_chip = make_chip("0 首可重命名", accent=True)
        self.missing_chip = make_chip("0 首无标签")
        summary.addWidget(self.count_chip)
        summary.addWidget(self.valid_chip)
        summary.addWidget(self.missing_chip)
        summary.addStretch()
        layout.addLayout(summary)

        self.file_list = QListWidget()
        self.file_list.setObjectName("batchList")
        self.file_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.file_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.file_list.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.file_list, 1)
        return panel

    def _on_fmt_changed(self):
        if self.files:
            self._load_files([f["path"] for f in self.files])

    def _select_folder(self):
        folder = choose_directory(self, "选择歌曲文件夹")
        if folder:
            files = scan_folder(folder)
            if files:
                self._load_files(files)

    def _load_files(self, file_paths):
        if not file_paths:
            return
        fmt = self.fmt_combo.currentData() or FORMAT_DEFAULT

        self.files.clear()
        self.file_list.clear()
        renamed_count = 0
        no_meta_count = 0

        for path in file_paths:
            old_name = os.path.basename(path)
            ext = os.path.splitext(old_name)[1]
            meta = get_full_metadata(path)
            new_base = generate_filename(meta["title"], meta["artist"], fmt)

            self.files.append({
                "path": path, "old_name": old_name,
                "title": meta["title"], "artist": meta["artist"],
                "new_base": new_base, "ext": ext,
            })

            item = QListWidgetItem()
            if new_base:
                renamed_count += 1
                item.setText(f"  {new_base}{ext}")
                item.setIcon(make_icon("check", "#1B7F4B", 16))
                item.setToolTip(f"原文件名：{old_name}")
            else:
                no_meta_count += 1
                item.setText(f"  {old_name}    ·  缺少标签，将跳过")
                item.setIcon(make_icon("alert", "#B25000", 16))
                item.setForeground(QColor("#8E8E93"))
                item.setToolTip("该文件没有可读取的标题或艺术家标签")
            item.setSizeHint(QSize(0, 44))
            self.file_list.addItem(item)

        self.drop.hide()
        self.list_panel.show()

        total = len(self.files)
        self.count_chip.setText(f"共 {total} 首")
        self.valid_chip.setText(f"{renamed_count} 首可重命名")
        self.missing_chip.setText(f"{no_meta_count} 首无标签")
        self.missing_chip.setVisible(no_meta_count > 0)

        if renamed_count > 0:
            self.batch_rename_btn.setText(f"批量重命名 · {renamed_count} 首")
            self.batch_rename_btn.setEnabled(True)
            self.batch_rename_btn.show()
        else:
            self.batch_rename_btn.hide()

    def _do_batch_rename(self):
        if not self.files:
            return
        valid = [f for f in self.files if f["new_base"]]
        confirm = QMessageBox.question(
            self, "确认批量重命名",
            f"将对 {len(valid)} 首歌曲进行重命名，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return

        success = 0
        skipped = 0
        failed = 0
        for f in self.files:
            if not f["new_base"]:
                skipped += 1
                continue
            folder = os.path.dirname(f["path"])
            new_path = os.path.join(folder, f["new_base"] + f["ext"])
            if os.path.exists(new_path) and new_path != f["path"]:
                skipped += 1
                continue
            try:
                os.rename(f["path"], new_path)
                f["path"] = new_path
                success += 1
            except OSError:
                failed += 1

        for index, f in enumerate(self.files):
            item = self.file_list.item(index)
            if not f["new_base"]:
                continue
            if os.path.basename(f["path"]) == f["new_base"] + f["ext"]:
                item.setText(f"  {f['new_base']}{f['ext']}")
                item.setIcon(make_icon("check", "#1B7F4B", 16))
                item.setForeground(QColor("#1D1D1F"))
            else:
                item.setText(f"  {f['old_name']}    ·  重命名失败")
                item.setIcon(make_icon("alert", "#C0392B", 16))
                item.setForeground(QColor("#8E8E93"))

        self.batch_rename_btn.setText("✓ 已完成")
        self.batch_rename_btn.setEnabled(False)

        message = f"重命名完成\n\n成功 {success} 首"
        if skipped:
            message += f"\n跳过 {skipped} 首"
        if failed:
            message += f"\n失败 {failed} 首"
        QMessageBox.information(self, "批量重命名结果", message)

    def on_drop_path(self, path):
        if os.path.isdir(path):
            files = scan_folder(path)
            if files:
                self._load_files(files)
        elif os.path.isfile(path):
            self._load_files([path])
