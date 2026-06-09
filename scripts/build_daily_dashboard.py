#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Pages build script｜Daily Macro Dashboard + AI Presenter Podcast v7

v4 = Macro Pricing Logic Mode
- Fetch Apps Script dashboard HTML.
- Fetch daily_summary JSON.
- Ask Gemini to produce macro_pricing_logic first.
- Ask Gemini to produce AI Presenter Podcast script from that logic.
- Inject Podcast player / transcript and GitHub history nav into static HTML.
- Save index.html, history/YYYY-MM-DD.html, data/macro_pricing_logic, data/presenter_guides.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_HTML_DIR = ROOT / "history"
HISTORY_DATA_DIR = DATA_DIR / "history"
PRICING_DIR = DATA_DIR / "macro_pricing_logic"
PRESENTER_DIR = DATA_DIR / "presenter_guides"
TW_TZ = timezone(timedelta(hours=8))


def fetch_text(url: str, name: str) -> str:
    if not url:
        raise RuntimeError(f"Missing required URL: {name}")
    req = urllib.request.Request(url, headers={"User-Agent": "macro-dashboard-ai-presenter-v4"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url: str, name: str) -> Dict[str, Any]:
    raw = fetch_text(url, name)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} did not return valid JSON. Preview:\n{raw[:800]}") from exc


def post_json(url: str, payload: Dict[str, Any], name: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "macro-dashboard-ai-presenter-v4"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=150) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} did not return valid JSON. Preview:\n{raw[:800]}") from exc


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def escape_html(value: Any) -> str:
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def clean_text(value: Any, max_len: int = 280) -> str:
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    return s[:max_len].rstrip() + "…" if len(s) > max_len else s


def remove_block(html: str, start: str, end: str) -> str:
    return re.sub(r"\n?" + re.escape(start) + r"[\s\S]*?" + re.escape(end) + r"\n?", "\n", html)


def daily_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    d = payload.get("daily_summary") if isinstance(payload, dict) else None
    return d if isinstance(d, dict) else {}


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def infer_date(payload: Dict[str, Any], html: str) -> str:
    d = daily_summary(payload)
    if d.get("date"):
        return str(d["date"])
    for pat in [r"主要資料日\s*[：:]\s*(\d{4}-\d{2}-\d{2})", r"資料日\s*[：:]\s*(\d{4}-\d{2}-\d{2})"]:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return datetime.now(TW_TZ).strftime("%Y-%m-%d")


def history_dates(current_date: str, limit: int = 7) -> List[str]:
    dates = {current_date} if current_date else set()
    for folder, suffix in [(HISTORY_HTML_DIR, ".html"), (HISTORY_DATA_DIR, ".json")]:
        if folder.exists():
            for p in folder.glob("*" + suffix):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem):
                    dates.add(p.stem)
    return sorted(dates, reverse=True)[:limit]


# =============================================================================
# Gemini helpers
# =============================================================================

def gemini_json(prompt: str, fallback: Any, task: str, temperature: float = 0.55) -> Any:
    import time

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash"

    if not api_key:
        print(f"WARN: missing GEMINI_API_KEY, fallback used for {task}", file=sys.stderr)
        return fallback

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "topP": 0.9,
            "responseMimeType": "application/json",
        },
    }

    retry_waits = [10, 25, 45, 75, 110]
    last_error = None

    for attempt, wait_seconds in enumerate(retry_waits, start=1):
        try:
            data = post_json(url, payload, task)
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )

            if not text:
                raise RuntimeError("empty Gemini text")

            return json.loads(text)

        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP Error {exc.code}: {detail[:500]}"

            if exc.code in (429, 500, 503, 504):
                print(
                    f"WARN: Gemini {task} temporary error on attempt {attempt}/{len(retry_waits)}: "
                    f"HTTP {exc.code}. Retry in {wait_seconds}s.",
                    file=sys.stderr,
                )
                time.sleep(wait_seconds)
                continue

            print(f"WARN: Gemini failed for {task}: {last_error}; fallback used", file=sys.stderr)
            return fallback

        except Exception as exc:
            last_error = str(exc)
            print(
                f"WARN: Gemini {task} failed on attempt {attempt}/{len(retry_waits)}: "
                f"{last_error}. Retry in {wait_seconds}s.",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)

    print(f"WARN: Gemini failed for {task} after retries: {last_error}; fallback used", file=sys.stderr)
    return fallback


# =============================================================================
# Step 1: Macro Pricing Logic
# =============================================================================

