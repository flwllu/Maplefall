import os
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication

from app.icons import app_icon
from app.main_window import MusicRenamerApp
from app.styles import FONT_FAMILIES


def _install_translations(app):
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.Chinese, QLocale.Country.China),
                       "qtbase", "_", folder) or \
            translator.load("qtbase_zh_CN", folder):
        app.installTranslator(translator)
        return translator
    return None


def main():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("音律工具箱")
    app.setApplicationDisplayName("音律工具箱")
    app.setOrganizationName("MediaToolbox")
    app.setStyle("Fusion")

    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)

    _install_translations(app)

    app.setWindowIcon(app_icon())

    window = MusicRenamerApp()
    window.show()

    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        window.open_file(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
