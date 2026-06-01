#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DATA_DIR = DATA_DIR / "history"
HISTORY_HTML_DIR = ROOT / "history"
TW_TZ = timezone(timedelta(hours=8))


def fetch_json(url: str, name: str) -> Dict[str, Any]:
    if not url:
        raise RuntimeError(f"Missing required URL: {name}")
    req = urllib.request.Request(url, headers={"User-Agent": "macro-dashboard-github-pages/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} did not return valid JSON. Preview:\\n{raw[:800]}") from exc


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def today_tw() -> str:
    return datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")


def apps_script_base_url() -> str:
    url = os.environ.get("TODAY_DAILY_SOURCE_URL", "").strip()
    return url.split("?", 1)[0] if "?" in url else url


def visual_image_url(summary: Dict[str, Any]) -> str:
    visual = summary.get("visual_note") or {}
    file_id = str(visual.get("file_id") or "").strip()
    if not file_id:
        return ""
    base = apps_script_base_url()
    if base:
        return f"{base}?mode=drive_image&file_id={quote(file_id)}"
    return f"https://drive.google.com/thumbnail?id={quote(file_id)}&sz=w1600"


def latest_point(points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    valid = [p for p in points if p.get("value") is not None and p.get("date")]
    return sorted(valid, key=lambda p: str(p.get("date")))[-1] if valid else None


def sparkline_svg(points: List[Dict[str, Any]]) -> str:
    vals = [float(p["value"]) for p in points if p.get("value") is not None]
    if len(vals) < 2:
        return ""
    w, h, pad = 260, 44, 5
    mn, mx = min(vals), max(vals)
    if mn == mx:
        mx = mn + 1
    coords = []
    for i, v in enumerate(vals):
        x = pad + i * ((w - 2 * pad) / max(1, len(vals) - 1))
        y = h - pad - ((v - mn) / (mx - mn)) * (h - 2 * pad)
        coords.append((x, y))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.8"></circle>' for x, y in coords)
    return f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none"><polyline fill="none" stroke="currentColor" stroke-width="3" points="{poly}"></polyline>{circles}</svg>'


def render_asset_cards(market: Dict[str, Any]) -> str:
    cards = []
    for item in market.get("series") or []:
        points = item.get("points") or []
        lp = latest_point(points)
        if not lp:
            continue
        value = lp.get("value")
        try:
            value_text = f"{float(value):,.3f}".rstrip("0").rstrip(".")
        except Exception:
            value_text = esc(value)
        cards.append(f"""
        <article class="card asset">
          <h3>{esc(item.get("asset") or item.get("asset_key"))}（{esc(item.get("asset_key") or "")}）</h3>
          <div class="asset-value">{value_text}<span class="asset-unit">{esc(item.get("unit") or "")}</span></div>
          <div class="asset-date">資料日：{esc(lp.get("date") or "")}</div>
          {sparkline_svg(points)}
        </article>
        """)
    if not cards:
        return '<section class="card"><h2>走勢圖</h2><p>尚無市場數據。</p></section>'
    return '<section class="card"><h2>走勢圖</h2><div class="grid">' + "\\n".join(cards) + "</div></section>"


def render_block(title: str, content: Any) -> str:
    if not content:
        return ""
    return f'<section class="card"><h2>{esc(title)}</h2><div>{esc(content).replace(chr(10), "<br>")}</div></section>'


def render_list(title: str, items: Any) -> str:
    if not items:
        return ""
    if not isinstance(items, list):
        items = [items]
    lis = "".join(f"<li>{esc(x)}</li>" for x in items if str(x).strip())
    return f'<section class="card"><h2>{esc(title)}</h2><ul class="list">{lis}</ul></section>' if lis else ""


def recent_history_dates(limit: int = 7) -> List[str]:
    if not HISTORY_DATA_DIR.exists():
        return []
    return sorted({p.stem for p in HISTORY_DATA_DIR.glob("*.json")}, reverse=True)[:limit]


def render_history_links(current_date: str) -> str:
    dates = recent_history_dates(7)
    if current_date and current_date not in dates:
        dates = [current_date] + dates
    dates = sorted(set(dates), reverse=True)[:7]
    links = [f'<a class="history-link" href="history/{esc(d)}.html">{esc(d)}</a>' for d in dates]
    return '<section class="card"><h2>歷史總經摘要</h2><div class="history-list">' + "\\n".join(links) + "</div></section>" if links else ""


def page_shell(title: str, body: str, css_path: str = "assets/css/style.css") -> str:
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(title)}</title>
  <link rel="stylesheet" href="{css_path}">
</head>
<body><main class="wrap">{body}</main></body>
</html>
"""


def render_dashboard(summary: Dict[str, Any], market: Dict[str, Any], history: bool = False) -> str:
    date = str(summary.get("date") or "")
    visual = summary.get("visual_note") or {}
    chips = "".join(f'<span class="chip">{esc(x)}</span>' for x in (summary.get("market_signals") or []))
    body = ""
    if history:
        body += '<a class="back" href="../index.html">← 返回首頁</a>'
    body += f"""
    <section class="hero">
      <div class="kicker">{'HISTORY SNAPSHOT' if history else 'MARKET SNAPSHOT'}</div>
      <h1>{esc(summary.get("headline") or "今日總經摘要")}</h1>
      <div class="meta">資料日：{esc(date)}｜頁面產生：{esc(today_tw())}</div>
      <div class="chips">{chips}</div>
    </section>
    """
    body += render_block("總經傳導鏈", summary.get("macro_chain"))
    body += render_block("矛盾 / 背離", summary.get("divergence"))
    body += render_asset_cards(market)
    img = visual_image_url(summary)
    if img:
        body += f'<section class="card"><h2>Visual Note</h2><h3>{esc(visual.get("title") or "")}</h3><img class="visual-img" src="{esc(img)}" alt="Visual Note" loading="lazy"></section>'
    body += render_block("Executive Summary", summary.get("executive_summary"))
    body += render_list("今日核心訊號", summary.get("market_signals"))
    body += render_block("核心資產重點", summary.get("market_snapshot"))
    body += render_list("新聞佐證", summary.get("news_evidence"))
    body += render_list("觀察重點", summary.get("watchpoints"))
    if not history:
        body += render_history_links(date)
    return body


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_HTML_DIR.mkdir(exist_ok=True)

    today_payload = fetch_json(os.environ.get("TODAY_DAILY_SOURCE_URL", "").strip(), "TODAY_DAILY_SOURCE_URL")
    market_payload = fetch_json(os.environ.get("WEEKLY_MARKET_SERIES_URL", "").strip(), "WEEKLY_MARKET_SERIES_URL")

    summary = today_payload.get("daily_summary")
    if not isinstance(summary, dict):
        raise RuntimeError("TODAY_DAILY_SOURCE_URL missing daily_summary object")
    date = str(summary.get("date") or datetime.now(TW_TZ).strftime("%Y-%m-%d"))

    write_json(DATA_DIR / "latest.json", today_payload)
    write_json(DATA_DIR / "market_history_series.json", market_payload)
    write_json(HISTORY_DATA_DIR / f"{date}.json", today_payload)

    (ROOT / "index.html").write_text(page_shell("全球總經摘要", render_dashboard(summary, market_payload, False)), encoding="utf-8")
    (HISTORY_HTML_DIR / f"{date}.html").write_text(page_shell(f"歷史總經摘要｜{date}", render_dashboard(summary, market_payload, True), "../assets/css/style.css"), encoding="utf-8")
    print(f"Built dashboard for {date}")


if __name__ == "__main__":
    main()
