from core import *
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app_icon = icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
