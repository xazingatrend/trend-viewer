#!/usr/bin/env python3
"""Thin HTTP server for the trend-viewer port."""

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ai_news import ai_news_tool
from analysis import synthesis_tool
from date import date_tool
from settings import BASE_DIR, CACHE_TTL, PORT
from shared import accounts_tool, img_proxy_tool, saved_items_tool
from reels import reels_tool
from threads import threads_tool
from tiktok import tiktok_tool
from trends import trends_tool
from x_twitter import x_twitter_tool
from youtube import youtube_tool

STUB_PATHS = set()

reels_tool.register()
threads_tool.register()
tiktok_tool.register()
x_twitter_tool.register()


def _feed_status(items, errors):
    if items and errors:
        return "partial"
    if items:
        return "ok"
    if errors:
        return "error"
    return "empty"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_head(self, code, content_length, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _handle_index(self, qs):
        del qs
        with open(os.path.join(BASE_DIR, "frontend", "index.html"), "rb") as f:
            self._send(200, f.read(), "text/html; charset=utf-8")

    def _handle_categories(self, qs):
        del qs
        self._send(200, {"categories": ["전체", "AI"] + list(youtube_tool.CATEGORIES.keys())})

    def _handle_videos(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        category = qs.get("category", ["전체"])[0]
        period = qs.get("period", ["week"])[0]
        shorts = qs.get("shorts", ["0"])[0] == "1"
        enrich = qs.get("enrich", ["0"])[0] == "1"
        query = qs.get("q", [""])[0].strip()
        country = qs.get("country", ["KR"])[0].upper()
        if country not in youtube_tool.COUNTRY_LOCALE:
            country = "KR"
        if not query and category not in ("전체", "AI") and category not in youtube_tool.CATEGORIES:
            self._send(400, {"error": "unknown category"})
            return
        videos, fetched_at = youtube_tool.get_videos(category, period, shorts, force, enrich, query, country)
        self._send(200, {"videos": videos[:60], "country": country, "fetchedAt": fetched_at, "cacheTtl": CACHE_TTL})

    def _handle_trends(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        country = qs.get("country", ["KR"])[0].upper()
        if country not in trends_tool.GEOS:
            country = "KR"
        trends, fetched_at, errors, cache_ttl = trends_tool.get_trends(country, force)
        self._send(200, {"trends": trends, "country": country, "fetchedAt": fetched_at, "cacheTtl": cache_ttl, "status": _feed_status(trends, errors), "errors": errors})

    def _handle_reels(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        reels, accounts, fetched_at, errors, cache_ttl = reels_tool.get_reels(force)
        self._send(200, {"reels": reels[:80], "accounts": accounts, "fetchedAt": fetched_at, "cacheTtl": cache_ttl, "status": _feed_status(reels, errors), "errors": errors})

    def _handle_tiktok(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        posts, accounts, fetched_at = tiktok_tool.get_tiktok(force)
        self._send(200, {"posts": posts[:100], "accounts": accounts, "fetchedAt": fetched_at, "cacheTtl": CACHE_TTL})

    def _handle_x(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        posts, accounts, fetched_at, errors, cache_ttl = x_twitter_tool.get_x_posts(force)
        self._send(200, {"posts": posts, "accounts": accounts, "fetchedAt": fetched_at, "cacheTtl": cache_ttl, "status": _feed_status(posts, errors), "errors": errors})

    def _handle_threads(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        posts, accounts, fetched_at, errors, cache_ttl = threads_tool.get_threads_posts(force)
        self._send(200, {"posts": posts, "accounts": accounts, "fetchedAt": fetched_at, "cacheTtl": cache_ttl, "status": _feed_status(posts, errors), "errors": errors})

    def _handle_ai(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        data, fetched_at = ai_news_tool.get_ai_data(force)
        self._send(200, {**data, "fetchedAt": fetched_at, "cacheTtl": CACHE_TTL})

    def _handle_date(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        country = qs.get("country", ["KR"])[0].upper()
        if country not in youtube_tool.COUNTRY_LOCALE:
            country = "KR"
        data, fetched_at, cache_ttl = date_tool.get_date_radar(country, force)
        self._send(200, {**data, "country": country, "fetchedAt": fetched_at, "cacheTtl": cache_ttl})

    def _handle_analysis(self, qs):
        force = qs.get("force", ["0"])[0] == "1"
        country = qs.get("country", ["KR"])[0].upper()
        if country not in youtube_tool.COUNTRY_LOCALE:
            country = "KR"
        data, fetched_at, cache_ttl = synthesis_tool.get_analysis(country, force)
        self._send(200, {**data, "country": country, "fetchedAt": fetched_at, "cacheTtl": cache_ttl})

    def _handle_oembed(self, qs):
        self._send(200, ai_news_tool.fetch_oembed(qs.get("url", [""])[0]))

    def _handle_img(self, qs):
        status, content_type, body = img_proxy_tool.fetch_image(qs.get("u", [""])[0])
        self._send(status, body, content_type)

    def _handle_stub(self, qs):
        del qs
        self._send(501, {"error": "not implemented"})


    def _handle_saved_get(self, qs):
        self._send(200, {"items": saved_items_tool.list_items()})

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        routes = {
            "/": self._handle_index,
            "/index.html": self._handle_index,
            "/api/categories": self._handle_categories,
            "/api/videos": self._handle_videos,
            "/api/trends": self._handle_trends,
            "/api/img": self._handle_img,
            "/api/saved": self._handle_saved_get,
            "/api/reels": self._handle_reels,
            "/api/tiktok": self._handle_tiktok,
            "/api/x": self._handle_x,
            "/api/threads": self._handle_threads,
            "/api/ai": self._handle_ai,
            "/api/date": self._handle_date,
            "/api/analysis": self._handle_analysis,
            "/api/oembed": self._handle_oembed,
        }
        for path in STUB_PATHS:
            routes[path] = self._handle_stub
        handler = routes.get(parsed.path)
        if handler is None:
            self._send(404, {"error": "not found"})
            return
        handler(qs)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/index.html"):
            body = json.dumps({"error": "not found"}, ensure_ascii=False).encode()
            self._send_head(404, len(body), "application/json; charset=utf-8")
            return
        index_path = os.path.join(BASE_DIR, "frontend", "index.html")
        self._send_head(200, os.path.getsize(index_path), "text/html; charset=utf-8")

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/saved":
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length).decode())
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid json"})
                return
            action = req.get("action")
            if action == "add":
                items, added = saved_items_tool.add_item(
                    req.get("source", ""),
                    req.get("title", ""),
                    req.get("url", ""),
                    req.get("thumbnail", ""),
                    req.get("note", ""),
                    req.get("tags"),
                )
                self._send(200, {"items": items, "added": added})
            elif action == "remove":
                items, removed = saved_items_tool.remove_item(req.get("id", ""))
                self._send(200, {"items": items, "removed": removed})
            else:
                self._send(400, {"error": "unknown action"})
            return

        m = re.match(r"^/api/([a-z_]+)/accounts$", parsed.path)
        if not m:
            self._send(404, {"error": "not found"})
            return

        source = m.group(1)
        if accounts_tool.get_source(source) is None:
            self._send(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode())
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return

        accounts = accounts_tool.update_accounts(
            source,
            req.get("action"),
            req.get("username"),
        )
        self._send(200, {"accounts": accounts})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"트렌드 뷰어 실행 중: http://localhost:{PORT}")
    server.serve_forever()
