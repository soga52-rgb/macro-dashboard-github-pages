#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GitHub Pages：直接抓 Apps Script 完整 HTML，不重新組版。

需要 GitHub Secrets：
- DASHBOARD_HTML_SOURCE_URL

選配：
- TODAY_DAILY_SOURCE_URL
  只用來取得 date，方便保存 history/YYYY-MM-DD.html。
  如果沒有設定，會用台北時間今天日期。
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DATA_DIR = DATA_DIR / "history"
HISTORY_HTML_DIR = ROOT / "history"
TW_TZ = timezone(timedelta(hours=8))


def fetch_text(url: str, name: str) -> str:
    if not url:
        raise RuntimeError(f"Missing required URL: {name}")

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "macro-dashboard-github-pages-html-snapshot/1.0",
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
        },
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json_optional(url: str) -> Dict[str, Any]:
    if not url:
        return {}

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "macro-dashboard-github-pages-html-snapshot/1.0",
                "Accept": "application/json,text/plain,*/*",
            },
        )

        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        return json.loads(raw)

    except Exception as exc:
        print(f"WARN: unable to fetch optional JSON: {exc}", file=sys.stderr)
        return {}


def infer_date(today_payload: Dict[str, Any], html: str) -> str:
    daily = today_payload.get("daily_summary") if isinstance(today_payload, dict) else None

    if isinstance(daily, dict) and daily.get("date"):
        return str(daily["date"])

    patterns = [
        r"主要資料日\s*[：:]\s*(\d{4}-\d{2}-\d{2})",
        r"資料日\s*[：:]\s*(\d{4}-\d{2}-\d{2})",
        r"data-date=[\"'](\d{4}-\d{2}-\d{2})[\"']",
    ]

    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            return m.group(1)

    return datetime.now(TW_TZ).strftime("%Y-%m-%d")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    dashboard_url = os.environ.get("DASHBOARD_HTML_SOURCE_URL", "").strip()
    today_url = os.environ.get("TODAY_DAILY_SOURCE_URL", "").strip()

    html = fetch_text(dashboard_url, "DASHBOARD_HTML_SOURCE_URL")
    today_payload = fetch_json_optional(today_url)

    date = infer_date(today_payload, html)

    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_HTML_DIR.mkdir(exist_ok=True)

    write_text(ROOT / "index.html", html)
    write_text(HISTORY_HTML_DIR / f"{date}.html", html)

    meta = {
        "generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"),
        "date": date,
        "source": "Apps Script dashboard_html_source",
        "html_length": len(html),
    }

    write_json(DATA_DIR / "latest_meta.json", meta)

    if today_payload:
        write_json(DATA_DIR / "latest.json", today_payload)
        write_json(HISTORY_DATA_DIR / f"{date}.json", today_payload)

    print(f"Saved Apps Script dashboard HTML as static GitHub Pages index.html")
    print(f"date = {date}")
    print(f"html_length = {len(html)}")


if __name__ == "__main__":
    main()
