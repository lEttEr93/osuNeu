"""Standalone Qt window for the annotation studio (no browser profile)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

from .annotator import Handler


def data_directory(override: str | None = None) -> Path:
    """Keep the persistent desktop profile in a dated workspace artifact."""
    if override or os.environ.get("OSUNEU_DATA_DIR"):
        directory = Path(override or os.environ["OSUNEU_DATA_DIR"]).resolve()
    else:
        root = Path(os.environ.get("AI_ROOT", "D:/AI"))
        existing = sorted((root / "artifacts" / "osuneu").glob("*-desktop-studio"))
        directory = existing[-1] if existing else root / "artifacts" / "osuneu" / f"{date.today().isoformat()}-desktop-studio"
        if not directory.exists():
            helper = root / "bin" / "ai-artifact.cmd"
            if helper.exists():
                subprocess.run(["cmd", "/d", "/c", str(helper), "osuneu", "desktop-studio"], check=True)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "out").mkdir(exist_ok=True)
    return directory


def run(port: int = 8766, data_dir: str | None = None, debug_port: int | None = None):
    if debug_port:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = str(debug_port)
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfileBuilder, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("osu!neu")
    directory = data_directory(data_dir)
    caches = Path(os.environ.get("AI_CACHES", "D:/AI/caches")) / "osuneu"
    caches.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.assets = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    window = QMainWindow()
    window.setWindowTitle("osu!neu · 谱面标注器")
    window.resize(1440, 1000)
    window.setMinimumSize(900, 700)
    builder = QWebEngineProfileBuilder()
    builder.setPersistentStoragePath(str(directory / "profile"))
    builder.setCachePath(str(caches / "qtwebengine"))
    profile = builder.createProfile("osuneu-desktop", app)
    page = QWebEnginePage(profile, window)
    page.setBackgroundColor(QColor("#101218"))
    view = QWebEngineView(window)
    view.setPage(page)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.NavigateOnDropEnabled, False)
    window.setCentralWidget(view)

    def save_download(download):
        destination, _ = QFileDialog.getSaveFileName(
            window, "导出标注 JSON", str(directory / "out" / download.downloadFileName()),
            "JSON (*.json);;All files (*)",
        )
        if not destination:
            download.cancel()
            return
        path = Path(destination)
        download.setDownloadDirectory(str(path.parent))
        download.setDownloadFileName(path.name)
        download.accept()

    profile.downloadRequested.connect(save_download)
    view.load(QUrl(f"http://127.0.0.1:{server.server_port}/?desktop=1"))
    window.show()
    print(f"osu!neu desktop - data: {directory}", flush=True)
    try:
        app.exec()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        # Release the page before its profile so persistent storage flushes cleanly.
        view.setPage(QWebEnginePage(view))
        page.deleteLater()
        app.processEvents()


def main():
    parser = argparse.ArgumentParser(description="osu!neu 桌面谱面标注器")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", help="持久桌面数据目录")
    parser.add_argument("--debug-port", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    run(args.port, args.data_dir, args.debug_port)


if __name__ == "__main__":
    main()
