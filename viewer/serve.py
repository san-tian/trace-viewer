#!/usr/bin/env python3
"""静态站点服务器：支持 Range（断点续传）+ gzip 预压缩 + 缓存头。

比 python -m http.server 强的地方：
  1. Range 请求 —— 609MB 的包断了能续传，浏览器也不会整包重下
  2. gzip —— 单元格 .js 有 2.3MB，gzip 后约 0.5MB，查看器加载快 4-5 倍
  3. 缓存头 —— cells/ 是不可变内容，让浏览器长期缓存

用法: python3 serve.py [port] [root]
"""
from __future__ import annotations
import gzip, mimetypes, os, re, socketserver, sys, time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[2] if len(sys.argv) > 2 else "/home/dev/fsr60-public").resolve()
PORT = int(sys.argv[1] if len(sys.argv) > 1 else 8931)
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
GZ_EXT = {".js", ".json", ".csv", ".html", ".txt", ".md", ".css", ".svg"}


def gz_path(p: Path) -> Path:
    return p.with_suffix(p.suffix + ".gz")


def ensure_gz(p: Path) -> Path | None:
    """.gz 不存在或比源文件旧就重新压。"""
    if p.suffix.lower() not in GZ_EXT:
        return None
    g = gz_path(p)
    try:
        if not g.exists() or g.stat().st_mtime < p.stat().st_mtime:
            with open(p, "rb") as fi, gzip.open(g, "wb", compresslevel=6) as fo:
                while chunk := fi.read(1 << 20):
                    fo.write(chunk)
        return g
    except Exception:
        return None


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "fsr60"

    def log_message(self, fmt, *a):
        pass

    def _resolve(self):
        rel = self.path.split("?", 1)[0].split("#", 1)[0]
        rel = rel.lstrip("/")
        p = (ROOT / rel).resolve()
        if not str(p).startswith(str(ROOT)):     # 防目录穿越
            return None
        if p.is_dir():
            p = p / "index.html"
        return p if p.is_file() else None

    def _send(self, head_only=False):
        p = self._resolve()
        if p is None:
            body = b"404 not found\n"
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return

        # 先尝试 gzip
        use_gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        src = p
        if use_gz:
            g = ensure_gz(p)
            if g:
                src = g
        size = src.stat().st_size
        mtime = int(src.stat().st_mtime)

        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        if p.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"

        # 缓存策略
        if "/cells/" in str(p) or p.name in ("index.js",):
            cache = "public, max-age=31536000, immutable"
        elif "/download/" in str(p):
            cache = "public, max-age=3600"
        else:
            cache = "public, max-age=300"

        start, end = 0, size - 1
        partial = False
        rng = self.headers.get("Range")
        code = HTTPStatus.OK
        if rng:
            m = RANGE_RE.fullmatch(rng.strip())
            if m:
                a, b = m.group(1), m.group(2)
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                elif b:                      # bytes=-N （最后 N 字节）
                    start = max(0, size - int(b))
                if start >= size or end >= size or start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                partial = True
                code = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", cache)
        self.send_header("Last-Modified", self.date_time_string(mtime))
        if use_gz and src is not p:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        # 允许页面跨域取用（便于别人嵌 iframe / 抓数据）
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if head_only:
            return
        chunk = 1 << 20
        with open(src, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                b = f.read(min(chunk, left))
                if not b:
                    break
                self.wfile.write(b)
                left -= len(b)

    def do_GET(self):
        try:
            self._send(False)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):
        try:
            self._send(True)
        except (BrokenPipeError, ConnectionResetError):
            pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"serving {ROOT} on 127.0.0.1:{PORT}", flush=True)
    Server(("127.0.0.1", PORT), H).serve_forever()
