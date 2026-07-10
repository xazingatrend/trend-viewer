"""Deterministic cross-platform collection and heuristic trend analysis."""

import concurrent.futures
import json
import math
import os
import threading
import time
from urllib.parse import quote_plus

import settings
from ai_news import ai_news_tool
from reels import reels_tool
from shared import accounts_tool
from threads import threads_tool
from tiktok import tiktok_tool
from trends import trends_tool
from x_twitter import x_twitter_tool
from youtube import youtube_tool

from . import keyword_tool


_CHANNELS = ("trends", "youtube", "reels", "x", "threads", "tiktok", "ai_news")
_HISTORY_LIMIT = 48
_history_lock = threading.Lock()


def ensure_registered():
    """Repair the idempotent account-source registry before social fetches."""
    reels_tool.register()
    threads_tool.register()
    tiktok_tool.register()
    x_twitter_tool.register()


def _as_int(value):
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _as_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _item(platform, title, url, metric, ts):
    return {
        "platform": platform,
        "title": str(title or ""),
        "url": str(url or ""),
        "metric": _as_int(metric),
        "ts": _as_float(ts),
    }


def _trend_url(item):
    news = item.get("news")
    if isinstance(news, list) and news and isinstance(news[0], dict):
        url = news[0].get("url")
        if url:
            return url
    return "https://www.google.com/search?q=" + quote_plus(str(item.get("keyword") or ""))


def _fetch_channel(channel, country, force):
    errors = []
    if channel == "trends":
        result = trends_tool.get_trends(country, force)
        source, errors = result[0][:20], result[2]
        items = [
            _item("trends", row.get("keyword"), _trend_url(row), row.get("trafficValue"), row.get("ts"))
            for row in source
        ]
    elif channel == "youtube":
        result = youtube_tool.get_videos("전체", "week", False, force, country=country)
        items = [
            _item(
                "youtube",
                row.get("title"),
                "https://www.youtube.com/watch?v=" + str(row.get("id") or ""),
                row.get("views"),
                0,
            )
            for row in result[0][:20]
        ]
    elif channel == "reels":
        result = reels_tool.get_reels(force)
        errors = result[3]
        items = [
            _item("reels", row.get("title"), row.get("url"), row.get("views"), row.get("takenAt"))
            for row in result[0][:20]
        ]
    elif channel == "x":
        result = x_twitter_tool.get_x_posts(force)
        errors = result[3]
        source = sorted(
            result[0],
            key=lambda row: _as_int(row.get("views")) or _as_int(row.get("likes")),
            reverse=True,
        )[:20]
        items = [
            _item(
                "x",
                str(row.get("text") or "")[:160],
                row.get("url"),
                _as_int(row.get("views")) or _as_int(row.get("likes")),
                0,
            )
            for row in source
        ]
    elif channel == "threads":
        result = threads_tool.get_threads_posts(force)
        errors = result[3]
        source = sorted(result[0], key=lambda row: _as_int(row.get("likes")), reverse=True)[:20]
        items = [
            _item(
                "threads",
                str(row.get("text") or "")[:160],
                row.get("url"),
                row.get("likes"),
                row.get("createdAt"),
            )
            for row in source
        ]
    elif channel == "tiktok":
        result = tiktok_tool.get_tiktok(force)
        items = [
            _item("tiktok", row.get("title"), row.get("url"), row.get("views"), row.get("createdAt"))
            for row in result[0][:20]
        ]
    else:
        result = ai_news_tool.get_ai_data(force)
        data = result[0] if isinstance(result[0], dict) else {}
        items = [
            _item("ai_news", row.get("title"), row.get("link"), 0, row.get("ts"))
            for row in (data.get("news") or [])[:30]
        ]
    return items, errors or []


def _embedded_errors(channel, errors):
    harvested = []
    for error in errors:
        if isinstance(error, dict):
            entry = dict(error)
            entry["channel"] = channel
        else:
            entry = {"channel": channel, "kind": "error", "detail": str(error)}
        harvested.append(entry)
    return harvested


