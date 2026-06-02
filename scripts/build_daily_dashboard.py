#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GitHub Pages：直接抓 Apps Script 完整 HTML，不重新組版。
並在 GitHub 端插入「歷史回顧」下拉選單。

需要 GitHub Secrets：
- DASHBOARD_HTML_SOURCE_URL

選配：
- TODAY_DAILY_SOURCE_URL
  只用來取得 date，方便保存 history/YYYY-MM-DD.html。
  如果沒有設定，會用台北時間今天日期。

輸出：
- index.html
- history/YYYY-MM-DD.html
- data/latest_meta.json
- data/latest.json（若 TODAY_DAILY_SOURCE_URL 可用）
- data/history/YYYY-MM-DD.json（若 TODAY_DAILY_SOURCE_URL 可用）
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List


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
            "User-Agent": "macro-dashboard-github-pages-html-snapshot/1.1",
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
                "User-Agent": "macro-dashboard-github-pages-html-snapshot/1.1",
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


def escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def get_existing_history_dates(current_date: str, limit: int = 7) -> List[str]:
    dates = set()

    if HISTORY_HTML_DIR.exists():
        for path in HISTORY_HTML_DIR.glob("*.html"):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
                dates.add(path.stem)

    if HISTORY_DATA_DIR.exists():
        for path in HISTORY_DATA_DIR.glob("*.json"):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
                dates.add(path.stem)

    if current_date:
        dates.add(current_date)

    return sorted(dates, reverse=True)[:limit]


def remove_old_github_history_nav(html: str) -> str:
    pattern = re.compile(
        r"\n?<!-- GITHUB_HISTORY_NAV_START -->[\s\S]*?<!-- GITHUB_HISTORY_NAV_END -->\n?",
        re.MULTILINE,
    )
    return pattern.sub("\n", html)


def inject_github_history_nav(html: str, current_date: str, dates: List[str], is_history_page: bool) -> str:
    html = remove_old_github_history_nav(html)

    if not dates:
        return html

    home_href = "../index.html" if is_history_page else "index.html"
    history_prefix = "../history/" if is_history_page else "history/"

    options = []
    for d in dates:
        label = d + ("（最新）" if d == dates[0] else "")
        selected = " selected" if d == current_date else ""
        value = history_prefix + d + ".html"
        options.append(
            f'<option value="{escape_html(value)}"{selected}>{escape_html(label)}</option>'
        )

    section = f"""
<!-- GITHUB_HISTORY_NAV_START -->
<style id="github-history-nav-style-v1">
  .github-history-nav-v1 {{
    max-width: 980px;
    margin: 18px auto 28px;
    padding: 18px 20px;
    background: #ffffff;
    border: 1px solid var(--theme-border, #CEE7D7);
    border-radius: 18px;
    box-shadow: 0 10px 28px rgba(15,23,42,.035);
  }}
  .github-history-nav-v1 * {{
    box-sizing: border-box;
  }}
  .github-history-nav-head-v1 {{
    display: flex;
    gap: 14px;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }}
  .github-history-nav-title-v1 {{
    font-size: 20px;
    font-weight: 900;
    color: var(--theme-accent-text, #35724F);
  }}
  .github-history-nav-controls-v1 {{
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-end;
  }}
  .github-history-select-v1 {{
    min-width: 220px;
    max-width: 100%;
    border: 1px solid var(--theme-border, #CEE7D7);
    border-radius: 999px;
    padding: 8px 12px;
    background: #fff;
    color: var(--theme-text, #111827);
    font-weight: 750;
    font-size: 14px;
  }}
  .github-history-button-v1 {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--theme-border, #CEE7D7);
    border-radius: 999px;
    padding: 8px 13px;
    background: #fff;
    color: var(--theme-accent-text, #35724F);
    text-decoration: none;
    font-weight: 850;
    font-size: 14px;
    cursor: pointer;
  }}
  .github-history-note-v1 {{
    color: #64748b;
    font-size: 13px;
    line-height: 1.6;
  }}

  /* GitHub 正式前台不再使用 Apps Script 原本歷史下拉區 */
  .history-lite-section-v1,
  .historical-daily-summary-dropdown-section,
  .history-daily-summary-dropdown-section,
  .history-panel-v2,
  .history-card {{
    display: none !important;
  }}

  @media (max-width: 760px) {{
    .github-history-nav-v1 {{
      margin: 14px auto 22px;
      padding: 14px;
      border-radius: 16px;
    }}
    .github-history-nav-head-v1 {{
      display: block;
    }}
    .github-history-nav-title-v1 {{
      margin-bottom: 10px;
      font-size: 18px;
    }}
    .github-history-nav-controls-v1 {{
      justify-content: flex-start;
    }}
    .github-history-select-v1 {{
      width: 100%;
    }}
  }}
</style>

<section class="github-history-nav-v1" aria-label="歷史回顧">
  <div class="github-history-nav-head-v1">
    <div class="github-history-nav-title-v1">📅 歷史回顧</div>
    <div class="github-history-nav-controls-v1">
      <select id="githubHistorySelectV1" class="github-history-select-v1" aria-label="選擇歷史日期">
        {''.join(options)}
      </select>
      <button type="button" class="github-history-button-v1" onclick="openGithubHistoryV1()">開啟</button>
      <a class="github-history-button-v1" href="{escape_html(home_href)}">回今日</a>
    </div>
  </div>
  <div class="github-history-note-v1">
    GitHub Pages 會保存每日完整頁面快照；目前顯示最近 7 天。
  </div>
</section>

<script id="github-history-nav-script-v1">
  function openGithubHistoryV1() {{
    var select = document.getElementById('githubHistorySelectV1');
    if (!select || !select.value) return;
    window.location.href = select.value;
  }}
</script>
<!-- GITHUB_HISTORY_NAV_END -->
"""

    if "</body>" in html:
        return html.replace("</body>", section + "\n</body>", 1)

    return html + section


def main() -> None:
    dashboard_url = os.environ.get("DASHBOARD_HTML_SOURCE_URL", "").strip()
    today_url = os.environ.get("TODAY_DAILY_SOURCE_URL", "").strip()

    raw_html = fetch_text(dashboard_url, "DASHBOARD_HTML_SOURCE_URL")
    today_payload = fetch_json_optional(today_url)

    current_date = infer_date(today_payload, raw_html)

    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_HTML_DIR.mkdir(exist_ok=True)

    dates = get_existing_history_dates(current_date, limit=7)

    index_html = inject_github_history_nav(
        raw_html,
        current_date=current_date,
        dates=dates,
        is_history_page=False,
    )

    history_html = inject_github_history_nav(
        raw_html,
        current_date=current_date,
        dates=dates,
        is_history_page=True,
    )

    write_text(ROOT / "index.html", index_html)
    write_text(HISTORY_HTML_DIR / f"{current_date}.html", history_html)

    meta = {
        "generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"),
        "date": current_date,
        "history_dates": dates,
        "source": "Apps Script dashboard_html_source",
        "html_length": len(raw_html),
        "index_html_length": len(index_html),
    }

    write_json(DATA_DIR / "latest_meta.json", meta)

    if today_payload:
        write_json(DATA_DIR / "latest.json", today_payload)
        write_json(HISTORY_DATA_DIR / f"{current_date}.json", today_payload)

    print("Saved Apps Script dashboard HTML as static GitHub Pages index.html")
    print(f"date = {current_date}")
    print(f"history_dates = {', '.join(dates)}")
    print(f"raw_html_length = {len(raw_html)}")
    print(f"index_html_length = {len(index_html)}")


if __name__ == "__main__":
    main()
