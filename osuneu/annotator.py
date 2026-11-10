"""Local annotation server; deliberately independent of ML dependencies."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import posixpath
import re
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

WEB = Path(__file__).with_name("web")
MAX_UPLOAD = 200 * 1024 * 1024


def parse_preview(data: bytes, filename: str) -> dict:
    text = data.decode("utf-8-sig", errors="replace")
    sections: dict[str, list[str]] = {}
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        else:
            sections.setdefault(section, []).append(line)
    def fields(name):
        return dict(line.split(":", 1) for line in sections.get(name, []) if ":" in line)
    general, meta, diff = fields("General"), fields("Metadata"), fields("Difficulty")
    if int(general.get("Mode", "0")) != 0:
        raise ValueError("当前仅支持 osu!standard 谱面")
    settings = {k: float(diff.get(k, default)) for k, default in
                [("CircleSize", 4), ("OverallDifficulty", 5), ("SliderMultiplier", 1.4)]}
    settings["ApproachRate"] = float(diff.get("ApproachRate", settings["OverallDifficulty"]))
    timing = sorted([[float(p[0]), float(p[1]), int(p[6]) if len(p) > 6 else 1]
                     for line in sections.get("TimingPoints", []) if len(p := line.split(",")) >= 2])
    objects = []
    for line in sections.get("HitObjects", []):
        p = line.split(",")
        if len(p) < 5:
            continue
        x, y, t, bits = float(p[0]), float(p[1]), float(p[2]), int(p[3])
        obj = dict(x=x, y=y, time=t, end=t, kind="circle", newCombo=bool(bits & 4))
        if bits & 8:
            obj.update(kind="spinner", end=max(t, float(p[5])))
        elif bits & 2:
            curve = p[5].split("|")
            points = [[x, y]] + [[float(v) for v in pair.split(":")] for pair in curve[1:]]
            repeats, length = max(1, int(p[6])), max(0, float(p[7]))
            beat, sv = 500., 1.
            for start, value, red in timing:
                if start > t:
                    break
                if red and value > 0:
                    beat, sv = value, 1.
                elif not red and value < 0:
                    sv = max(.1, min(10., -100 / value))
            duration = length * repeats * beat / max(.01, settings["SliderMultiplier"] * 100 * sv)
            obj.update(kind="slider", end=t + duration, points=points, curve=curve[0],
                       repeats=repeats, length=length)
        objects.append(obj)
    objects.sort(key=lambda o: o["time"])
    if not objects:
        raise ValueError("谱面没有可预览的物件")
    number = 0
    for i, obj in enumerate(objects):
        number = 1 if obj["newCombo"] or i == 0 else number + 1
        obj.update(index=i, number=number)
    bpm = 60000.0 / timing[0][1] if timing and timing[0][1] > 0 else 0.0
    return dict(id=hashlib.sha256(data).hexdigest(), filename=filename,
                title=meta.get("TitleUnicode", "").strip() or meta.get("Title", "Untitled").strip(),
                artist=meta.get("ArtistUnicode", "").strip() or meta.get("Artist", "").strip(),
                version=meta.get("Version", "Unknown").strip(), creator=meta.get("Creator", "").strip(),
                audio=general.get("AudioFilename", "").strip(), settings=settings, bpm=bpm,
                objects=objects, timing=timing, duration=max(o["end"] for o in objects) + 1500)


def load_upload(data: bytes, filename: str) -> tuple[list, dict]:
    assets, maps, errors = {}, [], []
    if filename.lower().endswith(".osu"):
        return [parse_preview(data, filename)], assets
    if not filename.lower().endswith(".osz"):
        raise ValueError("请选择 .osu 或 .osz 文件")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if sum(i.file_size for i in infos) > 700 * 1024 * 1024 or len(infos) > 10000:
            raise ValueError("谱包解压后过大")
        names = {i.filename.replace("\\", "/").casefold(): i for i in infos}
        for info in infos:
            if not info.filename.lower().endswith(".osu"):
                continue
            try:
                bm = parse_preview(archive.read(info), info.filename)
                audio_name = posixpath.normpath(posixpath.join(posixpath.dirname(info.filename), bm["audio"].replace("\\", "/")))
                audio_info = names.get(audio_name.casefold())
                if audio_info:
                    key = hashlib.sha256(audio_name.encode()).hexdigest() + posixpath.splitext(audio_name)[1]
                    if key not in assets:
                        assets[key] = archive.read(audio_info)
                    bm["audioUrl"] = "/asset/" + key
                maps.append(bm)
            except (ValueError, IndexError) as exc:
                errors.append(str(exc))
    if not maps:
        raise ValueError("谱包中没有可用的 standard 谱面。" + "; ".join(errors[:2]))
    return maps, assets


class Handler(BaseHTTPRequestHandler):
    def send_asset(self, data: bytes, mime: str):
        size = len(data)
        start, end, status = 0, size - 1, 200
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            try:
                if not match or not any(match.groups()):
                    raise ValueError
                first, last = match.groups()
                start = int(first) if first else max(0, size - int(last))
                end = min(size - 1, int(last)) if first and last else size - 1
                if start > end or start >= size:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        self.wfile.write(data[start:end + 1])

    def send_data(self, data: bytes, mime: str, status=200):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/asset/"):
            key = path.removeprefix("/asset/")
            data = self.server.assets.get(key)
            if data is not None:
                return self.send_asset(data, mimetypes.guess_type(key)[0] or "application/octet-stream")
        elif path in ("/", "/app.js", "/style.css"):
            file = WEB / ("index.html" if path == "/" else path[1:])
            return self.send_data(file.read_bytes(), (mimetypes.guess_type(file)[0] or "text/plain") + "; charset=utf-8")
        self.send_error(404)

    def do_POST(self):
        try:
            if self.path != "/api/open":
                return self.send_error(404)
            # Prevent other websites from submitting files to this local server.
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                return self.send_error(403)
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= MAX_UPLOAD:
                raise ValueError("文件大小必须在 0–200 MB 之间")
            maps, assets = load_upload(self.rfile.read(size), unquote(self.headers.get("X-Filename", "")))
            self.server.assets = assets
            self.send_data(json.dumps(dict(maps=maps), ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8")
        except (ValueError, IndexError, zipfile.BadZipFile, RuntimeError, KeyError) as exc:
            self.send_data(json.dumps(dict(error=str(exc)), ensure_ascii=False).encode(), "application/json; charset=utf-8", 400)


def main():
    parser = argparse.ArgumentParser(description="osu!neu 本地谱面标注器")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.assets = {}
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"osu!neu annotator: {url}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
