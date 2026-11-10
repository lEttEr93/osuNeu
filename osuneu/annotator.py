"""Local annotation server; deliberately independent of ML dependencies."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import posixpath
import random
import re
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

WEB = Path(__file__).with_name("web")
MAX_UPLOAD = 200 * 1024 * 1024

# Same route as osu! Roam: pick a beatmapset from the public search JSON, then
# download the .osz from the CN mirror (with international fallbacks).
USER_AGENT = "osu!neu annotator/0.1 (https://github.com/lEttEr93/osuNeu)"
SEARCH_URL = "https://osu.ppy.sh/beatmapsets/search?m=0&s=ranked&page={page}"
RANDOM_PAGES = 200   # osu search only exposes the first ~10k ranked results
OSZ_MIRRORS = (
    "https://dl.sayobot.cn/beatmaps/download/full/{sid}",
    "https://txy1.sayobot.cn/beatmaps/download/full/{sid}",
    "https://catboy.best/d/{sid}",
    "https://beatconnect.io/b/{sid}/",
)
MAX_OSZ = 150 * 1024 * 1024


def _http(url: str, method: str = "GET", timeout: int = 20):
    request = urllib.request.Request(
        url, method=method,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    return urllib.request.urlopen(request, timeout=timeout)


def random_mapset() -> dict:
    """One ranked standard beatmapset, picked from a random search page."""
    for _ in range(3):
        with _http(SEARCH_URL.format(page=random.randrange(RANDOM_PAGES))) as response:
            payload = json.loads(response.read())
        sets = [s for s in payload.get("beatmapsets", [])
                if any(b.get("mode") in (0, "osu") for b in s.get("beatmaps", []))]
        if sets:
            return random.choice(sets)
    raise ValueError("这次没抽到标准模式谱面，再试一次")


def cached_osz(set_id: int, cache_dir: Path) -> bytes:
    path = cache_dir / f"{set_id}.osz"
    if path.exists() and path.stat().st_size > 1024:
        return path.read_bytes()
    errors = []
    deadline = time.monotonic() + 60
    for template in OSZ_MIRRORS:
        if time.monotonic() > deadline:
            errors.append("总超时")
            break
        url = template.format(sid=set_id)
        try:
            with _http(url) as response:
                data = bytearray()
                while chunk := response.read(1 << 20):
                    data.extend(chunk)
                    if len(data) > MAX_OSZ:
                        raise ValueError("谱包超过 150 MB")
                    if time.monotonic() > deadline:
                        raise TimeoutError("下载超时")
            if len(data) <= 1024 or bytes(data[:2]) != b"PK":
                errors.append(f"{template} -> 不是 zip")
                continue
            cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(data))
            return bytes(data)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"{template} -> {exc}")
    raise ValueError("所有镜像都失败了：" + "；".join(errors[:3]))


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
            path = urlsplit(self.path).path
            # Prevent other websites from submitting files to this local server.
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                return self.send_error(403)
            if path == "/api/random":
                info = random_mapset()
                maps = self.open_set(info["id"])
                body = dict(maps=maps, set=dict(id=info["id"], artist=info.get("artist", ""),
                                                title=info.get("title", ""),
                                                creator=info.get("creator", ""),
                                                status=info.get("status", "")))
                return self.send_data(json.dumps(body, ensure_ascii=False, allow_nan=False).encode(),
                                      "application/json; charset=utf-8")
            if path == "/api/fetch":
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 4096:
                    raise ValueError("请求无效")
                set_id = int(json.loads(self.rfile.read(size) or b"{}").get("set", 0))
                if set_id <= 0:
                    raise ValueError("无效的谱面集 ID")
                maps = self.open_set(set_id)
                return self.send_data(json.dumps(dict(maps=maps, set=dict(id=set_id)),
                                                 ensure_ascii=False, allow_nan=False).encode(),
                                      "application/json; charset=utf-8")
            if path != "/api/open":
                return self.send_error(404)
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= MAX_UPLOAD:
                raise ValueError("文件大小必须在 0–200 MB 之间")
            maps, assets = load_upload(self.rfile.read(size), unquote(self.headers.get("X-Filename", "")))
            self.server.assets = assets
            self.send_data(json.dumps(dict(maps=maps), ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8")
        except (ValueError, IndexError, zipfile.BadZipFile, RuntimeError, KeyError) as exc:
            self.send_data(json.dumps(dict(error=str(exc)), ensure_ascii=False).encode(), "application/json; charset=utf-8", 400)

    def open_set(self, set_id: int):
        cache = Path(os.environ.get("AI_CACHES", "D:/AI/caches")) / "osuneu" / "beatmaps"
        data = cached_osz(set_id, cache)
        maps, assets = load_upload(data, f"{set_id}.osz")
        self.server.assets = assets
        return maps


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
