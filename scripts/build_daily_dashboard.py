#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Pages build script｜Daily Macro Dashboard + AI Presenter v4

v4 = Macro Pricing Logic Mode
- Fetch Apps Script dashboard HTML.
- Fetch daily_summary JSON.
- Ask Gemini to produce macro_pricing_logic first.
- Ask Gemini to produce AI Presenter sections from that logic.
- Inject AI Presenter and GitHub history nav into static HTML.
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
        "asset_reaction": {"asia_fx": {"twd": "", "jpy": "", "krw": ""}, "gold": {"rate_pressure": "", "safe_haven_support": "", "dominant_force": "", "judgment": ""}},
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
        raw.setdefault(k, v)
    if not isinstance(raw.get("pricing_assessment"), dict):
        raw["pricing_assessment"] = fallback["pricing_assessment"]
    return raw


# =============================================================================
# Step 2: Presenter sections
# =============================================================================

def fallback_presenter_sections(logic: Dict[str, Any], payload: Dict[str, Any]) -> List[Dict[str, str]]:
    d = daily_summary(payload)
    a = logic.get("pricing_assessment", {}) if isinstance(logic, dict) else {}
    q = clean_text(a.get("market_question") or d.get("headline"), 170)
    non_obvious = clean_text(a.get("most_non_obvious_signal") or d.get("divergence"), 220)
    takeaway = clean_text(a.get("one_sentence_takeaway") or d.get("macro_chain") or d.get("executive_summary"), 240)
    watch = clean_text(a.get("next_watch") or "觀察後續數據與政策訊號是否驗證今日主線。", 180)

    return [
        {
            "title": "Opening Hook",
            "target": "top",
            "narration": f"今天市場表面上有一條主線，但真正值得追問的是：{q} 如果只看 headline，會以為答案很直接；但把價格反應放進來看，最關鍵的是這個不直覺訊號：{non_obvious}",
        },
        {
            "title": "Transmission Setup",
            "target": "visual",
            "narration": "照理說，市場會先從通膨預期看起，再傳到利率、美元，最後反映在亞洲貨幣與黃金。但今天不能把這條鏈當成公式，因為政策訊號、資金流向與避險需求，都可能在中間改變傳導方向。",
        },
        {
            "title": "Market Evidence",
            "target": "market",
            "narration": f"價格證據的重點不是誰漲誰跌，而是哪一段沒有照劇本走。今天最需要盯住的是：{non_obvious} 這代表主線沒有消失，但在局部市場出現了修正。",
        },
        {
            "title": "Narrative Check",
            "target": "news",
            "narration": "新聞與政策訊號要回答的是：這個分歧是雜訊，還是有基本面支撐？如果新聞只支持主線，分歧可能短暫；如果新聞也能解釋資金流，那它就可能成為新的定價線索。",
        },
        {
            "title": "Closing Takeaway",
            "target": "bottom",
            "narration": f"今天可以先記住一句話：{takeaway} 接下來要驗證的是：{watch} 也就是看這個修正只是短期反應，還是會變成新的市場主線。",
        },
    ]


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
你是 AI Presenter，一位具備千萬訂閱級敘事能力的機構級總經導讀主持人。

你的任務不是朗讀網頁，也不是重新分析市場。
你的任務是根據「每日總經定價邏輯 macro_pricing_logic」，像人類簡報者一樣，帶使用者看懂今天市場真正交易的主線。

最重要的原則：
- 你不是在介紹網頁區塊。
- 你是在帶觀眾理解「今天市場哪裡不直覺」。
- 每一段都要圍繞 macro_pricing_logic.pricing_assessment.most_non_obvious_signal。
- 不要平均導覽所有內容；今天只抓一個最值得追問的傳導斷點來說清楚。
- 每段都要有「問題感」，不是摘要感。

基準總經框架：
通膨預期 → 利率預期 → 美元指數 → 亞洲貨幣 / 黃金

但這不是公式，不是 A 上升就必然 B 上升。
你要用「市場預期、資金流向、政策訊號」三者交集來解釋今天市場定價。