def collect_snapshot(country="KR", force=False, deadline=25):
    """Collect seven source channels concurrently within a shared deadline."""
    started_at = time.monotonic()
    ensure_registered()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=7)
    futures = {
        channel: executor.submit(_fetch_channel, channel, country, force)
        for channel in _CHANNELS
    }
    items = []
    errors = []
    try:
        remaining = max(0.0, float(deadline) - (time.monotonic() - started_at))
        done, _ = concurrent.futures.wait(tuple(futures.values()), timeout=remaining)
        for channel in _CHANNELS:
            future = futures[channel]
            if future not in done:
                errors.append({"channel": channel, "kind": "timeout"})
                continue
            try:
                channel_items, channel_errors = future.result()
            except Exception:
                errors.append({"channel": channel, "kind": "error"})
                continue
            items.extend(channel_items)
            errors.extend(_embedded_errors(channel, channel_errors))
    finally:
        executor.shutdown(wait=False)
    return {"items": items, "errors": errors}


def _snapshot_items(snapshot):
    if isinstance(snapshot, dict):
        items = snapshot.get("items", [])
    else:
        items = snapshot
    return [item for item in items if isinstance(item, dict)]


def _topic_for_anchor(anchor, title, items, trend_anchored):
    matched = [item for item in items if keyword_tool.matches(anchor, item.get("title", ""))]
    platforms = sorted({str(item.get("platform") or "") for item in matched if item.get("platform")})
    if not matched or (not trend_anchored and len(platforms) < 2):
        return None
    score = sum(math.log10(_as_int(item.get("metric")) + 1) for item in matched)
    score *= 1.0 + 0.5 * (len(platforms) - 1)
    return {
        "keyword": keyword_tool.normalize(anchor),
        "title": str(title or anchor),
        "platforms": platforms,
        "score": score,
        "items": sorted(matched, key=lambda item: (str(item.get("platform") or ""), str(item.get("url") or ""))),
    }


def correlate(snapshot):
    """Build non-transitive topics from trend and exact-token fallback anchors."""
    items = _snapshot_items(snapshot)
    trend_anchors = []
    seen_trends = set()
    for item in items:
        if item.get("platform") != "trends":
            continue
        title = str(item.get("title") or "").strip()
        normalized = keyword_tool.normalize(title)
        if normalized and normalized not in seen_trends:
            seen_trends.add(normalized)
            trend_anchors.append((normalized, title))

    topics = []
    emitted_trend_compacts = []
    for anchor, title in trend_anchors:
        topic = _topic_for_anchor(anchor, title, items, trend_anchored=True)
        if topic is not None:
            topics.append(topic)
            emitted_trend_compacts.append(anchor.replace(" ", ""))

    token_platforms = {}
    for item in items:
        platform = item.get("platform")
        if not platform:
            continue
        for token in set(keyword_tool.tokens(item.get("title", ""))):
            token_platforms.setdefault(token, set()).add(platform)

    fallback_anchors = sorted(
        token
        for token, platforms in token_platforms.items()
        if len(platforms) >= 2
        and (len(token) >= 3 or not token.isascii())
        and not token.isdigit()
    )
    for anchor in fallback_anchors:
        compact = anchor.replace(" ", "")
        if any(compact and compact in trend_compact for trend_compact in emitted_trend_compacts):
            continue
        topic = _topic_for_anchor(anchor, anchor, items, trend_anchored=False)
        if topic is not None:
            # Bare tokens make poor display titles; surface the strongest matched
            # headline instead while keeping the token as the keyword.
            best = max(topic["items"], key=lambda item: _as_int(item.get("metric")))
            best_title = str(best.get("title") or "").strip()
            if best_title:
                topic["title"] = best_title
            topics.append(topic)

    topics.sort(key=lambda topic: (-topic["score"], topic["keyword"]))
    return topics