def fallback_pricing_logic(payload: Dict[str, Any]) -> Dict[str, Any]:
    d = daily_summary(payload)
    return {
        "pricing_context": {
            "market_was_pricing": "資料不足，暫以今日摘要主線判斷。",
            "new_information": clean_text(d.get("headline"), 160),
            "pricing_question": clean_text(d.get("headline"), 160) or "今天市場真正交易的是哪一股力量？",
        },
        "inflation_expectation": {
            "energy": {"direction": "unclear", "importance": "medium", "evidence": [], "judgment": ""},
            "supply_chain": {"direction": "unclear", "importance": "low", "evidence": [], "judgment": ""},
            "price_data": {"direction": "unclear", "importance": "medium", "evidence": [], "judgment": ""},
            "demand": {"direction": "unclear", "importance": "medium", "evidence": [], "judgment": ""},
            "labor_market": {"direction": "unclear", "importance": "medium", "evidence": [], "judgment": ""},
            "policy_expectation": {"direction": "unclear", "importance": "medium", "evidence": [], "judgment": ""},
            "summary": {"overall_direction": "unclear", "strength": "weak", "dominant_force": "", "offsetting_force": "", "judgment": clean_text(d.get("executive_summary"), 220)},
        },
        "rate_pricing": {
            "direction": "unclear",
            "inflation_link": "",
            "non_inflation_drivers": {"fed_policy": "", "treasury_supply_demand": "", "safe_haven_bond_buying": "", "growth_concern": "", "term_premium": ""},
            "dominant_force": "",
            "judgment": "",
        },
        "dollar_pricing": {"direction": "unclear", "rate_link": "", "other_drivers": [], "judgment": ""},
        "pricing_assessment": {
            "dominant_market_force": clean_text(d.get("headline"), 160),
            "offsetting_force": "",
            "most_non_obvious_signal": clean_text(d.get("divergence"), 220),
            "market_question": clean_text(d.get("headline"), 160) or "今天市場最值得追問的是什麼？",
            "one_sentence_takeaway": clean_text(d.get("macro_chain") or d.get("executive_summary"), 220),
            "next_watch": "觀察今日摘要列出的後續風險與數據。",
        },
    }


