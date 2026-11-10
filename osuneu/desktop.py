"""Standalone Qt window for the annotation studio (no browser profile)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import date, datetime
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


def run(port: int = 8766, data_dir: str | None = None, debug_port: int | None = None,
        ready_file: str | None = None):
    if debug_port:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = str(debug_port)
    from PySide6.QtCore import Qt, QUrl, QTimer
    from PySide6.QtGui import QColor
    from PySide6.QtWebEngineCore import (
        QWebEnginePage, QWebEngineProfileBuilder, QWebEngineSettings,
        QWebEngineUrlRequestInterceptor,
    )
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
    # This window is an editor for local files, never a general web browser.
    # Keep the compatibility renderer confined to the bundled local application.
    origin_port = server.server_port

    def allowed(url):
        return (url.scheme() in {"about", "blob", "data"}
                or (url.scheme() == "http" and url.host() == "127.0.0.1"
                    and url.port() == origin_port))

    class LocalRequests(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, request):
            if not allowed(request.requestUrl()):
                request.block(True)

    class LocalPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            return allowed(url)

    interceptor = LocalRequests(profile)
    profile.setUrlRequestInterceptor(interceptor)
    page = LocalPage(profile, window)
    page.renderProcessTerminated.connect(
        lambda status, code: print(f"Renderer stopped: {status}, exit={code}", flush=True))
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

    def check_ready():
        def result(ok):
            if ok:
                ready_timer.stop()
                if ready_file:
                    Path(ready_file).write_text("ready", encoding="ascii")
                print("Desktop UI ready", flush=True)
        page.runJavaScript("document.getElementById('tags')?.children.length > 0", result)

    ready_timer = QTimer(window)
    ready_timer.setInterval(500)
    ready_timer.timeout.connect(check_ready)

    def loaded(ok):
        print(f"Page loaded: {ok}", flush=True)
        if ok:
            check_ready()
    page.loadFinished.connect(loaded)
    # Also catches a renderer that never emits loadFinished.
    ready_timer.start()
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


def launch(args):
    """Supervise startup: a native Qt crash cannot be caught inside Python."""
    root = Path(os.environ.get("AI_ROOT", "D:/AI"))
    logs = root / "runs" / "osuneu"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    log_path = logs / f"desktop-{stamp}.log"
    scratch = root / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    print(f"osu!neu startup log: {log_path}", flush=True)
    # Remember only a renderer configuration that actually reached the editor.
    config = Path(os.environ.get("AI_CACHES", str(root / "caches"))) / "osuneu" / "renderer.json"
    compatibility = False
    try:
        compatibility = json.loads(config.read_text(encoding="utf-8")).get("compatibility", False)
    except (OSError, ValueError):
        pass
    modes = [True] if compatibility else [False, True]
    for compat in modes:
        ready = logs / f"desktop-{stamp}-{'compat' if compat else 'normal'}.ready"
        command = [sys.executable, "-u", "-m", "osuneu.desktop", "--worker",
                   "--port", str(args.port), "--ready-file", str(ready)]
        if args.data_dir:
            command.extend(["--data-dir", args.data_dir])
        if args.debug_port:
            command.extend(["--debug-port", str(args.debug_port)])
        env = os.environ.copy()
        env.update(TEMP=str(scratch), TMP=str(scratch), PYTHONUTF8="1")
        if compat:
            # Qt's Windows renderer sandbox fails to spawn on this machine.
            # Only this child process changes; remote navigation is blocked above.
            env["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
            print("Starting local editor with compatibility renderer.", flush=True)
        with log_path.open("ab", buffering=0) as log:
            log.write(f"\nRenderer compatibility={compat}\n".encode())
            child = subprocess.Popen(command, env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 15
            while child.poll() is None and not ready.exists() and time.monotonic() < deadline:
                time.sleep(.2)
            if ready.exists():
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(json.dumps({"compatibility": compat}), encoding="utf-8")
                return child.wait()
            code = child.poll()
            if code == 0:
                return 0  # User closed the window during startup.
            if code is None:
                child.terminate()
                child.wait()
            print(f"Renderer startup failed (exit={code}); see {log_path}", flush=True)
    print("Desktop could not start. Please share the startup log shown above.", flush=True)
    return 1


def main():
    parser = argparse.ArgumentParser(description="osu!neu 桌面谱面标注器")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", help="持久桌面数据目录")
    parser.add_argument("--debug-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ready-file", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        run(args.port, args.data_dir, args.debug_port, args.ready_file)
    else:
        sys.exit(launch(args))


if __name__ == "__main__":
    main()