口吻：
- 專業，但要像人類主持人。
- 有 Hook、有節奏、有問題意識。
- 可以像 YouTuber 一樣抓注意力，但不能浮誇。
- 像總經分析師一樣講邏輯，但不能像報告摘要。
- 不喊單、不誇大、不給投資建議。

硬性限制：
1. 不可新增 daily_summary 或 pricing_logic 沒有的數字。
2. 不可創造新聞。
3. 不可推翻 pricing_logic 的判斷。
4. 不可使用聳動詞，例如「崩盤、暴漲、史詩級、必看、翻倍」。
5. 不要說「本頁包含」、「這個區塊是」、「先看 Visual Note」、「再看新聞敘事驗證」這種網頁說明員語氣。
6. 每段 90～170 字，繁體中文。
7. 只輸出 JSON，不要 Markdown，不要註解。

敘事硬規則：
1. Opening Hook 必須從「最不直覺的傳導斷點」開場。
   - 不要重寫 headline。
   - 不要直接說今天主線是什麼。
   - 必須先丟出一個市場問題。
   - 句型方向：
     「今天市場表面上很好懂：A 發生，所以 B 跟著走。但真正值得追問的是，為什麼 C 沒有照劇本走？」

2. 每段都要先講「為什麼這一段值得看」，不要只說「看哪一頁」。
   - 禁止：「先看 Visual Market Note」
   - 改成：「如果照正常傳導鏈，強勁數據應該先推升通膨預期，再帶動利率與美元；但今天真正要看的，是這條鏈走到哪裡開始出現修正。」

3. 必須先講正常劇本，再講今天偏離劇本的地方。
   - 正常劇本：通膨預期 / 利率 / 美元 / 亞幣 / 黃金理論上應該如何反應。
   - 今日偏離：哪個資產、哪個訊號、哪段傳導沒有照常走。
   - 解釋：是政策、資金流、避險需求，還是區域因素造成修正。

4. Presenter 要像在做一場 3 分鐘簡報。
   - 第一段：丟矛盾。
   - 第二段：建立正常傳導劇本。
   - 第三段：用市場價格指出斷點。
   - 第四段：用新聞與政策解釋為什麼斷點存在。
   - 第五段：收斂成一句人類聽得懂的結論與下一個驗證點。

5. 不要把五段寫成五個互不相干的摘要。
   - 每一段都要接續同一個核心問題。
   - 例如若核心問題是「強美元下台幣為什麼逆勢」，五段都要圍繞這個問題推進。

6. 不要只說「資金流」三個字。
   - 若提到資金流，必須說明它是在修正哪一段傳導。
   - 例：「它不是推翻強美元主線，而是在亞洲貨幣這一段形成局部修正。」

7. Narrative Check 不能寫空話。
   - 禁止：「確認新聞、政策與資金流能否解釋價格反應」
   - 必須具體寫出：
     - 哪個新聞支持主線
     - 哪個新聞或訊號解釋分歧
     - 這是推翻主線，還是修正主線

請產生 5 段 JSON 陣列，欄位固定：
[
  {{"title":"Opening Hook","target":"top","narration":"..."}},
  {{"title":"Transmission Setup","target":"visual","narration":"..."}},
  {{"title":"Market Evidence","target":"market","narration":"..."}},
  {{"title":"Narrative Check","target":"news","narration":"..."}},
  {{"title":"Closing Takeaway","target":"bottom","narration":"..."}}
]

每段任務：

1. Opening Hook：
   用 pricing_assessment.most_non_obvious_signal 或 pricing_assessment.market_question 開場。
   必須指出今天市場「表面上合理，但真正奇怪的是什麼」。

2. Transmission Setup：
   說明正常總經傳導劇本應該如何走。
   再指出今天這條鏈在哪裡可能被修正。
   不要說「先看 Visual Note」。

3. Market Evidence：
   用 pricing_logic 中的價格與資產反應，指出哪一段傳導順、哪一段不順。
   必須明確講出「最不直覺的價格反應」。