def _history_path():
    return os.path.join(settings.CONFIG_DIR, "analysis_history.json")


def _read_history_unlocked():
    try:
        with open(_history_path(), encoding="utf-8") as history_file:
            history = json.load(history_file)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    return history if isinstance(history, list) else []


def load_history():
    """Load history, treating missing or corrupt data as an empty ring."""
    with _history_lock:
        return _read_history_unlocked()


def record_history(country, topics, now=None):
    """Atomically append a score snapshot and retain the latest 48 entries."""
    entry = {
        "ts": float(time.time() if now is None else now),
        "country": country,
        "topics": {topic["keyword"]: topic["score"] for topic in topics},
    }
    path = _history_path()
    tmp_path = path + ".tmp"
    with _history_lock:
        history = _read_history_unlocked()
        history.append(entry)
        history = history[-_HISTORY_LIMIT:]
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as history_file:
                json.dump(history, history_file, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_path, path)
        except OSError:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False
    return True


def velocity(topics, history, country, now):
    """Annotate topics against the newest eligible same-country baseline."""
    eligible = []
    for entry in history:
        if not isinstance(entry, dict) or entry.get("country") != country:
            continue
        try:
            timestamp = float(entry.get("ts"))
        except (TypeError, ValueError, OverflowError):
            continue
        if now - 86400 <= timestamp <= now - 1800:
            eligible.append((timestamp, entry))

    annotated = [dict(topic) for topic in topics]
    if not eligible:
        for topic in annotated:
            topic["velocity"] = "insufficient"
        return {
            "topics": annotated,
            "velocityBaseline": {"available": False, "elapsedSeconds": None},
        }

    baseline_ts, baseline = max(eligible, key=lambda pair: pair[0])
    baseline_topics = baseline.get("topics")
    if not isinstance(baseline_topics, dict):
        baseline_topics = {}
    for topic in annotated:
        previous = baseline_topics.get(topic["keyword"])
        if previous is None:
            state = "new"
        else:
            previous_score = float(previous)
            current_score = float(topic["score"])
            if current_score > previous_score * 1.10:
                state = "rising"
            elif current_score < previous_score * 0.90:
                state = "falling"
            else:
                state = "flat"
        topic["velocity"] = state
    return {
        "topics": annotated,
        "velocityBaseline": {
            "available": True,
            "elapsedSeconds": int(now - baseline_ts),
        },
    }


def _compose_briefing(topics):
    rising = next((topic for topic in topics if topic.get("velocity") == "rising"), None)
    cross_platform = next((topic for topic in topics if len(topic.get("platforms", [])) >= 2), None)
    rising_line = (
        "상승세 토픽: " + rising["title"]
        if rising
        else "상승세 토픽: 감지되지 않았습니다."
    )
    cross_line = (
        "교차 플랫폼 토픽: " + cross_platform["title"]
        if cross_platform
        else "교차 플랫폼 토픽: 감지되지 않았습니다."
    )
    return [rising_line, cross_line]


def analyze_heuristic(country, force):
    """Run collection, correlation, prior-history velocity, then persistence."""
    ensure_registered()
    snapshot = collect_snapshot(country=country, force=force)
    topics = correlate(snapshot)
    now = time.time()
    prior_history = load_history()
    velocity_result = velocity(topics, prior_history, country, now)
    output_topics = []
    for topic in velocity_result["topics"]:
        output = dict(topic)
        output["items"] = output.get("items", [])[:5]
        output_topics.append(output)

    errors = list(snapshot.get("errors", []))
    if not record_history(country, topics, now=now):
        errors.append({"channel": "history", "kind": "error"})
    return {
        "topics": output_topics,
        "velocityBaseline": velocity_result["velocityBaseline"],
        "briefing": _compose_briefing(output_topics),
        "errors": errors,
        "generatedBy": "heuristic",
    }