def pricing_prompt(payload: Dict[str, Any]) -> str:
    d = daily_summary(payload)
    compact = {
        "date": d.get("date"),
        "headline": d.get("headline"),
        "executive_summary": d.get("executive_summary"),
        "market_signals": as_list(d.get("market_signals"))[:6],
        "macro_chain": d.get("macro_chain"),
        "divergence": d.get("divergence"),
        "market_snapshot": d.get("market_snapshot"),
        "news_evidence": as_list(d.get("news_evidence"))[:6],
        "watchpoints": as_list(d.get("watchpoints"))[:6],
    }
    return f"""
你是機構級總經策略分析師。請根據 daily_summary 產生「每日總經定價邏輯」。

本任務只做分析層，不寫導讀稿。
後續 AI Presenter 會讀取你的分析結果，所以你必須把市場判斷拆清楚，不要只輸出 headline 摘要。

核心原則：
- 總經不是數學公式，不是 A 上升就必然 B 上升。
- 固定基準檢查路徑是：通膨預期 → 利率預期 → 美元指數 → 亞洲貨幣 / 黃金。
- 這只是基準路徑，不是鐵律；市場預期、資金流向、政策訊號會共同決定最後定價。
- 每一層都必須先看 daily_summary 提供的新聞、價格與市場訊號，再判斷 up / down / mixed / unclear，不得預設方向。
- 市場矛盾不是錯誤；若價格與基準傳導不一致，請保留矛盾，並解釋它是修正因子、抵銷力量、資料不足，或新主線早期訊號。
- 分析語氣應採中性、客觀、機構級研究口吻。即使訊號明顯，也應使用「主導、壓過、支撐、削弱、修正、尚待驗證、可能代表」等分析語言描述，不把單日訊號直接定調為確定的新趨勢。
- 對市場轉向、共振或異常訊號，應說明其「目前可能代表的定價變化」與「後續仍需驗證的條件」。若資料只支持短期判斷，請避免將其延伸為長期結論。
- 結論應保留不確定性層次，例如「目前較像」、「短線主導」、「仍需觀察」、「資料不足以確認」；分析語氣應避免過度戲劇化或絕對化。
- 不可新增 daily_summary 沒有的數字。
- 不可創造新聞。
- 不可給投資建議。
- 資料不足請寫 unclear / 待確認。
- 請只輸出 JSON，不要 Markdown，不要註解。

分析順序必須固定：

一、新聞與市場素材盤點
請先整理 daily_summary 中可用的新聞、政策訊號與市場價格反應。
本段只歸類，不直接下今日主線結論。

請分成：
1. 通膨相關素材：
   油價、能源、CPI / PPI / PCE、PMI / NMI、零售銷售、就業、Fed 通膨說法、地緣政治。
2. 利率相關素材：
   Fed 政策、公債供需、期限溢價、避險買債、成長擔憂、降息 / 升息預期變化。
3. 美元相關素材：
   利差、避險美元、美元流動性需求、其他貨幣自身弱點、美國相對經濟韌性。
4. 黃金相關素材：
   利率 / 實質利率、美元方向、避險需求、央行買盤、地緣政治。
5. 亞洲貨幣相關素材：
   美元壓力、本地資金流、央行政策、出口 / 科技產業、區域風險。

二、通膨預期形成
請先判斷今日通膨預期如何形成。
CPI / PPI / PCE、油價、PMI / NMI、就業與 Fed 通膨說法，應先進入本段，不可直接跳去解釋利率。

請檢查：
- energy：油價、OPEC、EIA、IEA、頁岩油、戰略儲備、荷姆茲海峽、戰爭供給風險。
- supply_chain：運價、原物料、制裁、港口、航道、供應瓶頸。
- price_data：CPI、PPI、PCE、核心 PCE、物價分項。
- demand：PMI、NMI、零售銷售、消費信心、企業訂單。
- labor_market：非農、ADP、初領失業金、續領失業金、薪資成長、聘僱或裁員新聞。
- policy_expectation：Fed 談話、通膨預期調查、關稅、財政刺激、政策不確定性。

請判斷：
- 哪些通道推升通膨預期？
- 哪些通道緩解或抵銷通膨預期？
- 今日通膨預期是 up / down / mixed / unclear？
- 強度是 strong / medium / weak？

三、利率定價
請承接第二段「通膨預期形成」的結論，分析今日利率偏強、偏弱或分歧的來源。

請先回答：
- 利率是否與通膨預期同向？
- 如果同向，是通膨預期如何傳導到利率？
- 如果不同向，是不是利率自身因子主導？

利率自身因子至少檢查：
1. Fed 政策訊號
2. 公債供需 / 長債賣壓
3. 期限溢價
4. 避險買債需求
5. 成長擔憂或降息預期變化

注意：
- CPI / PPI / PCE 只能作為第二段通膨預期判斷的背景，不應在本段重新獨立判斷通膨方向。
- 不可只寫「Fed 偏鷹」或「市場避險」，必須說明具體內容。
- 不得預設利率一定偏強。
- 若利率方向 mixed / unclear，請說明是哪幾股力量訊號交錯。

四、美元定價
請承接第三段「利率定價」，分析美元。

請回答：
- 美元是否與利率方向同向？
- 若同向，是利差 / 高利率預期如何影響美元？
- 若不同向，是否受到避險美元、美元流動性需求、其他貨幣自身弱點或美國相對經濟韌性修正？
- 不可預設美元一定受高利率支撐。
- 若 mixed / unclear，請說明是哪幾股力量訊號交錯。

五、黃金定價
請承接第三段「利率定價」與第四段「美元定價」，分析黃金。

請檢查：
1. 高利率 / 實質利率壓力
2. 美元方向
3. 避險需求
4. 央行買盤
5. 地緣政治

請回答：
- 黃金主要受哪一股力量主導？
- 若黃金與利率 / 美元不同向，是哪個因素修正？
- 不可預設黃金一定受高利率壓抑，也不可預設一定受避險推升。

六、亞洲貨幣：台幣、日圓、韓圜
請承接第四段「美元定價」，分別分析台幣、日圓、韓圜，不可只寫「亞幣」。

請回答：
- 台幣是否與美元壓力同向？若不同向，是本地資金流、央行政策、出口 / 科技產業、區域風險或其他因素修正？
- 日圓是否與美元壓力同向？若不同向，是日本自身政策、利差、避險需求或其他因素修正？
- 韓圜是否與美元壓力同向？若不同向，是韓國出口、股市資金、區域風險或其他因素修正？
- 若資料不足，請標示待確認。

七、市場矛盾與修正因子
請根據第二段到第六段，找出今日最值得追問的市場矛盾。

請回答：
- 正常基準傳導劇本應該怎麼走？
- 今日實際市場反應哪一段最不直覺？
- 這個矛盾是修正因子、抵銷力量、資料不足，還是新主線早期訊號？
- 它如何嵌入今日主線，避免敘事前後自我打架？
- AI Presenter 應該用哪個問題開場？

八、今日主線與下一個驗證點
請根據前面分析，收斂今日主線。

請回答：
- 今日市場最後最主導的定價力量是什麼？
- 主要抵銷或修正力量是什麼？
- 今日真正要記住的一句話是什麼？
- 下一個要觀察什麼來驗證？

請輸出固定 JSON：
{{
  "pricing_context": {{
    "market_was_pricing": "",
    "new_information": "",
    "pricing_question": ""
  }},
  "input_material_mapping": {{
    "inflation_materials": [],
    "rate_materials": [],
    "dollar_materials": [],
    "gold_materials": [],
    "asia_fx_materials": [],
    "mapping_summary": ""
  }},
  "inflation_expectation": {{
    "energy": {{"direction":"up / down / mixed / unclear", "importance":"high / medium / low", "evidence":[], "judgment":""}},
    "supply_chain": {{"direction":"up / down / mixed / unclear", "importance":"high / medium / low", "evidence":[], "judgment":""}},
    "price_data": {{"direction":"up / down / mixed / unclear", "importance":"high / medium / low", "evidence":[], "judgment":""}},
    "demand": {{"direction":"up / down / mixed / unclear", "importance":"high / medium / low", "evidence":[], "judgment":""}},
    "labor_market": {{"direction":"up / down / mixed / unclear", "importance":"high / medium / low", "evidence":[], "judgment":""}},
    "policy_expectation": {{"direction":"up / down / mixed / unclear", "importance":"high / medium / low", "evidence":[], "judgment":""}},
    "summary": {{
      "overall_direction":"up / down / mixed / unclear",
      "strength":"strong / medium / weak",
      "dominant_force":"",
      "offsetting_force":"",
      "judgment":""
    }}
  }},
  "rate_pricing": {{
    "direction":"up / down / mixed / unclear",
    "link_with_inflation_expectation":"",
    "fed_policy_signal":"",
    "treasury_supply_demand":"",
    "term_premium":"",
    "safe_haven_bond_buying":"",
    "growth_concern_or_cut_expectation":"",
    "dominant_force":"",
    "judgment":""
  }},
  "dollar_pricing": {{
    "direction":"up / down / mixed / unclear",
    "link_with_rates":"",
    "safe_haven_dollar":"",
    "liquidity_demand":"",
    "other_currency_weakness":"",
    "us_relative_growth_or_policy":"",
    "dominant_force":"",
    "judgment":""
  }},
  "gold_pricing": {{
    "direction":"up / down / mixed / unclear",
    "rate_or_real_rate_pressure":"",
    "dollar_effect":"",
    "safe_haven_demand":"",
    "central_bank_buying":"",
    "geopolitical_risk":"",
    "dominant_force":"",
    "judgment":""
  }},
  "asia_fx_pricing": {{
    "twd": {{"reaction":"", "consistent_with_dollar_pressure":"yes / no / mixed / unclear", "local_correction_factor":"", "judgment":""}},
    "jpy": {{"reaction":"", "consistent_with_dollar_pressure":"yes / no / mixed / unclear", "local_correction_factor":"", "judgment":""}},
    "krw": {{"reaction":"", "consistent_with_dollar_pressure":"yes / no / mixed / unclear", "local_correction_factor":"", "judgment":""}}
  }},
  "market_contradiction": {{
    "baseline_expectation":"",
    "actual_reaction":"",
    "most_non_obvious_link":"",
    "possible_explanation":"",
    "is_correction_or_new_mainline":"correction_factor / offsetting_force / data_uncertainty / new_mainline_signal / unclear",
    "how_to_integrate_into_main_theme":"",
    "presenter_story_angle": {{
      "opening_question":"",
      "normal_script":"",
      "where_it_breaks":"",
      "why_it_matters":"",
      "next_watch":""
    }}
  }},
  "pricing_assessment": {{
    "dominant_market_force":"",
    "offsetting_force":"",
    "most_non_obvious_signal":"",
    "market_question":"",
    "one_sentence_takeaway":"",
    "next_watch":""
  }}
}}

daily_summary:
{json.dumps(compact, ensure_ascii=False, indent=2)}
""".strip()