4. Narrative Check：
   用 pricing_logic 的 new_information、inflation_expectation、rate_pricing、dollar_pricing、asset_reaction 解釋：
   - 哪些新聞 / 數據支持主線
   - 哪些力量形成修正
   - 這是主線被推翻，還是主線中的局部修正

5. Closing Takeaway：
   用 pricing_assessment.one_sentence_takeaway 收斂。
   但不能只是複製原句，要改成自然口語。
   最後用 pricing_assessment.next_watch 指出下一個驗證點。

輸出品質要求：
- 每段都必須像人類在講話，不要像 JSON 摘要。
- 不要使用箭頭符號「->」。
- 不要逐字複製 macro_chain。
- 不要寫「這個問題的重點不是單一數字」這種抽象套話。
- 儘量使用「照理說」、「但今天真正奇怪的是」、「換句話說」、「這代表」這類口語化邏輯銜接。
- 如果資料不足，請說「這一點還需要後續數據確認」，不要硬補。

daily_summary:
{json.dumps(compact_daily, ensure_ascii=False, indent=2)}

macro_pricing_logic:
{json.dumps(logic, ensure_ascii=False, indent=2)}
""".strip()


def normalize_sections(raw: Any, fallback: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if isinstance(raw, dict) and isinstance(raw.get("sections"), list):
        raw = raw["sections"]
    if not isinstance(raw, list):
        return fallback
    targets = ["top", "visual", "market", "news", "bottom"]
    out = []
    for i, item in enumerate(raw[:5]):
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title") or f"Section {i+1}", 50)
        target = clean_text(item.get("target") or targets[min(i, 4)], 20)
        text = clean_text(item.get("narration") or item.get("text"), 340)
        if target not in targets:
            target = targets[min(i, 4)]
        if text:
            out.append({"title": title, "target": target, "narration": text})
    return out if len(out) == 5 else fallback


def generate_presenter_sections(logic: Dict[str, Any], payload: Dict[str, Any]) -> List[Dict[str, str]]:
    fallback = fallback_presenter_sections(logic, payload)
    raw = gemini_json(presenter_prompt(logic, payload), fallback, "AI Presenter", 0.65)
    return normalize_sections(raw, fallback)


# =============================================================================
# HTML Injection
# =============================================================================

def inject_ai_presenter(html: str, sections: List[Dict[str, str]]) -> str:
    html = remove_block(html, "<!-- GITHUB_AI_PRESENTER_START -->", "<!-- GITHUB_AI_PRESENTER_END -->")
    sections_json = json.dumps(sections, ensure_ascii=False)
    presenter = f'''
<!-- GITHUB_AI_PRESENTER_START -->
<style id="github-ai-presenter-style-v4">
.github-ai-presenter-v4{{max-width:980px;margin:0 auto 18px;padding:18px 20px;background:#fff;border:1px solid var(--theme-border,#CEE7D7);border-radius:18px;box-shadow:0 10px 28px rgba(15,23,42,.035)}}
.github-ai-presenter-head-v4{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:12px}}
.github-ai-presenter-title-v4{{font-size:22px;font-weight:950;color:var(--theme-accent-text,#35724F);line-height:1.35}}
.github-ai-presenter-subtitle-v4{{color:#64748b;font-size:13px;line-height:1.6;margin-top:4px}}
.github-ai-presenter-badge-v4{{white-space:nowrap;border:1px solid var(--theme-border,#CEE7D7);border-radius:999px;padding:6px 10px;color:var(--theme-accent-text,#35724F);font-weight:850;font-size:12px;background:#fff}}
.github-ai-presenter-body-v4{{border:1px solid var(--theme-border,#CEE7D7);border-radius:14px;background:#fbfcfb;padding:14px 15px}}
.github-ai-presenter-step-title-v4{{font-weight:900;color:#172033;margin-bottom:7px;font-size:15px}}
.github-ai-presenter-text-v4{{color:#374151;font-size:15px;line-height:1.8}}
.github-ai-presenter-controls-v4{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}
.github-ai-presenter-button-v4{{border:1px solid var(--theme-border,#CEE7D7);border-radius:999px;padding:8px 13px;background:#fff;color:var(--theme-accent-text,#35724F);font-weight:850;cursor:pointer;font-size:14px}}
.github-ai-presenter-progress-v4{{color:#64748b;font-size:13px;margin-top:8px}}
.github-ai-presenter-highlight-v4{{outline:3px solid rgba(53,114,79,.16);outline-offset:4px;transition:outline .25s ease}}
@media(max-width:760px){{.github-ai-presenter-v4{{margin:0 auto 14px;padding:14px;border-radius:16px}}.github-ai-presenter-head-v4{{display:block}}.github-ai-presenter-title-v4{{font-size:19px}}.github-ai-presenter-badge-v4{{display:inline-block;margin-top:8px}}.github-ai-presenter-button-v4{{flex:1 1 auto}}}}
</style>
<section class="github-ai-presenter-v4" id="githubAiPresenterV4" aria-label="AI Presenter">
  <div class="github-ai-presenter-head-v4"><div><div class="github-ai-presenter-title-v4">AI Presenter｜3 分鐘看懂今日市場</div><div class="github-ai-presenter-subtitle-v4">先判斷今日總經定價邏輯，再用簡報方式帶你看主線、證據與分歧。</div></div><div class="github-ai-presenter-badge-v4">Macro Pricing Logic</div></div>
  <div class="github-ai-presenter-body-v4"><div class="github-ai-presenter-step-title-v4" id="githubAiPresenterStepTitleV4"></div><div class="github-ai-presenter-text-v4" id="githubAiPresenterTextV4"></div><div class="github-ai-presenter-controls-v4"><button type="button" class="github-ai-presenter-button-v4" onclick="githubAiPresenterStartV4()">開始導讀</button><button type="button" class="github-ai-presenter-button-v4" onclick="githubAiPresenterPrevV4()">上一段</button><button type="button" class="github-ai-presenter-button-v4" onclick="githubAiPresenterNextV4()">下一段</button><button type="button" class="github-ai-presenter-button-v4" onclick="githubAiPresenterStopV4()">結束</button></div><div class="github-ai-presenter-progress-v4" id="githubAiPresenterProgressV4"></div></div>
</section>
<script id="github-ai-presenter-script-v4">
window.__githubAiPresenterSectionsV4={sections_json};window.__githubAiPresenterIndexV4=0;window.__githubAiPresenterLastTargetV4=null;
function githubAiPresenterFindByTextV4(tags,texts){{for(var t=0;t<tags.length;t++){{var nodes=document.getElementsByTagName(tags[t]);for(var i=0;i<nodes.length;i++){{var tx=(nodes[i].textContent||'').trim();for(var j=0;j<texts.length;j++){{if(tx.indexOf(texts[j])>=0)return nodes[i];}}}}}}return null;}}
function githubAiPresenterFindTargetV4(kind){{if(kind==='top')return document.querySelector('.top-date-meta-bar')||githubAiPresenterFindByTextV4(['section','div'],['今日總經摘要']);if(kind==='visual')return githubAiPresenterFindByTextV4(['section','div','h1','h2'],['Visual Market Note','市場傳導圖解']);if(kind==='market')return githubAiPresenterFindByTextV4(['section','div','h1','h2'],['走勢圖','Market Snapshot']);if(kind==='news')return document.querySelector('.news-narrative-section')||githubAiPresenterFindByTextV4(['section','div','h1','h2'],['新聞敘事驗證']);if(kind==='bottom')return document.querySelector('.github-history-nav-v1')||document.querySelector('.footer')||document.body;return null;}}
function githubAiPresenterClearHighlightV4(){{var last=window.__githubAiPresenterLastTargetV4;if(last&&last.classList)last.classList.remove('github-ai-presenter-highlight-v4');window.__githubAiPresenterLastTargetV4=null;}}
function githubAiPresenterRenderV4(scroll){{var s=window.__githubAiPresenterSectionsV4||[];var idx=window.__githubAiPresenterIndexV4||0;if(!s.length)return;if(idx<0)idx=0;if(idx>=s.length)idx=s.length-1;window.__githubAiPresenterIndexV4=idx;var item=s[idx];var title=document.getElementById('githubAiPresenterStepTitleV4');var text=document.getElementById('githubAiPresenterTextV4');var progress=document.getElementById('githubAiPresenterProgressV4');if(title)title.textContent=(idx+1)+'. '+item.title;if(text)text.textContent=item.narration||item.text||'';if(progress)progress.textContent='第 '+(idx+1)+' / '+s.length+' 段';if(scroll){{githubAiPresenterClearHighlightV4();var target=githubAiPresenterFindTargetV4(item.target);if(target&&target.scrollIntoView){{target.scrollIntoView({{behavior:'smooth',block:'start'}});if(target.classList){{target.classList.add('github-ai-presenter-highlight-v4');window.__githubAiPresenterLastTargetV4=target;}}}}}}}}
function githubAiPresenterStartV4(){{window.__githubAiPresenterIndexV4=0;githubAiPresenterRenderV4(true);}}
function githubAiPresenterNextV4(){{var s=window.__githubAiPresenterSectionsV4||[];window.__githubAiPresenterIndexV4=Math.min((window.__githubAiPresenterIndexV4||0)+1,s.length-1);githubAiPresenterRenderV4(true);}}
function githubAiPresenterPrevV4(){{window.__githubAiPresenterIndexV4=Math.max((window.__githubAiPresenterIndexV4||0)-1,0);githubAiPresenterRenderV4(true);}}
function githubAiPresenterStopV4(){{githubAiPresenterClearHighlightV4();var p=document.getElementById('githubAiPresenterV4');if(p&&p.scrollIntoView)p.scrollIntoView({{behavior:'smooth',block:'start'}});}}
document.addEventListener('DOMContentLoaded',function(){{githubAiPresenterRenderV4(false);}});
</script>
<!-- GITHUB_AI_PRESENTER_END -->
'''
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
    sections = generate_presenter_sections(pricing_logic, today_payload)

    index_html = inject_history_nav(inject_ai_presenter(raw_html, sections), current_date, dates, False)
    history_html = inject_history_nav(inject_ai_presenter(raw_html, sections), current_date, dates, True)

    write_text(ROOT / "index.html", index_html)
    write_text(HISTORY_HTML_DIR / f"{current_date}.html", history_html)
    write_json(DATA_DIR / "latest.json", today_payload)
    write_json(HISTORY_DATA_DIR / f"{current_date}.json", today_payload)
    write_json(PRICING_DIR / "latest.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "mode": "macro_pricing_logic_v4", "logic": pricing_logic})
    write_json(PRICING_DIR / f"{current_date}.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "mode": "macro_pricing_logic_v4", "logic": pricing_logic})
    write_json(PRESENTER_DIR / "latest.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "mode": "macro_pricing_logic_presenter_v4", "sections": sections})
    write_json(PRESENTER_DIR / f"{current_date}.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "mode": "macro_pricing_logic_presenter_v4", "sections": sections})
    write_json(DATA_DIR / "latest_meta.json", {"generated_at": datetime.now(TW_TZ).isoformat(timespec="seconds"), "date": current_date, "history_dates": dates, "source": "Apps Script dashboard_html_source", "html_length": len(raw_html), "index_html_length": len(index_html), "ai_presenter": "macro_pricing_logic_v4", "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")})

    print("Saved Apps Script dashboard HTML as static GitHub Pages index.html")
    print(f"date = {current_date}")
    print(f"history_dates = {', '.join(dates)}")
    print(f"raw_html_length = {len(raw_html)}")
    print(f"index_html_length = {len(index_html)}")
    print("ai_presenter = macro_pricing_logic_v4")


if __name__ == "__main__":
    main()
