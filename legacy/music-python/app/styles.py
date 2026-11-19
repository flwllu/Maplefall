"""黑白极简主题（macOS / Windows / Linux 共用一套 QSS）。"""

import sys

FONT_FAMILIES = {
    "darwin": ["SF Pro Text", "PingFang SC", "Helvetica Neue"],
    "win32": ["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"],
}.get(sys.platform, ["Noto Sans CJK SC", "Noto Sans", "Source Han Sans SC"])

ACCENT = "#111111"
ACCENT_SOFT = "#111111"
TEXT = "#1D1D1F"
TEXT_2 = "#6E6E73"
TEXT_3 = "#8E8E93"

_QSS = r"""
* {
    outline: none;
}

QWidget {
    color: #1D1D1F;
    font-size: 13px;
    background: transparent;
}

/* ================= 标题栏 ================= */

QWidget#titleBar {
    background: transparent;
    border-bottom: 1px solid #ECECF0;
}

QLabel#brandName {
    font-size: 13px;
    font-weight: 600;
    color: #111111;
}

QLabel#brandCaption {
    font-size: 10px;
    color: #A1A1A6;
}

QLabel#titleDivider {
    background: #E5E5EA;
    max-width: 1px;
    min-width: 1px;
}

QLabel#fileChip {
    background: #F5F5F7;
    border: 1px solid #E5E5EA;
    border-radius: 7px;
    padding: 3px 10px;
    color: #6E6E73;
    font-size: 11px;
}

QPushButton#winBtn {
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0;
}

QPushButton#winBtn:hover {
    background: #F0F0F2;
}

QPushButton#winBtn:pressed {
    background: #E5E5EA;
}

QPushButton#closeBtn {
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0;
}

QPushButton#closeBtn:hover {
    background: #E5484D;
}

QPushButton#closeBtn:pressed {
    background: #C93A3F;
}

QPushButton#macClose, QPushButton#macMin, QPushButton#macMax {
    border: none;
    border-radius: 7px;
    padding: 0;
}

QPushButton#macClose { background: #FF5F57; }
QPushButton#macMin   { background: #FEBC2E; }
QPushButton#macMax   { background: #28C840; }

QPushButton#macClose:hover { background: #FF7A73; }
QPushButton#macMin:hover   { background: #FFD05B; }
QPushButton#macMax:hover   { background: #4BE05F; }

/* ================= 侧边栏 ================= */

QFrame#sidebar {
    background: #FAFAFA;
    border-right: 1px solid #ECECF0;
}

QLabel#navSection {
    font-size: 10px;
    font-weight: 700;
    color: #A1A1A6;
    padding: 16px 12px 6px 12px;
}

QPushButton#navBtn {
    text-align: left;
    padding: 0 12px;
    border: 1px solid transparent;
    border-radius: 9px;
    background: transparent;
    color: #3A3A3C;
    font-size: 13px;
}

QPushButton#navBtn:hover {
    background: #F0F0F2;
    color: #111111;
}

QPushButton#navBtn:checked {
    background: #E9E9ED;
    border: 1px solid #DCDCE1;
    color: #111111;
    font-weight: 600;
}

QLabel#sidebarFoot {
    font-size: 10px;
    color: #A1A1A6;
}

/* ================= 页面 ================= */

QLabel#pageTitle {
    font-size: 23px;
    font-weight: 700;
    color: #111111;
}

QLabel#pageSubtitle {
    font-size: 12px;
    color: #8E8E93;
}

QFrame#glassCard {
    background: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 14px;
}

QFrame#softCard {
    background: #FAFAFA;
    border: 1px solid #ECECF0;
    border-radius: 10px;
}

QFrame#dropZone {
    background: #FAFAFA;
    border: 1px dashed #C7C7CC;
    border-radius: 14px;
}

QFrame#previewPanel {
    background: #F7F7F9;
    border: 1px solid #E5E5EA;
    border-radius: 10px;
}

QFrame#previewPanelWarn {
    background: #FFF8F0;
    border: 1px solid #F0D9BD;
    border-radius: 10px;
}

QFrame#previewPanelDone {
    background: #F3FAF5;
    border: 1px solid #CDE8D6;
    border-radius: 10px;
}

QLabel#sectionTitle {
    font-size: 13px;
    font-weight: 600;
    color: #111111;
}

QLabel#fieldLabel {
    font-size: 11px;
    color: #8E8E93;
}

QLabel#valueLabel {
    font-size: 13px;
    color: #1D1D1F;
}

QLabel#muted {
    font-size: 12px;
    color: #8E8E93;
}

QLabel#hint {
    font-size: 11px;
    color: #A1A1A6;
}

QLabel#songTitle {
    font-size: 22px;
    font-weight: 700;
    color: #111111;
}

QLabel#songArtist {
    font-size: 15px;
    color: #48484A;
}

QLabel#songAlbum {
    font-size: 12px;
    color: #8E8E93;
}

QLabel#statValue {
    font-size: 15px;
    font-weight: 600;
    color: #111111;
}

QLabel#statLabel {
    font-size: 10px;
    color: #A1A1A6;
}

QLabel#chip {
    background: #F2F2F7;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    padding: 3px 10px;
    font-size: 11px;
    color: #48484A;
}

QLabel#chipAccent {
    background: #111111;
    border: 1px solid #111111;
    border-radius: 8px;
    padding: 3px 10px;
    font-size: 11px;
    color: #FFFFFF;
}

QLabel#warnText {
    color: #B25000;
    font-size: 12px;
}

QLabel#okText {
    color: #1B7F4B;
    font-size: 12px;
}

QLabel#errorText {
    color: #C0392B;
    font-size: 12px;
}

QLabel#previewName {
    font-size: 17px;
    font-weight: 600;
    color: #111111;
}

QLabel#previewNameDone {
    font-size: 17px;
    font-weight: 600;
    color: #1B7F4B;
}

QLabel#previewNameWarn {
    font-size: 17px;
    font-weight: 600;
    color: #B25000;
}

/* ================= 按钮 ================= */

QPushButton {
    font-size: 13px;
}

QPushButton#primaryBtn {
    background: #111111;
    border: 1px solid #111111;
    border-radius: 8px;
    padding: 0 18px;
    color: #FFFFFF;
    font-weight: 600;
}

QPushButton#primaryBtn:hover {
    background: #2C2C2E;
    border-color: #2C2C2E;
}

QPushButton#primaryBtn:pressed {
    background: #000000;
    border-color: #000000;
}

QPushButton#primaryBtn:disabled {
    background: #E5E5EA;
    border-color: #E5E5EA;
    color: #A1A1A6;
}

QPushButton#ghostBtn {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 0 16px;
    color: #1D1D1F;
}

QPushButton#ghostBtn:hover {
    background: #F5F5F7;
    border-color: #C7C7CC;
}

QPushButton#ghostBtn:pressed {
    background: #E9E9ED;
}

QPushButton#ghostBtn:disabled {
    background: #FAFAFA;
    border-color: #ECECF0;
    color: #B0B0B5;
}

QPushButton#dangerBtn {
    background: #FFF1F0;
    border: 1px solid #F3C2C0;
    border-radius: 8px;
    padding: 0 16px;
    color: #B3261E;
}

QPushButton#dangerBtn:hover {
    background: #FFE4E2;
    border-color: #E9A7A4;
}

QPushButton#dangerBtn:disabled {
    background: #FAFAFA;
    border-color: #ECECF0;
    color: #B0B0B5;
}

QPushButton#quietBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 0 10px;
    color: #6E6E73;
    font-size: 12px;
}

QPushButton#quietBtn:hover {
    background: #F0F0F2;
    color: #111111;
}

/* ================= 输入控件 ================= */

QLineEdit#fieldInput {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 8px 12px;
    color: #1D1D1F;
    font-size: 13px;
    selection-background-color: #D1D1D6;
    selection-color: #111111;
    placeholder-text-color: #B0B0B5;
}

QLineEdit#fieldInput:hover {
    border-color: #B0B0B5;
}

QLineEdit#fieldInput:focus {
    border-color: #111111;
    background: #FFFFFF;
}

QLineEdit#fieldInput:disabled {
    background: #F5F5F7;
    border-color: #ECECF0;
    color: #B0B0B5;
}

QComboBox#select {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 8px;
    padding: 0 34px 0 12px;
    color: #1D1D1F;
    font-size: 13px;
}

QComboBox#select:hover {
    border-color: #B0B0B5;
}

QComboBox#select:focus {
    border-color: #111111;
}

QComboBox#select:disabled {
    color: #B0B0B5;
    border-color: #ECECF0;
    background: #F5F5F7;
}

QComboBox#select::drop-down {
    border: none;
    width: 30px;
}

QComboBox#select::down-arrow {
    image: none;
    width: 0;
    height: 0;
}

QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    padding: 5px;
    color: #1D1D1F;
    outline: none;
    selection-background-color: #F0F0F2;
    selection-color: #111111;
}

QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 6px;
}

QProgressBar {
    background: #ECECF0;
    border: none;
    border-radius: 3px;
    text-align: center;
}

QProgressBar::chunk {
    border-radius: 3px;
    background: #111111;
}

/* ================= 列表 ================= */

QListWidget#batchList {
    background: transparent;
    border: none;
    outline: none;
    font-size: 13px;
}

QListWidget#batchList::item {
    color: #1D1D1F;
    background: #FFFFFF;
    border: 1px solid #ECECF0;
    border-radius: 8px;
    padding: 10px 14px;
    margin: 2px 0;
}

QListWidget#batchList::item:hover {
    background: #FAFAFA;
}

QListWidget#batchList::item:selected {
    background: #F0F0F2;
    border-color: #DCDCE1;
}

/* ================= 滚动条 ================= */

QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #D1D1D6;
    border-radius: 3px;
    min-height: 32px;
}

QScrollBar::handle:vertical:hover {
    background: #B0B0B5;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
    background: transparent;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: transparent;
    height: 9px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background: #D1D1D6;
    border-radius: 3px;
    min-width: 32px;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
    background: transparent;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ================= 滚动与分段控件 ================= */

QScrollArea#pageScroll,
QScrollArea#tabScroll {
    background: transparent;
    border: none;
}

QScrollArea#pageScroll > QWidget > QWidget,
QScrollArea#tabScroll > QWidget > QWidget {
    background: transparent;
}

QPushButton#segBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 0 15px;
    color: #6E6E73;
    font-size: 12px;
}

QPushButton#segBtn:hover {
    background: #F0F0F2;
    color: #111111;
}

QPushButton#segBtn:checked {
    background: #111111;
    border-color: #111111;
    color: #FFFFFF;
    font-weight: 600;
}

QPushButton#miniBtn {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 7px;
    padding: 0 11px;
    color: #48484A;
    font-size: 11px;
}

QPushButton#miniBtn:hover {
    background: #F0F0F2;
    border-color: #C7C7CC;
    color: #111111;
}

QLabel#sectionNote {
    font-size: 11px;
    color: #A1A1A6;
}

QLabel#sourceName {
    font-size: 14px;
    font-weight: 600;
    color: #111111;
}

QFrame#kvRow {
    background: transparent;
    border: none;
}

QLabel#streamTag {
    background: #F2F2F7;
    border: 1px solid #E5E5EA;
    border-radius: 7px;
    padding: 3px 9px;
    font-size: 11px;
    color: #48484A;
}

/* ================= 对话框 ================= */

QMessageBox {
    background-color: #FFFFFF;
}

QMessageBox QLabel {
    color: #1D1D1F;
    font-size: 13px;
}

QMessageBox QPushButton {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 7px;
    padding: 7px 18px;
    color: #1D1D1F;
    min-width: 68px;
}

QMessageBox QPushButton:hover {
    background: #F5F5F7;
}

QMessageBox QPushButton:default {
    background: #111111;
    border-color: #111111;
    color: #FFFFFF;
    font-weight: 600;
}

QFileDialog {
    background: #FFFFFF;
}

QFileDialog QListView,
QFileDialog QTreeView {
    background: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    outline: none;
}

QFileDialog QHeaderView::section {
    background: #FAFAFA;
    color: #6E6E73;
    border: none;
    border-bottom: 1px solid #E5E5EA;
    padding: 5px 8px;
    font-size: 11px;
}

QFileDialog QPushButton {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 7px;
    padding: 7px 18px;
    color: #1D1D1F;
    min-width: 68px;
}

QFileDialog QPushButton:hover {
    background: #F5F5F7;
}

QFileDialog QPushButton:default {
    background: #111111;
    border-color: #111111;
    color: #FFFFFF;
    font-weight: 600;
}

QFileDialog QComboBox {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 7px;
    padding: 4px 24px 4px 8px;
    color: #1D1D1F;
}

QFileDialog QListView::item:selected,
QFileDialog QTreeView::item:selected {
    background: #111111;
    color: #FFFFFF;
}

QFileDialog QLineEdit {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 7px;
    padding: 6px 10px;
    color: #1D1D1F;
}

QFileDialog QToolButton {
    background: #FFFFFF;
    border: 1px solid #D2D2D7;
    border-radius: 6px;
    padding: 4px 8px;
    color: #1D1D1F;
}

QFileDialog QToolButton:hover {
    background: #F5F5F7;
}

QToolTip {
    background-color: #FFFFFF;
    color: #1D1D1F;
    border: 1px solid #E5E5EA;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 12px;
}
"""


def build_stylesheet():
    return _QSS


STYLESHEET = build_stylesheet()