def generate_pricing_logic(payload: Dict[str, Any]) -> Dict[str, Any]:
    fallback = fallback_pricing_logic(payload)
    raw = gemini_json(pricing_prompt(payload), fallback, "Macro Pricing Logic", 0.45)
    if not isinstance(raw, dict):
        return fallback
    for k, v in fallback.items():
        if k == "asset_reaction":
            continue
        raw.setdefault(k, v)
    raw.pop("asset_reaction", None)
    if not isinstance(raw.get("pricing_assessment"), dict):
        raw["pricing_assessment"] = fallback["pricing_assessment"]
    return raw


# =============================================================================
# Step 2: Presenter sections
# =============================================================================

def fallback_presenter_podcast(logic: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    d = daily_summary(payload)
    a = logic.get("pricing_assessment", {}) if isinstance(logic, dict) else {}
    contradiction = logic.get("market_contradiction", {}) if isinstance(logic, dict) else {}

    title = clean_text("AI Presenter Podcast｜3 分鐘聽懂今日市場", 80)
    opening_question = clean_text(
        (contradiction.get("presenter_story_angle") or {}).get("opening_question")
        or a.get("market_question")
        or d.get("headline")
        or "今天市場真正交易的是什麼？",
        180,
    )
    normal_script = clean_text(
        (contradiction.get("presenter_story_angle") or {}).get("normal_script")
        or "一般來說，市場會從通膨預期出發，再傳導到利率、美元，最後反映在黃金與亞洲貨幣。",
        240,
    )
    where_breaks = clean_text(
        (contradiction.get("presenter_story_angle") or {}).get("where_it_breaks")
        or a.get("most_non_obvious_signal")
        or d.get("divergence")
        or "今天真正值得注意的是，部分價格反應並沒有完全照基準傳導路徑走。",
        260,
    )
    why_matters = clean_text(
        (contradiction.get("presenter_story_angle") or {}).get("why_it_matters")
        or contradiction.get("how_to_integrate_into_main_theme")
        or a.get("dominant_market_force")
        or "這代表市場可能正在用另一股力量修正原本的總經傳導。",
        260,
    )
    takeaway = clean_text(
        a.get("one_sentence_takeaway")
        or d.get("macro_chain")
        or d.get("executive_summary")
        or "今日市場主線仍需搭配後續數據與政策訊號驗證。",
        260,
    )
    watch = clean_text(
        a.get("next_watch")
        or (contradiction.get("presenter_story_angle") or {}).get("next_watch")
        or "觀察後續數據與政策訊號是否驗證今日主線。",
        200,
    )

    segments = [
        {
            "title": "開場問題",
            "narration": f"今天先抓一個問題：{opening_question} 這不是要追逐單一價格，而是要看市場最後把哪一股力量放在第一順位。",
            "pause_after_seconds": 1.0,
        },
        {
            "title": "正常劇本",
            "narration": f"先建立基準劇本。{normal_script} 但這條鏈不是公式，政策訊號、資金流向與避險需求，都可能在中間改變傳導方向。",
            "pause_after_seconds": 0.8,
        },
        {
            "title": "今日斷點",
            "narration": f"今天最值得看的斷點是：{where_breaks} 換句話說，市場不是沒有主線，而是在某一段傳導上出現修正。",
            "pause_after_seconds": 0.8,
        },
        {
            "title": "背後原因",
            "narration": f"這個修正之所以重要，是因為：{why_matters} 目前較像是市場定價重心的短線調整，仍需要後續數據驗證。",
            "pause_after_seconds": 0.8,
        },
        {
            "title": "收斂與觀察",
            "narration": f"今天可以先記住：{takeaway} 下一步要觀察的是：{watch} 這會決定今天的修正是短期反應，還是會延伸成更明確的市場主線。",
            "pause_after_seconds": 1.0,
        },
    ]
    full_script = "\n\n".join([item["narration"] for item in segments])
    return {
        "title": title,
        "summary": clean_text(takeaway, 180),
        "duration_target_seconds": 180,
        "segments": segments,
        "full_script": full_script,
        "tts_notes": {
            "tone": "中性、沉浸式、機構級市場導讀",
            "speaking_rate": "medium",
            "pause_style": "自然停頓；段落之間保留約 0.8 到 1 秒",
            "number_reading": "數字前後保留短暫停頓，避免連續快速朗讀",
        },
    }


def presenter_prompt(logic: Dict[str, Any], payload: Dict[str, Any]) -> str:
    d = daily_summary(payload)
    compact_daily = {
        "date": d.get("date"),
        "headline": d.get("headline"),
        "executive_summary": d.get("executive_summary"),
        "market_signals": as_list(d.get("market_signals"))[:5],
        "macro_chain": d.get("macro_chain"),
        "divergence": d.get("divergence"),
        "market_snapshot": d.get("market_snapshot"),
        "news_evidence": as_list(d.get("news_evidence"))[:5],
        "watchpoints": as_list(d.get("watchpoints"))[:5],
    }
    return f"""
你是 AI Presenter Podcast 的總經導讀主持人。

你的任務不是朗讀網頁，也不是重新分析市場。
你的任務是根據「每日總經定價邏輯 macro_pricing_logic」，寫出一段適合 TTS 朗讀、約 3 分鐘的沉浸式市場導讀稿。

分工原則：
- pricing_logic 已經完成市場判斷。
- 你不得重新判斷市場主線。
- 你只能把 pricing_logic 的判斷轉成自然、可聽、連貫的 Podcast 腳本。
- 如果 pricing_logic 有不確定或待確認，請保留不確定性，不要改成確定結論。

語氣原則：
- 中性、客觀、機構級研究口吻。
- 有節奏、有問題意識，但不要戲劇化。
- 像專業市場導讀，不像新聞播報，也不像財經節目標題。
- 即使訊號明顯，也使用「主導、壓過、支撐、削弱、修正、尚待驗證、可能代表」等分析語言。
- 不把單日訊號直接定調為長期趨勢。
- 對任何市場敘事、價格共振或傳導斷點，請以「市場目前較像在定價」、「短線主導因素」、「可能代表」、「仍需後續數據驗證」等方式描述；不得把單日市場反應直接寫成已確認的長期結構性事實。
- 不喊單、不誇大、不給投資建議。

聽感原則：
- 這是一段要被播放的 Podcast，不是給人逐字閱讀的報告。
- 句子要自然，避免過長。
- 每段只處理一個核心問題。
- 數字前後應有語氣停頓，避免連續堆數字。
- 轉場要自然，讓聽眾知道「為什麼下一段值得聽」。
- 避免密集名詞堆疊；必要時用一句白話解釋總經含義。

敘事結構固定：
1. 開場問題：從今日最不直覺的市場矛盾或價格斷點開場。
2. 正常劇本：說明基準傳導理論上應該怎麼走。
3. 今日斷點：指出今天哪一段沒有照劇本走，或哪一段特別順。
4. 背後原因：說明這是修正因子、抵銷力量、資料不足，還是新主線早期訊號。
5. 收斂與觀察：用一句話收斂今日主線，並說明下一個驗證點。

硬性限制：
1. 不可新增 daily_summary 或 pricing_logic 沒有的數字。
2. 不可創造新聞。
3. 不可推翻 pricing_logic 的判斷。
4. 不要說「本頁包含」、「這個區塊是」、「先看 Visual Note」這種網頁說明員語氣。
5. 不要使用箭頭符號。
6. 不要逐字複製 macro_chain。
7. 不要輸出 Markdown。
8. 只輸出合法 JSON。

請輸出固定 JSON：
{{
  "podcast": {{
    "title": "",
    "summary": "",
    "duration_target_seconds": 180,
    "segments": [
      {{
        "title": "開場問題",
        "narration": "",
        "pause_after_seconds": 1.0
      }},
      {{
        "title": "正常劇本",
        "narration": "",
        "pause_after_seconds": 0.8
      }},
      {{
        "title": "今日斷點",
        "narration": "",
        "pause_after_seconds": 0.8
      }},
      {{
        "title": "背後原因",
        "narration": "",
        "pause_after_seconds": 0.8
      }},
      {{
        "title": "收斂與觀察",
        "narration": "",
        "pause_after_seconds": 1.0
      }}
    ],
    "full_script": "請用 segments narration 之間的雙換行組成，不要接成單一大段",
    "tts_notes": {{
      "tone": "中性、沉浸式、機構級市場導讀",
      "speaking_rate": "medium",
      "pause_style": "自然停頓",
      "number_reading": "數字前後保留停頓"
    }}
  }}
}}

daily_summary:
{json.dumps(compact_daily, ensure_ascii=False, indent=2)}

macro_pricing_logic:
{json.dumps(logic, ensure_ascii=False, indent=2)}
""".strip()


def normalize_podcast(raw: Any, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("podcast"), dict):
        raw = raw["podcast"]

    if isinstance(raw, dict):
        segments = raw.get("segments")
        if not isinstance(segments, list):
            segments = raw.get("sections")

        normalized_segments = []
        if isinstance(segments, list):
            for i, item in enumerate(segments[:5]):
                if not isinstance(item, dict):
                    continue
                title = clean_text(item.get("title") or f"第 {i+1} 段", 40)
                narration = clean_text(item.get("narration") or item.get("text") or "", 520)
                pause = item.get("pause_after_seconds", 0.8)
                try:
                    pause = float(pause)
                except (TypeError, ValueError):
                    pause = 0.8
                if narration:
                    normalized_segments.append({
                        "title": title,
                        "narration": narration,
                        "pause_after_seconds": pause,
                    })

        if len(normalized_segments) >= 3:
            full_script = clean_text("\n\n".join([s["narration"] for s in normalized_segments]), 3200)
            return {
                "title": clean_text(raw.get("title") or fallback.get("title"), 80),
                "summary": clean_text(raw.get("summary") or fallback.get("summary"), 220),
                "duration_target_seconds": int(raw.get("duration_target_seconds") or 180),
                "segments": normalized_segments,
                "full_script": full_script,
                "tts_notes": raw.get("tts_notes") if isinstance(raw.get("tts_notes"), dict) else fallback.get("tts_notes", {}),
            }

    return fallback


def generate_presenter_podcast(logic: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    fallback = fallback_presenter_podcast(logic, payload)
    raw = gemini_json(presenter_prompt(logic, payload), {"podcast": fallback}, "AI Presenter Podcast", 0.55)
    return normalize_podcast(raw, fallback)


# =============================================================================
# HTML Injection
# =============================================================================

def inject_ai_presenter(html: str, podcast: Dict[str, Any], current_date: str, is_history: bool) -> str:
    html = remove_block(html, "<!-- GITHUB_AI_PRESENTER_START -->", "<!-- GITHUB_AI_PRESENTER_END -->")

    audio_file = ROOT / "assets" / "audio" / f"daily_ai_presenter_{current_date}.mp3"
    audio_src = ("../assets/audio/" if is_history else "assets/audio/") + f"daily_ai_presenter_{current_date}.mp3"

    if audio_file.exists():
        player_html = f'<audio class="github-ai-podcast-audio-v7" controls preload="metadata" src="{escape_html(audio_src)}"></audio>'
    else:
        player_html = '<span class="github-ai-podcast-pending-v7">語音尚未產生</span>'

    presenter = f"""
<!-- GITHUB_AI_PRESENTER_START -->
<style id="github-ai-presenter-style-v7">
.github-ai-podcast-v7{{max-width:980px;margin:0 auto 14px;padding:12px 18px;background:#fff;border:1px solid var(--theme-border,#E6CFA5);border-radius:999px;box-shadow:0 8px 22px rgba(15,23,42,.03)}}
.github-ai-podcast-row-v7{{display:flex;align-items:center;justify-content:space-between;gap:16px}}
.github-ai-podcast-left-v7{{display:flex;align-items:center;gap:12px;min-width:0;flex:1}}
.github-ai-podcast-icon-v7{{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#fff7e8;border:1px solid var(--theme-border,#E6CFA5);color:var(--theme-accent-text,#8A5A12);font-size:20px;font-weight:950;flex:0 0 auto}}
.github-ai-podcast-title-v7{{font-size:18px;font-weight:950;color:#172033;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.github-ai-podcast-controls-v7{{display:flex;align-items:center;justify-content:flex-end;flex:0 0 auto;min-width:270px}}
.github-ai-podcast-audio-v7{{width:270px;height:34px;display:block}}
.github-ai-podcast-pending-v7{{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--theme-border,#E6CFA5);border-radius:999px;background:#fffaf0;color:var(--theme-accent-text,#8A5A12);font-weight:900;font-size:13px;padding:8px 14px;white-space:nowrap}}
@media(max-width:760px){{.github-ai-podcast-v7{{border-radius:18px;padding:12px 13px}}.github-ai-podcast-row-v7{{display:block}}.github-ai-podcast-title-v7{{font-size:17px;white-space:normal}}.github-ai-podcast-controls-v7{{margin-top:10px;justify-content:flex-start;min-width:0}}.github-ai-podcast-audio-v7{{width:100%}}}}
</style>
<section class="github-ai-podcast-v7" id="githubAiPresenterV7" aria-label="AI 市場導讀 Podcast">
  <div class="github-ai-podcast-row-v7">
    <div class="github-ai-podcast-left-v7">
      <div class="github-ai-podcast-icon-v7">🎙️</div>
      <div class="github-ai-podcast-title-v7">AI 市場導讀</div>
    </div>
    <div class="github-ai-podcast-controls-v7">
      {player_html}
    </div>
  </div>
</section>
<!-- GITHUB_AI_PRESENTER_END -->
"""
    marker = 'class="top-date-meta-bar"'
    if marker in html:
        start = html.find(marker)
        end = html.find('</section>', start)
        if end >= 0:
            insert_at = end + len('</section>')
            return html[:insert_at] + '\n' + presenter + html[insert_at:]
    m = re.search(r'<body[^>]*>', html, flags=re.I)
    return html[:m.end()] + '\n' + presenter + html[m.end():] if m else presenter + html

def inject_history_nav(html: str, current_date: str, dates: List[str], is_history: bool) -> str:
    html = remove_block(html, "<!-- GITHUB_HISTORY_NAV_START -->", "<!-- GITHUB_HISTORY_NAV_END -->")
    if not dates:
        return html
    home = "../index.html" if is_history else "index.html"
    prefix = "../history/" if is_history else "history/"
    opts = "".join([f'<option value="{escape_html(prefix+d+".html")}"{" selected" if d==current_date else ""}>{escape_html(d + ("（最新）" if d==dates[0] else ""))}</option>' for d in dates])
    section = f'''
<!-- GITHUB_HISTORY_NAV_START -->
<style id="github-history-nav-style-v1">
.github-history-nav-v1{{max-width:980px;margin:18px auto 28px;padding:18px 20px;background:#fff;border:1px solid var(--theme-border,#CEE7D7);border-radius:18px;box-shadow:0 10px 28px rgba(15,23,42,.035)}}.github-history-nav-v1 *{{box-sizing:border-box}}.github-history-nav-head-v1{{display:flex;gap:14px;align-items:center;justify-content:space-between;margin-bottom:12px}}.github-history-nav-title-v1{{font-size:20px;font-weight:900;color:var(--theme-accent-text,#35724F)}}.github-history-nav-controls-v1{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end}}.github-history-select-v1{{min-width:220px;max-width:100%;border:1px solid var(--theme-border,#CEE7D7);border-radius:999px;padding:8px 12px;background:#fff;color:var(--theme-text,#111827);font-weight:750;font-size:14px}}.github-history-button-v1{{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--theme-border,#CEE7D7);border-radius:999px;padding:8px 13px;background:#fff;color:var(--theme-accent-text,#35724F);text-decoration:none;font-weight:850;font-size:14px;cursor:pointer}}.github-history-note-v1{{color:#64748b;font-size:13px;line-height:1.6}}.history-lite-section-v1,.historical-daily-summary-dropdown-section,.history-daily-summary-dropdown-section,.history-panel-v2,.history-card{{display:none!important}}@media(max-width:760px){{.github-history-nav-v1{{margin:14px auto 22px;padding:14px;border-radius:16px}}.github-history-nav-head-v1{{display:block}}.github-history-nav-title-v1{{margin-bottom:10px;font-size:18px}}.github-history-nav-controls-v1{{justify-content:flex-start}}.github-history-select-v1{{width:100%}}}}
</style>
<section class="github-history-nav-v1" aria-label="歷史回顧"><div class="github-history-nav-head-v1"><div class="github-history-nav-title-v1">🗂️ 歷史回顧</div><div class="github-history-nav-controls-v1"><select id="githubHistorySelectV1" class="github-history-select-v1" aria-label="選擇歷史日期">{opts}</select><button type="button" class="github-history-button-v1" onclick="openGithubHistoryV1()">開啟</button><a class="github-history-button-v1" href="{escape_html(home)}">回今日</a></div></div><div class="github-history-note-v1">GitHub Pages 會保存每日完整頁面快照；目前顯示最近 7 天。</div></section>
<script id="github-history-nav-script-v1">function openGithubHistoryV1(){{var s=document.getElementById('githubHistorySelectV1');if(!s||!s.value)return;window.location.href=s.value;}}</script>
<!-- GITHUB_HISTORY_NAV_END -->
'''
    m = re.search(r'</body>', html, flags=re.I)
    return html[:m.start()] + section + '\n' + html[m.start():] if m else html + section



def inject_mobile_overflow_fix(html: str) -> str:
    """
    GitHub Pages mobile safeguard.

    The Apps Script dashboard HTML is fetched as raw_html, so if any upstream
    news/evidence/source block contains fixed width, long English strings, URLs,
    or nowrap text, it can create horizontal overflow on mobile. This injected
    CSS keeps the page inside the viewport without changing the data pipeline.
    """
    html = remove_block(html, "<!-- GITHUB_MOBILE_OVERFLOW_FIX_START -->", "<!-- GITHUB_MOBILE_OVERFLOW_FIX_END -->")

    style = """
<!-- GITHUB_MOBILE_OVERFLOW_FIX_START -->
<style id="github-mobile-overflow-fix-v1">
html,body{max-width:100%;overflow-x:hidden}
*,*::before,*::after{box-sizing:border-box}
img,svg,canvas,video{max-width:100%;height:auto}
table{max-width:100%}
a{overflow-wrap:anywhere;word-break:break-word}

@media(max-width:760px){
  body{width:100%;max-width:100%;overflow-x:hidden!important}
  main,section,article,div{max-width:100%}

  [class*="news"],[class*="News"],
  [class*="headline"],[class*="Headline"],
  [class*="evidence"],[class*="Evidence"],
  [class*="source"],[class*="Source"],
  [class*="article"],[class*="Article"],
  [class*="event"],[class*="Event"],
  [class*="focus"],[class*="Focus"]{
    max-width:100%!important;
    min-width:0!important;
    overflow-wrap:anywhere!important;
    word-break:break-word!important;
    white-space:normal!important;
  }

  [class*="news"] *,[class*="News"] *,
  [class*="headline"] *,[class*="Headline"] *,
  [class*="evidence"] *,[class*="Evidence"] *,
  [class*="source"] *,[class*="Source"] *,
  [class*="article"] *,[class*="Article"] *,
  [class*="event"] *,[class*="Event"] *,
  [class*="focus"] *,[class*="Focus"] *{
    max-width:100%!important;
    min-width:0!important;
    overflow-wrap:anywhere!important;
    word-break:break-word!important;
    white-space:normal!important;
  }

  [class*="card"],[class*="Card"],
  [class*="grid"],[class*="Grid"],
  [class*="list"],[class*="List"],
  [class*="row"],[class*="Row"],
  [class*="item"],[class*="Item"]{
    min-width:0!important;
    max-width:100%!important;
  }

  table{
    display:block;
    overflow-x:auto;
    -webkit-overflow-scrolling:touch;
  }
}
</style>
<!-- GITHUB_MOBILE_OVERFLOW_FIX_END -->
"""

    if re.search(r"</head>", html, flags=re.I):
        return re.sub(r"</head>", style + "\n</head>", html, count=1, flags=re.I)

    m = re.search(r"<body[^>]*>", html, flags=re.I)
    if m:
        return html[:m.end()] + "\n" + style + html[m.end():]

    return style + html


def main() -> None:
    dashboard_url = os.environ.get("DASHBOARD_HTML_SOURCE_URL", "").strip()
    today_url = os.environ.get("TODAY_DAILY_SOURCE_URL", "").strip()
    raw_html = fetch_text(dashboard_url, "DASHBOARD_HTML_SOURCE_URL")
    today_payload = fetch_json(today_url, "TODAY_DAILY_SOURCE_URL")
    current_date = infer_date(today_payload, raw_html)

    for folder in [DATA_DIR, HISTORY_HTML_DIR, HISTORY_DATA_DIR, PRICING_DIR, PRESENTER_DIR]:
        folder.mkdir(parents=True, exist_ok=True)

    dates = history_dates(current_date, 7)
    pricing_logic = generate_pricing_logic(today_payload)
    podcast = generate_presenter_podcast(pricing_logic, today_payload)

    index_html = inject_history_nav(
        inject_mobile_overflow_fix(inject_ai_presenter(raw_html, podcast, current_date, False)),
        current_date,
        dates,
        False,
    )
    history_html = inject_history_nav(
        inject_mobile_overflow_fix(inject_ai_presenter(raw_html, podcast, current_date, True)),
        current_date,
        dates,
        True,
    )

    write_text(ROOT / "index.html", index_html)
    write_text(HISTORY_HTML_DIR / f"{current_date}.html", history_html)
    write_json(DATA_DIR / "latest.json", today_payload)
    write_json(HISTORY_DATA_DIR / f"{current_date}.json", today_payload)
    write_json(PRICING_DIR / "latest.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "mode": "macro_pricing_logic_v4", "logic": pricing_logic})
    write_json(PRICING_DIR / f"{current_date}.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "mode": "macro_pricing_logic_v4", "logic": pricing_logic})
    write_json(PRESENTER_DIR / "latest.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "mode": "daily_macro_podcast_v1", "podcast": podcast})
    write_json(PRESENTER_DIR / f"{current_date}.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "mode": "daily_macro_podcast_v1", "podcast": podcast})
    write_json(DATA_DIR / "latest_meta.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "history_dates": dates, "source": "Apps Script dashboard_html_source", "html_length": len(raw_html), "index_html_length": len(index_html), "ai_presenter": "daily_macro_podcast_v1_compact_ui_v7", "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")})

    print("Saved Apps Script dashboard HTML as static GitHub Pages index.html")
    print(f"date = {current_date}")
    print(f"history_dates = {', '.join(dates)}")
    print(f"raw_html_length = {len(raw_html)}")
    print(f"index_html_length = {len(index_html)}")
    print("ai_presenter = daily_macro_podcast_v1_compact_ui_v7")


if __name__ == "__main__":
    main()
