#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
No-API diagnostic｜Check whether Apps Script dashboard HTML supports mobile chart point tap.

This script only fetches DASHBOARD_HTML_SOURCE_URL and inspects the returned HTML.
It does NOT call Gemini and does NOT generate podcast / pricing logic.

Required env:
- DASHBOARD_HTML_SOURCE_URL

Output:
- data/daily_dashboard_chart_point_support_check.json
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
TW_TZ = timezone(timedelta(hours=8))


def fetch_text(url: str) -> str:
    if not url:
        raise RuntimeError("Missing DASHBOARD_HTML_SOURCE_URL")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "daily-dashboard-chart-point-support-check"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


def count_pattern(html: str, pattern: str) -> int:
    return len(re.findall(pattern, html, flags=re.I))


def main() -> None:
    url = os.environ.get("DASHBOARD_HTML_SOURCE_URL", "").strip()
    html = fetch_text(url)

    checks: Dict[str, Any] = {
        "generated_at_tw": datetime.now(TW_TZ).isoformat(timespec="seconds"),
        "html_length": len(html),
        "supports_svg_spark_point_data_tip": bool(re.search(r'class=["\'][^"\']*spark-point[^"\']*["\'][^>]*data-tip=', html, flags=re.I)),
        "supports_svg_data_tooltip": bool(re.search(r'data-tooltip=', html, flags=re.I)),
        "has_spark_point": bool(re.search(r'class=["\'][^"\']*spark-point[^"\']*["\']', html, flags=re.I)),
        "has_data_tip": bool(re.search(r'data-tip=', html, flags=re.I)),
        "has_spark_tooltip": bool(re.search(r'class=["\'][^"\']*spark-tooltip[^"\']*["\']', html, flags=re.I)),
        "has_canvas": bool(re.search(r'<canvas\b', html, flags=re.I)),
        "has_chartjs": bool(re.search(r'\bChart\s*\(', html, flags=re.I)),
        "counts": {
            "spark_point": count_pattern(html, r'class=["\'][^"\']*spark-point[^"\']*["\']'),
            "data_tip": count_pattern(html, r'data-tip='),
            "data_tooltip": count_pattern(html, r'data-tooltip='),
            "spark_tooltip": count_pattern(html, r'class=["\'][^"\']*spark-tooltip[^"\']*["\']'),
            "canvas": count_pattern(html, r'<canvas\b'),
            "chart_constructor": count_pattern(html, r'\bChart\s*\('),
            "svg": count_pattern(html, r'<svg\b'),
            "circle": count_pattern(html, r'<circle\b'),
        },
    }

    if checks["supports_svg_spark_point_data_tip"]:
        checks["verdict"] = "OK: Apps Script deployed HTML contains .spark-point[data-tip]. Mobile tap tooltip can be supported by the GitHub injection layer."
    elif checks["supports_svg_data_tooltip"]:
        checks["verdict"] = "OK: Apps Script deployed HTML contains data-tooltip points. Mobile tap tooltip can be supported."
    elif checks["has_canvas"] and checks["has_chartjs"]:
        checks["verdict"] = "PARTIAL: Apps Script deployed HTML uses Chart.js canvas. Mobile tap may work through Chart.js binding, but it depends on chart instance availability."
    elif checks["counts"]["svg"] > 0 and checks["counts"]["circle"] == 0:
        checks["verdict"] = "NO: Apps Script deployed HTML appears to draw SVG lines without clickable circle points. Code.gs spark_() must be updated/redeployed first."
    else:
        checks["verdict"] = "NO/UNKNOWN: No supported clickable chart point format found in deployed HTML."

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "daily_dashboard_chart_point_support_check.json"
    out.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(checks, ensure_ascii=False, indent=2))

    # Exit non-zero only when clearly unsupported. UNKNOWN stays zero so artifact can be inspected.
    if checks["verdict"].startswith("NO:"):
        sys.exit(2)


if __name__ == "__main__":
    main()
