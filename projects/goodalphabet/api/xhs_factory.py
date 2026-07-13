from __future__ import annotations

import io
import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_NOTE_COUNT = 1
DEFAULT_WORDS_PER_NOTE = 5
DEFAULT_COMPANY_VOCAB_POOL = 3000
COMPANY_CARD_VOCAB_LIMIT = 5

COMPANY_ANGLES = [
    {"value": "company_overview", "label": "公司全景"},
    {"value": "product_intro", "label": "产品介绍"},
    {"value": "technology_product", "label": "科技产品"},
    {"value": "aviation_travel", "label": "航空出行"},
    {"value": "business_english", "label": "商务英语"},
    {"value": "company_history", "label": "公司历史"},
    {"value": "global_impact", "label": "全球影响"},
]

COMPANY_KEYWORDS = {
    "product": {"product", "brand", "device", "platform", "service", "feature", "design", "portfolio"},
    "technology": {"technology", "software", "hardware", "chip", "semiconductor", "ai", "cloud", "algorithm", "data", "compute"},
    "aviation": {"airline", "aircraft", "flight", "route", "fleet", "airport", "passenger", "travel"},
    "business": {"customer", "consumer", "market", "distribution", "global", "revenue", "operation", "supply", "chain"},
    "history": {"found", "founded", "launch", "legacy", "acquire", "expand", "origin"},
    "impact": {"influence", "ubiquitous", "daily", "leader", "worldwide", "connect"},
}

ANGLE_KEYWORDS = {
    "company_overview": COMPANY_KEYWORDS["business"] | COMPANY_KEYWORDS["history"] | COMPANY_KEYWORDS["impact"],
    "product_intro": COMPANY_KEYWORDS["product"],
    "technology_product": COMPANY_KEYWORDS["technology"] | COMPANY_KEYWORDS["product"],
    "aviation_travel": COMPANY_KEYWORDS["aviation"],
    "business_english": COMPANY_KEYWORDS["business"],
    "company_history": COMPANY_KEYWORDS["history"],
    "global_impact": COMPANY_KEYWORDS["impact"] | {"global", "worldwide"},
}

COMPANY_FALLBACK_TERMS = {
    "technology_product": {
        "innovative",
        "sophisticated",
        "robust",
        "dominant",
        "ubiquitous",
        "pioneer",
        "proliferate",
        "proficient",
        "ascendant",
        "transform",
        "transfigure",
        "hasten",
    },
    "product_intro": {"innovative", "sophisticated", "robust", "proficient", "pioneer"},
    "company_overview": {"dominant", "ubiquitous", "pioneer", "ascendant", "robust", "proliferate"},
    "business_english": {"dominant", "ascendant", "proficient", "robust", "ubiquitous"},
    "company_history": {"pioneer", "ascendant", "proliferate", "transfigure"},
    "global_impact": {"ubiquitous", "dominant", "ascendant", "proliferate", "pioneer"},
    "aviation_travel": {"aloft", "hasten", "robust", "proficient", "pioneer"},
}

GENERAL_COMPANY_FALLBACK_TERMS = {
    "innovative",
    "sophisticated",
    "robust",
    "dominant",
    "ubiquitous",
    "pioneer",
    "proliferate",
    "proficient",
    "ascendant",
}

HIGH_QUALITY_COMPANY_FALLBACK_TERMS = {
    "advocate",
    "bracing",
    "document",
    "elaborate",
    "elevate",
    "fecund",
    "fluent",
    "gripping",
    "maven",
    "perceptive",
    "propagate",
    "qualify",
    "spiral",
    "stasis",
    "transitional",
    "transitory",
    "unflagging",
}

LOW_QUALITY_COMPANY_FALLBACK_TERMS = {
    "abandon",
    "belligerent",
    "blameworthy",
    "cloying",
    "damn",
    "effrontery",
    "gloomy",
    "grumpy",
    "guzzle",
    "indigence",
    "lurid",
    "obese",
    "poseur",
    "prevaricate",
    "deference",
    "compassionate",
    "hale",
    "predispose",
    "ruffle",
    "rubicund",
    "shiftless",
    "surly",
    "vengeance",
    "wince",
}

KNOWN_COMPANY_PROFILES: dict[str, dict[str, Any]] = {}

SCENES = [
    {"value": "exam_anxiety", "label": "考试焦虑"},
    {"value": "workplace", "label": "职场表达"},
    {"value": "study_abroad", "label": "留学生活"},
    {"value": "relationship_chat", "label": "恋爱聊天"},
    {"value": "trending_memes", "label": "热点热梗"},
    {"value": "film_tv", "label": "影视台词"},
    {"value": "travel", "label": "旅行场景"},
    {"value": "japanese_watching", "label": "日剧/动漫"},
]

STYLES = [
    {"value": "resonance", "label": "共鸣感"},
    {"value": "comedy", "label": "搞笑反转"},
    {"value": "practical", "label": "实用干货"},
    {"value": "story", "label": "故事型"},
    {"value": "contrast", "label": "反差型"},
    {"value": "list", "label": "清单型"},
]

METRIC_FIELDS = {"views", "likes", "favorites", "comments", "profile_visits", "product_visits"}
IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1440
GENERATED_ROOT = Path(os.environ.get("XHS_GENERATED_DIR") or ("/tmp/generated" if os.environ.get("VERCEL") else "static/generated"))
LOGO_CACHE_DIR = GENERATED_ROOT / "xhs" / "logo-cache"
IMAGE_CACHE_DIR = GENERATED_ROOT / "xhs" / "image-cache"

BRAND_STYLES: dict[str, dict[str, str]] = {}

BOEING_IMAGE_ASSET: dict[str, str] = {}

KNOWN_COMPANY_IMAGE_ASSETS: dict[str, list[dict[str, str]]] = {}


def get_options(db: Any) -> dict[str, Any]:
    wordbooks = db.execute(
        """
        SELECT wb.id, wb.name, wb.language, COUNT(w.id) AS word_count
        FROM wordbooks wb
        LEFT JOIN words w ON w.book_id=wb.id
        GROUP BY wb.id, wb.name, wb.language
        ORDER BY
            CASE WHEN wb.language='en' THEN 0 ELSE 1 END,
            CASE WHEN COUNT(w.id) > 0 THEN 0 ELSE 1 END,
            CASE WHEN wb.name LIKE ? THEN 0 ELSE 1 END,
            wb.id
        """
        ,
        ("%3000%",),
    ).fetchall()
    return {
        "wordbooks": wordbooks,
        "scenes": SCENES,
        "styles": STYLES,
        "company_angles": COMPANY_ANGLES,
        "defaults": {
            "note_count": DEFAULT_NOTE_COUNT,
            "words_per_note": DEFAULT_WORDS_PER_NOTE,
        },
    }


def sample_words(db: Any, wordbook_id: int, count: int, offset: int = 0) -> list[dict[str, Any]]:
    safe_count = max(1, min(int(count), 5000))
    safe_offset = max(0, int(offset))
    rows = db.execute(
        """
        SELECT id, word, phonetic, definition, seq
        FROM words
        WHERE book_id=?
        ORDER BY seq
        LIMIT ? OFFSET ?
        """,
        (wordbook_id, safe_count, safe_offset),
    ).fetchall()
    if not rows:
        raise ValueError("No words available for the selected wordbook.")
    return [dict(row) for row in rows]


def build_generation_prompt(
    *,
    scene: str,
    topic: str,
    style: str,
    note_count: int,
    words_per_note: int,
    language: str,
    words: list[dict[str, Any]],
) -> str:
    word_lines = "\n".join(f"- {item['word']}: {item['definition']}" for item in words)
    return f"""You are writing Xiaohongshu draft notes for an AI vocabulary learning product.

Generate {note_count} notes. Each note should naturally include about {words_per_note} vocabulary items.

Context:
- Product: AI vocabulary learning product that turns word lists into memorable stories, short texts, dialogues, and review material.
- Language track: {language}
- Scene: {scene}
- Topic or trend: {topic}
- Style: {style}

Vocabulary pool:
{word_lines}

Rules:
- Return valid JSON only.
- The top-level object must contain a "notes" array.
- Every note needs a human scene, emotion, problem, or story hook.
- Do not write a hard-sell ad.
- Do not promise guaranteed score improvement, official endorsement, or impossible timelines.
- Avoid repeated openings in the same batch.
- Vocabulary must appear naturally in the body, not only in a pasted list.

JSON shape for each note:
{{
  "titles": ["title 1", "title 2", "title 3"],
  "body": "main Xiaohongshu note body",
  "vocabulary": [{{"word": "word", "definition": "definition", "usage": "usage or memory hook"}}],
  "cover_text": "short cover text",
  "image_prompt": "image prompt",
  "hashtags": ["#tag"],
  "cta": "light product mention",
  "quality_notes": ["self-check note"],
  "risk_flags": ["risk flag, or empty array"]
}}"""


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _clean_string(value)
        key = text.lower()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def _image_assets_for_profile(company_name: str, ticker: str = "", aliases: list[str] | None = None) -> list[dict[str, str]]:
    keys = [company_name, ticker, *(aliases or [])]
    assets: list[dict[str, str]] = []
    seen: set[str] = set()
    external_assets = _external_company_catalog().get("image_assets", {})
    external_aliases = _external_company_catalog().get("aliases", {})
    for key in keys:
        normalized = _clean_string(key).lower()
        canonical = _clean_string(external_aliases.get(normalized)).lower() if isinstance(external_aliases, dict) else ""
        candidates = list(KNOWN_COMPANY_IMAGE_ASSETS.get(normalized, []))
        if isinstance(external_assets, dict):
            external_value = external_assets.get(canonical or normalized, [])
            if isinstance(external_value, list):
                candidates.extend(asset for asset in external_value if isinstance(asset, dict))
        for asset in candidates:
            url = _clean_string(asset.get("url"))
            if url and url not in seen:
                assets.append(
                    {
                        "url": url,
                        "caption": _clean_string(asset.get("caption")),
                        "source": _clean_string(asset.get("source")),
                    }
                )
                seen.add(url)
    return assets


def _unique_image_assets(values: list[Any]) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        url = _clean_string(value.get("url"))
        if not url or url in seen:
            continue
        assets.append(
            {
                "url": url,
                "caption": _clean_string(value.get("caption")),
                "source": _clean_string(value.get("source")),
            }
        )
        seen.add(url)
    return assets


def normalize_company_profile(
    *,
    company_name: str,
    manual_company_profile: str = "",
    ticker: str = "",
    source_language: str = "zh",
    logo_url: str = "",
    provider_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clean_name = _clean_string(company_name)
    if not clean_name:
        raise ValueError("Company name is required.")
    payloads = provider_payloads or []
    summaries = [_clean_string(manual_company_profile)]
    summaries.extend(_clean_string(payload.get("summary")) for payload in payloads)
    summary_text = "\n".join(item for item in summaries if item)
    if not summary_text:
        raise ValueError("No company profile source was available. Enter a manual profile or provide a ticker.")

    industries = _unique_strings([industry for payload in payloads for industry in payload.get("industries", [])])
    aliases = _unique_strings([ticker, *(alias for payload in payloads for alias in payload.get("aliases", []))])
    source_urls = _unique_strings([url for payload in payloads for url in payload.get("source_urls", [])])
    warnings = _unique_strings([warning for payload in payloads for warning in payload.get("warnings", [])])
    image_assets = _unique_image_assets(
        [asset for payload in payloads for asset in payload.get("image_assets", [])]
        + _image_assets_for_profile(clean_name, ticker=ticker, aliases=aliases)
    )
    if manual_company_profile:
        warnings.append("Manual company profile should be fact-checked before publishing.")
    return {
        "company_name": clean_name,
        "aliases": aliases,
        "source_summary": summary_text,
        "logo_url": _clean_string(logo_url or next((payload.get("logo_url") for payload in payloads if payload.get("logo_url")), "")),
        "image_assets": image_assets,
        "industries": industries,
        "products": _unique_strings([product for payload in payloads for product in payload.get("products", [])]),
        "brands": _unique_strings([brand for payload in payloads for brand in payload.get("brands", [])]),
        "milestones": _unique_strings([milestone for payload in payloads for milestone in payload.get("milestones", [])]),
        "headquarters": _clean_string(next((payload.get("headquarters") for payload in payloads if payload.get("headquarters")), "")),
        "source_language": source_language,
        "source_urls": source_urls,
        "source_warnings": _unique_strings(warnings),
    }


def _profile_text(profile: dict[str, Any]) -> str:
    parts = [_clean_string(profile.get("company_name")), _clean_string(profile.get("source_summary"))]
    for key in ("aliases", "industries", "products", "brands", "milestones"):
        value = profile.get(key)
        if isinstance(value, list):
            parts.extend(_clean_string(item) for item in value)
    return " ".join(part for part in parts if part).lower()


def _profile_context_terms(profile_text: str) -> set[str]:
    groups = [
        (
            ("半导体", "芯片", "gpu", "数据中心", "人工智能", "ai", "软件", "平台", "compute", "computing", "semiconductor"),
            {
                "advanced",
                "complex",
                "compute",
                "computing",
                "data",
                "elaborate",
                "elevate",
                "improve",
                "platform",
                "propagate",
                "robust",
                "semiconductor",
                "software",
                "spread",
                "support",
            },
        ),
        (
            ("消费品", "日化", "家庭", "护理", "洗衣", "消费者", "品牌", "consumer", "home care", "household"),
            {
                "brand",
                "category",
                "consumer",
                "customer",
                "home",
                "household",
                "insight",
                "market",
                "maven",
                "perceptive",
                "product",
                "ubiquitous",
            },
        ),
        (
            ("航空", "飞机", "航天", "商用飞机", "飞行", "机场", "安全", "aircraft", "aviation", "flight"),
            {
                "air",
                "aircraft",
                "airplane",
                "aloft",
                "aviation",
                "flight",
                "safety",
                "travel",
            },
        ),
        (
            ("白酒", "茅台", "酱香", "礼赠", "宴请", "稀缺", "moutai", "baijiu"),
            {
                "brand",
                "craft",
                "distribution",
                "premium",
                "resilience",
                "scarcity",
                "strategic",
            },
        ),
    ]
    terms: set[str] = set()
    for triggers, mapped_terms in groups:
        if any(_contains_keyword(profile_text, trigger) for trigger in triggers):
            terms.update(mapped_terms)
    return terms


def _contains_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    if re.search(r"[a-z0-9]", keyword):
        return re.search(rf"\b{re.escape(keyword)}(?:s|es)?\b", text) is not None
    return keyword in text


def _company_fallback_score(item: dict[str, Any], angle: str) -> int:
    word = _clean_string(item.get("word") or item.get("hanzi")).lower()
    if not re.fullmatch(r"[a-z][a-z-]*", word):
        return 0
    definition = _clean_string(item.get("definition") or item.get("meaning") or item.get("meaning_en")).lower()
    angle_fallbacks = COMPANY_FALLBACK_TERMS.get(angle, set())
    score = 0
    if word in angle_fallbacks:
        score += 10
    if word in GENERAL_COMPANY_FALLBACK_TERMS:
        score += 6
    is_high_quality = word in HIGH_QUALITY_COMPANY_FALLBACK_TERMS
    if is_high_quality:
        score += 8
    if word in LOW_QUALITY_COMPANY_FALLBACK_TERMS:
        score -= 8
    useful_definition_terms = (
        "innovation",
        "advanced",
        "complex",
        "strength",
        "dominant",
        "influence",
        "everywhere",
        "leader",
        "multiply",
        "rapidly",
        "competence",
        "创新",
        "先进",
        "复杂",
        "强",
        "影响",
        "支配",
        "领先",
        "普遍",
        "增长",
        "熟练",
    )
    if not is_high_quality and any(term in definition for term in useful_definition_terms):
        score += 3
    return score


def match_company_vocabulary(
    profile: dict[str, Any],
    words: list[dict[str, Any]],
    *,
    limit: int = 15,
    angle: str = "company_overview",
) -> list[dict[str, Any]]:
    text = _profile_text(profile)
    profile_terms = _profile_context_terms(text)
    angle_terms = ANGLE_KEYWORDS.get(angle, set())
    ranked: list[dict[str, Any]] = []
    for item in words:
        word = _clean_string(item.get("word") or item.get("hanzi"))
        definition = _clean_string(item.get("definition") or item.get("meaning") or item.get("meaning_en"))
        if not word:
            continue
        word_lower = word.lower()
        is_english_word = re.fullmatch(r"[a-z][a-z-]*", word_lower) is not None
        definition_lower = definition.lower()
        score = 0
        reasons: list[str] = []
        if _contains_keyword(text, word_lower):
            score += 5
            reasons.append("word appears in profile")
        if is_english_word and profile_terms:
            if word_lower in profile_terms or any(_contains_keyword(definition_lower, term) for term in profile_terms):
                score += 18
                reasons.append("matches company context")
        fallback_score = _company_fallback_score(item, angle)
        if fallback_score > 0:
            score += fallback_score
            reasons.append("usable in company profile")
        if is_english_word:
            for bucket, keywords in COMPANY_KEYWORDS.items():
                if word_lower in keywords or any(_contains_keyword(definition_lower, keyword) for keyword in keywords):
                    score += 2
                    reasons.append(f"matches {bucket}")
            if word_lower in angle_terms or any(_contains_keyword(definition_lower, keyword) for keyword in angle_terms):
                score += 2
                reasons.append("matches angle")
        if score <= 0:
            continue
        ranked.append({
            "id": item.get("id"),
            "word": word,
            "hanzi": word,
            "pinyin": item.get("pinyin") or "",
            "meaning": definition,
            "phonetic": item.get("phonetic") or "",
            "definition": definition,
            "seq": item.get("seq"),
            "score": score,
            "match_reasons": _unique_strings(reasons),
            "company_context": f"用中文介绍 {profile.get('company_name', '该公司')} 时，可写成中文表达（{word}）。",
        })
    ranked.sort(key=lambda item: (-int(item["score"]), int(item.get("seq") or 999999), item["word"]))
    if len(ranked) < limit and any(_clean_string(item.get("word") or item.get("hanzi")) for item in words):
        seen = {item["word"].lower() for item in ranked}
        fallback_candidates = [
            {
                "id": item.get("id"),
                "word": _clean_string(item.get("word") or item.get("hanzi")),
                "hanzi": _clean_string(item.get("word") or item.get("hanzi")),
                "pinyin": item.get("pinyin") or "",
                "meaning": _clean_string(item.get("definition") or item.get("meaning") or item.get("meaning_en")),
                "definition": _clean_string(item.get("definition") or item.get("meaning") or item.get("meaning_en")),
                "phonetic": item.get("phonetic") or "",
                "seq": item.get("seq"),
                "_order": index,
                "score": _company_fallback_score(item, angle),
                "match_reasons": ["fallback company vocabulary"],
                "company_context": f"用中文介绍 {profile.get('company_name', '该公司')} 时，可写成中文表达（{_clean_string(item.get('word') or item.get('hanzi'))}）。",
            }
            for index, item in enumerate(words)
            if _clean_string(item.get("word") or item.get("hanzi"))
            and _clean_string(item.get("word") or item.get("hanzi")).lower() not in seen
        ]
        fallback_candidates.sort(
            key=lambda item: (-int(item.get("score") or 0), int(item.get("seq") or 999999), int(item.get("_order") or 0), item["word"])
        )
        if any(int(item.get("score") or 0) >= 0 for item in fallback_candidates):
            fallback_candidates = [item for item in fallback_candidates if int(item.get("score") or 0) >= 0]
        for item in fallback_candidates:
            item.pop("_order", None)
        return (ranked + fallback_candidates)[: max(1, int(limit))]
    return ranked[: max(1, int(limit))]


def _company_narrative_guidance(style: str, angle: str) -> str:
    style_guidance = {
        "story": "Use a connected story arc: origin or user scene -> technology/product shift -> current influence.",
        "practical": "Use a practical explainer arc: what it is -> what it makes possible -> where readers see it.",
        "list": "Use a connected list with logical transitions; each point must build on the previous one.",
        "contrast": "Use a before/after contrast, but keep the facts objective and avoid hype.",
        "resonance": "Use a relatable opening scene, then connect it to concrete company facts.",
        "comedy": "Use light contrast or surprise only in the opening; keep the company facts serious.",
    }.get(style, "Use a connected story arc: origin or user scene -> product capability -> current influence.")
    angle_guidance = {
        "technology_product": "Focus the fact chain on technology, platform, developer ecosystem, and real use cases.",
        "product_intro": "Focus the fact chain on product category, function, users, and practical impact.",
        "aviation_travel": "Focus the fact chain on aircraft/service/network, safety context, and travel experience.",
        "business_english": "Focus the fact chain on market, customers, operations, and business model.",
        "company_history": "Focus the fact chain on founding, turning points, product milestones, and expansion.",
        "global_impact": "Focus the fact chain on adoption, industry influence, and worldwide footprint.",
        "company_overview": "Focus the fact chain on what the company does, why it matters, and how it evolved.",
    }.get(angle, "Focus the fact chain on concrete company facts and their real-world impact.")
    return f"{style_guidance}\n{angle_guidance}"


def build_company_generation_prompt(
    *,
    profile: dict[str, Any],
    style: str,
    angle: str,
    note_count: int,
    words_per_note: int,
    language: str,
    words: list[dict[str, Any]],
) -> str:
    word_lines = "\n".join(
        f"- {item['word']}: {item.get('definition', '')}; context: {item.get('company_context', '')}"
        for item in words
    )
    industry_info = ", ".join(profile.get("industries", []) or [])
    requested_word_count = max(1, int(words_per_note))
    card_word_count = min(requested_word_count, COMPANY_CARD_VOCAB_LIMIT)
    natural_word_floor = max(3, min(card_word_count, COMPANY_CARD_VOCAB_LIMIT))
    narrative_guidance = _company_narrative_guidance(style, angle)
    return f"""You are writing GOODALPHABET Xiaohongshu image-text notes.
中文小红书图文笔记：核心是“读公司/产品学英文词”，用真实公司内容串联英文词汇，并轻量宣传 GOODALPHABET 的学习方法。
目标是高质量但克制的图文：封面承载一段中文公司/产品介绍和底部真实图片，后面只做词汇复盘和结尾页。

Generate {note_count} notes. Each note should naturally include target English vocabulary items from the matched vocabulary pool.

Context:
- GOODALPHABET is the light brand frame: it helps readers learn English words through company/product stories.
- GOODALPHABET must not be the subject of the note.
- The subject must still be {profile.get('company_name')} and the embedded English vocabulary. Do not turn the body into a pure GOODALPHABET advertisement.
- Language track: {language}
- Content mode: company_or_product_profile
- Company/product to introduce: {profile.get('company_name')}
- Logo URL: {profile.get('logo_url') or 'not provided'}
- Industry info: {industry_info or 'not provided'}
- Style: {style}
- Angle: {angle}
- Requested vocabulary count: {requested_word_count}
- Practical card vocabulary count: {card_word_count}. A Xiaohongshu cover should teach a few words well, not cram too many terms.
- Natural vocabulary floor: {natural_word_floor}

Company/product facts:
{profile.get('source_summary')}

Matched vocabulary pool:
{word_lines}

Narrative guidance:
{narrative_guidance}
- Build a clear fact chain instead of listing disconnected facts.
- Each vocabulary item should help explain one link in that fact chain.
- Treat vocabulary as inline annotations inside a company story, not as teaching points. The reader should first feel they are reading a company/product profile.
- Prefer concrete nouns and business/technology words that match the company facts. Skip personality, mood, conflict, or unrelated GRE words even if they are in the pool.
- Use transitions so the paragraph flows: origin/product -> capability -> customer/use case -> industry impact or limitation.
- Manual publishing only: this tool drafts notes for human review and copy-paste publishing.
- Do not include claims that the note was automatically posted, scheduled, or published by the system.

Rules:
- Return valid JSON only.
- The top-level object must contain a "notes" array.
- Write about {profile.get('company_name')} as the story carrier, and make the learning hook explicit: 读公司/产品故事学英文词.
- The title should use a hook like "读 {profile.get('company_name')} 学 6 个英文词" or "从 {profile.get('company_name')} 看懂这些商业/科技词".
- The cover should be readable by itself: one Chinese introduction paragraph with several inline Chinese（English） vocabulary annotations, plus a real product/company/industry image underneath.
- You may mention GOODALPHABET once in the CTA or quality_notes as the tool/brand that turns company stories into vocabulary cards.
- Write one coherent, vivid Chinese company/product introduction paragraph, or two short connected paragraphs.
- Body length should usually be 280-520 Chinese characters for company/product mode, unless the company facts are very sparse.
- The main body must be Chinese Xiaohongshu-style writing, but objective and source-grounded.
- Use Chinese-first parenthetical vocabulary format in the body: 中文表达（English term）, for example 基础设施（infrastructure） or 算力（computing power）.
- Use the most natural subset of the matched vocabulary. Aim for {card_word_count} words in the note even if the user requested more; never force awkward words. Use at least {natural_word_floor} different vocabulary items in each body and list those same items in "vocabulary".
- Integrate every used vocabulary item inside the narrative sentence where it helps explain the company, product, history, technology, market, impact, or risk.
- Every parenthetical English term must be attached to a Chinese phrase that would still make sense if the English were removed.
- Do not use a vocabulary item merely as a final comment, slogan, or isolated adjective. Bad: "这家公司很强（formidable）". Better: "它建立了难以复制的供应链壁垒（barrier）".
- Do not append a vocabulary list after the body. The "body" field must not end with standalone lines like "提升（elevate）".
- Do not invent vocabulary outside the matched vocabulary pool unless the word is a product/company proper noun.
- Do not put bare English words in the sentence unless they are product names or official company names.
- Mention 3 to 5 concrete facts from the provided profile.
- Keep vocabulary annotation short and secondary.
- Avoid investment advice, stock recommendations, or unsupported factual claims.
- The image_prompt should describe one concrete real-world visual: product, company scene, headquarters, factory, shelf, aircraft, data center, or industry imagery. Do not describe abstract gradients.
- Do not plan separate article, timeline, or business-logic visualization pages. The business context belongs in the cover paragraph.
- If adding image_cards, include only simple pages such as cover, vocabulary, CTA.

Return this top-level JSON shape:
{{
  "notes": [
{{
  "titles": ["title 1", "title 2", "title 3"],
  "body": "一段中文客观公司介绍，包含中文（English）格式的词汇",
  "vocabulary": [{{"word": "infrastructure", "definition": "基础设施", "usage": "基础设施（infrastructure）"}}],
  "cover_text": "中文封面介绍段落，包含几个中文（English）词汇",
  "visual_header": {{"logo_url": "logo URL or empty string", "industry_info": "industry, market, or product category", "company_meta": ["founded year", "headquarters", "ticker"]}},
  "image_prompt": "concrete visual prompt, e.g. product shelf, GPU server rack, aircraft cabin, baijiu bottle and origin landscape",
  "image_cards": [{{"kind": "cover", "visual": "specific real product/company scene"}}, {{"kind": "vocabulary", "visual": "words from the cover paragraph"}}, {{"kind": "cta", "visual": "GOODALPHABET closing card"}}],
  "hashtags": ["#tag"],
  "cta": "用 GOODALPHABET 把公司故事变成单词记忆",
  "quality_notes": ["self-check note"],
  "risk_flags": ["risk flag, or empty array"],
  "company_facts_used": ["fact used in this note"],
  "fact_check_notes": ["fact check note"],
  "word_context_map": [{{"word": "word", "company_context": "中文表达（word）"}}]
}}
  ]
}}"""


def build_company_retry_prompt(*, original_prompt: str, validation_error: str, rejected_response: str) -> str:
    rejected_excerpt = _clean_string(rejected_response)[:4000]
    return f"""Rewrite the rejected company/product Xiaohongshu note.

The previous response failed validation:
{validation_error}

Rejected response excerpt:
{rejected_excerpt}

Use the original task and JSON contract below, but fix the failure completely.
Important:
- The subject must be the requested company/product, not GOODALPHABET.
- The body must be a coherent Chinese company/product introduction.
- The body must naturally embed vocabulary as 中文（English）.
- Do not append a pasted vocabulary list after the body.
- Return valid JSON only.

Original task:
{original_prompt}
"""


def build_company_intro_prompt(
    *,
    company_profile: dict[str, Any],
    vocabulary: list[dict[str, Any]],
    note_count: int,
) -> str:
    profile = normalize_company_profile(
        company_name=company_profile.get("company") or company_profile.get("company_name") or "",
        manual_company_profile=company_profile.get("summary") or company_profile.get("source_summary") or "",
    )
    words = [
        {
            "word": item.get("word") or item.get("hanzi") or "",
            "definition": item.get("definition") or item.get("meaning") or "",
            "company_context": item.get("company_context") or "",
        }
        for item in vocabulary
    ]
    prompt = build_company_generation_prompt(
        profile=profile,
        style="profile",
        angle="company_overview",
        note_count=note_count,
        words_per_note=6,
        language="en",
        words=words,
    )
    return prompt + "\nCompatibility note: 中文小红书图文笔记；公司资料摘要；自然引出中文词汇；operation_plan；image_cards；不要编造未经来源支持的公司事实。"


def _copy_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


_EXTERNAL_COMPANY_CATALOG: dict[str, Any] | None = None


def _external_company_catalog() -> dict[str, Any]:
    global _EXTERNAL_COMPANY_CATALOG
    if _EXTERNAL_COMPANY_CATALOG is not None:
        return _EXTERNAL_COMPANY_CATALOG
    path = Path(__file__).resolve().parents[1] / "data" / "xhs_company_profiles.json"
    if not path.exists():
        _EXTERNAL_COMPANY_CATALOG = {"profiles": {}, "aliases": {}, "brand_styles": {}, "image_assets": {}}
        return _EXTERNAL_COMPANY_CATALOG
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    _EXTERNAL_COMPANY_CATALOG = {
        "profiles": payload.get("profiles") if isinstance(payload.get("profiles"), dict) else {},
        "aliases": payload.get("aliases") if isinstance(payload.get("aliases"), dict) else {},
        "brand_styles": payload.get("brand_styles") if isinstance(payload.get("brand_styles"), dict) else {},
        "image_assets": payload.get("image_assets") if isinstance(payload.get("image_assets"), dict) else {},
    }
    return _EXTERNAL_COMPANY_CATALOG


def _external_company_profile(key: str) -> dict[str, Any] | None:
    normalized = _clean_string(key).lower()
    if not normalized:
        return None
    catalog = _external_company_catalog()
    aliases = catalog.get("aliases", {})
    canonical = _clean_string(aliases.get(normalized)).lower() if isinstance(aliases, dict) else ""
    profiles = catalog.get("profiles", {})
    if isinstance(profiles, dict):
        payload = profiles.get(canonical or normalized)
        if isinstance(payload, dict):
            return _copy_profile_payload(payload)
    return None


def _known_company_profile(company: str, ticker: str = "") -> dict[str, Any] | None:
    keys = [_clean_string(company).lower(), _clean_string(ticker).lower()]
    for key in keys:
        if key and key in KNOWN_COMPANY_PROFILES:
            return _copy_profile_payload(KNOWN_COMPANY_PROFILES[key])
        if key:
            external_profile = _external_company_profile(key)
            if external_profile:
                return external_profile
    return None


def _wikipedia_company_profile(company: str) -> dict[str, Any] | None:
    clean_company = _clean_string(company)
    if not clean_company:
        return None
    title = urllib.parse.quote(clean_company.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    request = urllib.request.Request(url, headers={"User-Agent": "GOODALPHABET-XHS/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None
    summary = _clean_string(payload.get("extract"))
    if not summary:
        return None
    page_url = ""
    content_urls = payload.get("content_urls")
    if isinstance(content_urls, dict):
        desktop = content_urls.get("desktop")
        if isinstance(desktop, dict):
            page_url = _clean_string(desktop.get("page"))
    return {
        "company": clean_company,
        "summary": summary,
        "aliases": [payload.get("title") or clean_company],
        "industries": [],
        "products": [],
        "milestones": [],
        "source_urls": [page_url] if page_url else [url],
        "warnings": ["Wikipedia summary should be checked against company sources before publishing."],
        "search_provider": "wikipedia",
    }


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    cleaned = _clean_string(text)
    if not cleaned:
        return None
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            payload, _end = decoder.raw_decode(cleaned[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _codex_company_profile(company: str, ticker: str = "") -> dict[str, Any] | None:
    enabled = os.environ.get("XHS_CODEX_PROFILE_ENABLED", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return None
    clean_company = _clean_string(company)
    if not clean_company:
        return None
    timeout = max(5, min(int(os.environ.get("XHS_CODEX_PROFILE_TIMEOUT", "30")), 90))
    model = _clean_string(os.environ.get("XHS_CODEX_PROFILE_MODEL", ""))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as output_file:
        output_path = output_file.name
    prompt = (
        "Return ONLY compact JSON for a company/product profile. "
        "Use broadly known public facts; do not include investment advice. "
        "Fields: company, summary, industries array, products array, milestones array, "
        "headquarters, logo_url if known else empty string, source_urls array, warnings array. "
        f"Company/product: {clean_company}. Ticker/code: {ticker or 'not provided'}."
    )
    command = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--output-last-message",
        output_path,
    ]
    if model:
        command.extend(["-m", model])
    command.append(prompt)
    try:
        subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output_text = Path(output_path).read_text(encoding="utf-8")
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    finally:
        try:
            Path(output_path).unlink(missing_ok=True)
        except OSError:
            pass
    payload = _json_object_from_text(output_text)
    if not payload:
        return None
    summary = _clean_string(payload.get("summary"))
    if not summary:
        return None
    return {
        "company": _clean_string(payload.get("company") or clean_company),
        "summary": summary,
        "aliases": _as_string_list(payload.get("aliases")) + ([ticker] if ticker else []),
        "industries": _as_string_list(payload.get("industries")),
        "products": _as_string_list(payload.get("products")),
        "milestones": _as_string_list(payload.get("milestones")),
        "headquarters": _clean_string(payload.get("headquarters")),
        "logo_url": _clean_string(payload.get("logo_url")),
        "source_urls": _as_string_list(payload.get("source_urls")),
        "warnings": _as_string_list(payload.get("warnings")) + ["Codex CLI profile should be fact-checked before publishing."],
        "search_provider": "codex_exec",
    }


def search_company_profile(company: str, ticker: str = "") -> dict[str, Any]:
    clean_company = _clean_string(company)
    known_profile = _known_company_profile(clean_company, ticker)
    if known_profile:
        return known_profile
    codex_profile = _codex_company_profile(clean_company, ticker)
    if codex_profile:
        return codex_profile
    wiki_profile = _wikipedia_company_profile(clean_company)
    if wiki_profile:
        return wiki_profile
    return {
        "company": clean_company,
        "summary": f"{clean_company} 的公司资料需要由运营人员补充或核对。",
        "keywords": [clean_company, "公司", "产品", "品牌", "历史", "影响"],
        "sources": [],
        "search_provider": "fallback",
    }


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_note_payload(note: dict[str, Any]) -> dict[str, Any]:
    titles = _as_string_list(note.get("titles"))
    body = str(note.get("body") or "").strip()
    if not titles:
        raise ValueError("Each note must include at least one title.")
    if not body:
        raise ValueError("Each note must include a body.")
    return {
        "titles": titles,
        "selected_title": titles[0],
        "body": body,
        "vocabulary": note.get("vocabulary") if isinstance(note.get("vocabulary"), list) else [],
        "cover_text": str(note.get("cover_text") or "").strip(),
        "image_prompt": str(note.get("image_prompt") or "").strip(),
        "hashtags": _as_string_list(note.get("hashtags")),
        "cta": str(note.get("cta") or "").strip(),
        "quality_notes": _as_string_list(note.get("quality_notes")),
        "risk_flags": _as_string_list(note.get("risk_flags")),
        "visual_header": note.get("visual_header") if isinstance(note.get("visual_header"), dict) else {},
        "company_facts_used": _as_string_list(note.get("company_facts_used")),
        "fact_check_notes": _as_string_list(note.get("fact_check_notes")),
        "word_context_map": note.get("word_context_map") if isinstance(note.get("word_context_map"), list) else [],
    }


def _contains_parenthetical_english(text: str) -> bool:
    return re.search(r"[（(][A-Za-z][A-Za-z0-9 /+_.-]{1,60}[）)]", text) is not None


def _embedded_parenthetical_terms(text: str) -> set[str]:
    return {
        match.group(1).strip().lower()
        for match in re.finditer(r"[（(]([A-Za-z][A-Za-z0-9 /+_.-]{1,60})[）)]", text)
        if match.group(1).strip()
    }


def _looks_like_vocabulary_list_tail(body: str) -> bool:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    tail = lines[-3:]
    vocab_like = 0
    for line in tail:
        if len(line) <= 40 and re.fullmatch(r"[\u4e00-\u9fffA-Za-z，,；;、/ -]*[（(][A-Za-z][A-Za-z0-9 /+_.-]{1,60}[）)]", line):
            vocab_like += 1
    return vocab_like >= 1 and len(lines[-1]) <= 40


def validate_company_notes(
    notes: list[dict[str, Any]],
    *,
    company_name: str,
    min_vocabulary_count: int = 1,
    min_body_chars: int = 0,
) -> None:
    clean_company = _clean_string(company_name)
    if not clean_company:
        raise ValueError("Company name is required for company note validation.")
    company_lower = clean_company.lower()
    for index, note in enumerate(notes, start=1):
        title_text = " ".join(_as_string_list(note.get("titles")) + [_clean_string(note.get("selected_title"))])
        body = _clean_string(note.get("body"))
        combined = f"{title_text}\n{body}"
        combined_lower = combined.lower()
        body_lower = body.lower()
        if "goodalphabet" in combined_lower and company_lower not in combined_lower:
            raise ValueError(f"Company note {index} is about GOODALPHABET instead of {clean_company}.")
        if company_lower not in body_lower:
            raise ValueError(f"Company note {index} must mention {clean_company} in the body.")
        if min_body_chars > 0 and len(body) < min_body_chars:
            raise ValueError(f"Company note {index} is too short for a complete company introduction.")
        if not _contains_parenthetical_english(body):
            raise ValueError(f"Company note {index} must include Chinese-first parenthetical English vocabulary.")
        embedded_terms = _embedded_parenthetical_terms(body)
        required_terms = max(1, int(min_vocabulary_count))
        if len(embedded_terms) < required_terms:
            raise ValueError(
                f"Company note {index} must embed at least {required_terms} English vocabulary items in the body."
            )
        if _looks_like_vocabulary_list_tail(body):
            raise ValueError(f"Company note {index} appears to end with a pasted vocabulary list.")


def _load_ai_json(raw: str) -> Any:
    cleaned = raw.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    decoder = json.JSONDecoder()
    try:
        return decoder.decode(cleaned)
    except json.JSONDecodeError:
        pass

    for match in re.finditer(r"\{", cleaned):
        candidate = cleaned[match.start():]
        try:
            payload, _end = decoder.raw_decode(candidate)
            return payload
        except json.JSONDecodeError:
            continue

    raise ValueError("AI response must be valid JSON.")


def parse_generation_response(raw: str, requested_count: int) -> dict[str, Any]:
    payload = _load_ai_json(raw)

    notes = payload.get("notes") if isinstance(payload, dict) else None
    if not isinstance(notes, list):
        raise ValueError('AI response must contain a "notes" array.')

    normalized = [normalize_note_payload(note) for note in notes if isinstance(note, dict)]
    warning = None
    if len(normalized) != requested_count:
        warning = f"Generated {len(normalized)} notes, requested {requested_count}."
    return {"notes": normalized, "warning": warning}


def parse_company_generation_response(raw: str, requested_count: int) -> dict[str, Any]:
    payload = _load_ai_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("AI response must be a JSON object.")
    notes = payload.get("notes")
    if isinstance(notes, dict):
        notes = [notes]
    if not isinstance(notes, list) and ("titles" in payload or "body" in payload):
        notes = [payload]
    if not isinstance(notes, list):
        for key in ("note", "article", "draft", "result", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                notes = value
                break
            if isinstance(value, dict):
                notes = [value]
                break
    if not isinstance(notes, list):
        body = (
            payload.get("body")
            or payload.get("content")
            or payload.get("text")
            or payload.get("article_text")
            or payload.get("正文")
        )
        title = (
            payload.get("title")
            or payload.get("selected_title")
            or payload.get("cover_text")
            or payload.get("标题")
            or "公司资料卡"
        )
        if isinstance(body, str) and body.strip():
            notes = [
                {
                    **payload,
                    "titles": payload.get("titles") if isinstance(payload.get("titles"), list) else [str(title)],
                    "body": body,
                }
            ]
    if not isinstance(notes, list):
        raise ValueError('AI response must contain a "notes" array.')
    operation_plan = payload.get("operation_plan")
    if not isinstance(operation_plan, dict):
        operation_plan = {
            "positioning": "客观公司/产品介绍图文",
            "weekly_calendar": [],
            "content_series": [],
            "title_formulas": [],
            "review_checklist": [],
        }
    normalized_notes = [normalize_note_payload(note) for note in notes if isinstance(note, dict)]
    for note, source in zip(normalized_notes, [item for item in notes if isinstance(item, dict)]):
        note["image_cards"] = source.get("image_cards") if isinstance(source.get("image_cards"), list) else []
        note["vocabulary"] = [
            {
                **item,
                "word": item.get("word") or item.get("hanzi") or "",
                "definition": item.get("definition") or item.get("meaning") or "",
            }
            for item in note.get("vocabulary", [])
            if isinstance(item, dict)
        ]
        note["vocabulary"] = _vocabulary_used_in_body(note["vocabulary"], _short_text(note.get("body")))
    warning = None
    if len(normalized_notes) != requested_count:
        warning = f"Generated {len(normalized_notes)} notes, requested {requested_count}."
    return {
        "company": str(payload.get("company") or "").strip(),
        "company_profile": payload.get("company_profile") if isinstance(payload.get("company_profile"), dict) else {},
        "matched_vocabulary": payload.get("matched_vocabulary") if isinstance(payload.get("matched_vocabulary"), list) else [],
        "operation_plan": operation_plan,
        "notes": normalized_notes,
        "samples": payload.get("samples") if isinstance(payload.get("samples"), list) else [],
        "warning": warning,
    }


def validate_metrics_update(payload: dict[str, Any]) -> dict[str, int | None]:
    validated: dict[str, int | None] = {}
    for key, value in payload.items():
        if key not in METRIC_FIELDS:
            continue
        if value is None or value == "":
            validated[key] = None
            continue
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number.") from exc
        if number < 0:
            raise ValueError(f"{key} must be non-negative.")
        validated[key] = number
    return validated


def chunk_vocabulary(vocabulary: list[dict[str, Any]], chunk_size: int = 4) -> list[list[dict[str, Any]]]:
    safe_size = max(1, int(chunk_size or 4))
    normalized = [item for item in vocabulary if isinstance(item, dict)]
    return [normalized[index:index + safe_size] for index in range(0, len(normalized), safe_size)]


def _vocabulary_used_in_body(vocabulary: list[dict[str, Any]], body: str) -> list[dict[str, Any]]:
    if not body:
        return []
    used: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in vocabulary:
        if not isinstance(item, dict):
            continue
        word = _clean_string(item.get("word")).strip()
        if not word:
            continue
        if not re.search(r"[A-Za-z]", word):
            used.append(item)
            continue
        key = word.lower()
        if key in seen:
            continue
        escaped = re.escape(word)
        if re.search(rf"[（(]\s*{escaped}\s*[）)]", body, flags=re.IGNORECASE) or re.search(
            rf"\b{escaped}\b", body, flags=re.IGNORECASE
        ):
            used.append(item)
            seen.add(key)
    return used


def _vocabulary_context_body(vocabulary: list[dict[str, Any]]) -> str:
    usages: list[str] = []
    for item in vocabulary:
        if not isinstance(item, dict):
            continue
        usage = _clean_string(item.get("usage")).strip()
        word = _clean_string(item.get("word")).strip()
        if usage:
            usages.append(usage)
        elif word:
            usages.append(word)
    return f"上文对应：{'；'.join(usages)}。" if usages else ""


def _short_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _shorten_text(text: str, max_chars: int) -> str:
    clean = _clean_string(text)
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 1)].rstrip(" ，。；,.;") + "…"


def _sentence_chunks(text: str, *, target_chars: int = 150, max_chunks: int = 3) -> list[str]:
    clean = _clean_string(text)
    if not clean:
        return []
    sentences = [item.strip() for item in re.split(r"(?<=[。！？.!?])", clean) if item.strip()]
    if not sentences:
        sentences = [clean]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > target_chars:
            chunks.append(current)
            current = sentence
            if len(chunks) >= max_chunks:
                break
        else:
            current += sentence
    if current and len(chunks) < max_chunks:
        chunks.append(current)
    if not chunks:
        chunks = [_shorten_text(clean, target_chars)]
    return chunks[:max_chunks]


def build_image_cards(note: dict[str, Any], batch: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    title = _short_text(note.get("selected_title"), "小红书单词笔记")
    body = _short_text(note.get("body"))
    cover_text = _short_text(note.get("cover_text"), body[:80])
    cta = _short_text(note.get("cta"), "用 AI 把单词变成故事背。")
    hashtags = note.get("hashtags") if isinstance(note.get("hashtags"), list) else []
    vocabulary = note.get("vocabulary") if isinstance(note.get("vocabulary"), list) else []
    topic = _short_text((batch or {}).get("topic"), "AI 背单词")
    company_profile = (batch or {}).get("company_profile") if isinstance((batch or {}).get("company_profile"), dict) else {}
    is_company_profile = bool(company_profile)
    industries = [str(item) for item in company_profile.get("industries", [])[:3] if item]
    products = [str(item) for item in company_profile.get("products", [])[:5] if item]
    image_assets = company_profile.get("image_assets") if isinstance(company_profile.get("image_assets"), list) else []
    if is_company_profile:
        vocabulary = _vocabulary_used_in_body(vocabulary, body)[:COMPANY_CARD_VOCAB_LIMIT]
    word_count = len(vocabulary)
    if is_company_profile:
        company_label = _short_text(company_profile.get("company_name") or topic, topic)
        cover_title = f"读 {company_label} 学 {max(1, word_count)} 个英文词"
        cover_text = body or cover_text
    else:
        cover_title = title

    cards: list[dict[str, Any]] = [
        {
            "id": f"note-{note.get('id', 'draft')}-cover",
            "kind": "cover",
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "title": cover_title,
            "subtitle": topic,
            "body": cover_text,
            "vocabulary": [],
            "cta": cta,
            "hashtags": hashtags[:4],
            "image_asset": image_assets[0] if image_assets else {},
            "series_label": "GOODALPHABET 读公司学单词",
        }
    ]

    vocabulary_chunk_size = COMPANY_CARD_VOCAB_LIMIT if is_company_profile else 4
    for index, chunk in enumerate(chunk_vocabulary(vocabulary, chunk_size=vocabulary_chunk_size), start=1):
        cards.append(
            {
                "id": f"note-{note.get('id', 'draft')}-vocab-{index}",
                "kind": "vocabulary",
                "width": IMAGE_WIDTH,
                "height": IMAGE_HEIGHT,
                "title": "词汇深挖" if is_company_profile else "今天这几个词这样记",
                "subtitle": title,
                "body": "" if is_company_profile else _shorten_text(body, 180),
                "vocabulary": [
                    {
                        "word": _short_text(item.get("word")),
                        "definition": _short_text(item.get("definition")),
                        "usage": _short_text(item.get("usage")),
                    }
                    for item in chunk
                ],
                "cta": "",
                "hashtags": hashtags[:4],
            }
        )

    cards.append(
        {
            "id": f"note-{note.get('id', 'draft')}-cta",
            "kind": "cta",
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "title": "别再只背单词表",
            "subtitle": "GOODALPHABET 把公司故事变成单词记忆",
            "body": "把公司故事、产品场景和英文词汇放在一起记，下一次看到真实案例时就能想起这些词。",
            "vocabulary": [],
            "recap_words": [_short_text(item.get("word")) for item in vocabulary[:COMPANY_CARD_VOCAB_LIMIT]],
            "cta": cta,
            "hashtags": hashtags[:6],
        }
    )
    return cards


def _load_card_font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        "C:/Windows/Fonts/Dengb.ttf" if bold else "C:/Windows/Fonts/Deng.ttf",
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/SourceHanSansSC-Bold.otf" if bold else "C:/Windows/Fonts/SourceHanSansSC-Regular.otf",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/NotoSansSC-VF.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_card_text(text: str, max_chars: int) -> list[str]:
    clean = re.sub(r"\s+", " ", _clean_string(text))
    if not clean:
        return []
    lines: list[str] = []
    current = ""
    for char in clean:
        current += char
        if len(current) >= max_chars or char in "。！？.!?":
            lines.append(current.strip())
            current = ""
    if current.strip():
        lines.append(current.strip())
    return lines


def _text_width(draw: Any, text: str, font: Any) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0])


def _truncate_to_width(draw: Any, text: str, font: Any, max_width: int) -> str:
    clean = _clean_string(text)
    if _text_width(draw, clean, font) <= max_width:
        return clean
    ellipsis = "…"
    while clean and _text_width(draw, clean + ellipsis, font) > max_width:
        clean = clean[:-1]
    return clean.rstrip() + ellipsis if clean else ellipsis


def _text_units(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", _clean_string(text))
    if not clean:
        return []
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9&+./'_-]*|[\u4e00-\u9fff]|[^\s]", clean)


def _join_units(units: list[str]) -> str:
    output = ""
    previous = ""
    for unit in units:
        previous_last = previous[-1:] if previous else ""
        current_first = unit[:1]
        if output and re.match(r"[A-Za-z0-9]", previous_last) and re.match(r"[A-Za-z0-9]", current_first):
            output += " "
        elif output and previous_last in {",", ".", ";", ":"} and re.match(r"[A-Za-z0-9]", current_first):
            output += " "
        output += unit
        previous = unit
    return output


def _wrap_text_pixels(draw: Any, text: str, font: Any, max_width: int, *, max_lines: int | None = None) -> list[str]:
    units = _text_units(text)
    if not units:
        return []
    lines: list[str] = []
    current: list[str] = []
    for unit in units:
        candidate = current + [unit]
        closing_punctuation = unit in {"。", "！", "？", "!", "?", "，", ",", "；", ";", "：", ":"}
        if current and _text_width(draw, _join_units(candidate), font) > max_width:
            if closing_punctuation:
                current = candidate
            else:
                lines.append(_join_units(current))
                current = [unit]
                if max_lines and len(lines) >= max_lines:
                    lines[-1] = _truncate_to_width(draw, lines[-1], font, max_width)
                    return lines
        else:
            current = candidate
        if unit in {"。", "！", "？", "!", "?"}:
            lines.append(_join_units(current))
            current = []
            if max_lines and len(lines) >= max_lines:
                return lines
    if current:
        lines.append(_join_units(current))
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _truncate_to_width(draw, lines[-1], font, max_width)
    return lines


def _draw_wrapped_text(
    draw: Any,
    xy: tuple[int, int],
    text: str,
    font: Any,
    fill: str,
    max_width: int,
    *,
    line_height: int,
    max_lines: int | None = None,
) -> int:
    x, y = xy
    for line in _wrap_text_pixels(draw, text, font, max_width, max_lines=max_lines):
        draw.text((x, y), line, fill=fill, font=font)
        y += line_height
    return y


def _profile_style(company_name: str, ticker: str = "") -> dict[str, str]:
    keys = [company_name, ticker]
    catalog = _external_company_catalog()
    aliases = catalog.get("aliases", {})
    external_styles = catalog.get("brand_styles", {})
    for key in keys:
        normalized = _clean_string(key).lower()
        if normalized in BRAND_STYLES:
            return BRAND_STYLES[normalized]
        canonical = _clean_string(aliases.get(normalized)).lower() if isinstance(aliases, dict) else ""
        if isinstance(external_styles, dict):
            style = external_styles.get(normalized) or external_styles.get(canonical)
            if isinstance(style, dict):
                return {
                    "accent": _clean_string(style.get("accent")) or "#8f1d2c",
                    "mark": _clean_string(style.get("mark")) or (_clean_string(company_name)[:4] or "LOGO"),
                    "domain": _clean_string(style.get("domain")),
                }
    return {"accent": "#8f1d2c", "mark": _clean_string(company_name)[:4] or "LOGO", "domain": ""}


def _logo_candidates(logo_url: str, domain: str) -> list[str]:
    candidates = []
    clean_url = _clean_string(logo_url)
    clean_domain = _clean_string(domain)
    if clean_url:
        candidates.append(clean_url)
    if clean_domain:
        candidates.extend(
            [
                f"https://www.google.com/s2/favicons?domain={urllib.parse.quote(clean_domain)}&sz=256",
                f"https://icons.duckduckgo.com/ip3/{clean_domain}.ico",
            ]
        )
    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def _logo_cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return LOGO_CACHE_DIR / f"{digest}.png"


def _logo_failure_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return LOGO_CACHE_DIR / f"{digest}.fail"


def _recent_logo_failure(url: str) -> bool:
    path = _logo_failure_path(url)
    if not path.exists():
        return False
    try:
        return path.stat().st_mtime > (time.time() - 7 * 24 * 60 * 60)
    except OSError:
        return False


def _mark_logo_failure(url: str) -> None:
    try:
        _logo_failure_path(url).write_text("failed", encoding="utf-8")
    except OSError:
        pass


def _remote_image_cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return IMAGE_CACHE_DIR / f"{digest}.png"


def _load_remote_content_image(asset: dict[str, str] | None, *, max_side: int = 1400):
    from PIL import Image

    if not isinstance(asset, dict):
        return None
    url = _clean_string(asset.get("url"))
    if not url:
        return None
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _remote_image_cache_path(url)
    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception:
            try:
                cache_path.unlink()
            except OSError:
                pass
    if _recent_logo_failure(url):
        return None
    original_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(4)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 GOODALPHABET-XHS/1.0"})
        with urllib.request.urlopen(request, timeout=4) as response:
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type and "octet-stream" not in content_type:
                _mark_logo_failure(url)
                return None
            data = response.read(4 * 1024 * 1024)
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.thumbnail((max_side, max_side))
        image.save(cache_path, format="PNG", optimize=True)
        return image
    except Exception:
        _mark_logo_failure(url)
        return None
    finally:
        socket.setdefaulttimeout(original_timeout)


def _draw_image_cover(canvas: Any, image: Any, box: tuple[int, int, int, int], *, radius: int = 30) -> None:
    from PIL import Image, ImageDraw

    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    if not image or width <= 0 or height <= 0:
        return
    source = image.copy()
    scale = max(width / source.width, height / source.height)
    source = source.resize((max(1, int(source.width * scale)), max(1, int(source.height * scale))), Image.Resampling.LANCZOS)
    left = (source.width - width) // 2
    top = (source.height - height) // 2
    cropped = source.crop((left, top, left + width, top + height))
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
    canvas.paste(cropped, (x1, y1), mask)


def _draw_photo_panel(
    image_canvas: Any,
    draw: Any,
    *,
    photo: Any,
    box: tuple[int, int, int, int],
    accent: str,
    caption: str,
    source: str,
    font: Any,
    small_font: Any,
    show_label: bool = True,
) -> bool:
    if not photo:
        return False
    _draw_image_cover(image_canvas, photo, box, radius=30)
    if not show_label:
        return True
    x1, y1, x2, y2 = box
    overlay_h = 64
    if x2 - x1 < 80 or y2 - y1 < 100:
        return True
    overlay_top = max(y1 + 12, y2 - overlay_h - 18)
    overlay_bottom = y2 - 18
    if overlay_bottom <= overlay_top:
        return True
    draw.rounded_rectangle((x1 + 18, overlay_top, x2 - 18, overlay_bottom), radius=22, fill="#111827")
    label = caption or "真实图片素材"
    if source:
        label = f"{label} · {source}"
    draw.text((x1 + 42, overlay_top + 16), _truncate_to_width(draw, label, small_font, x2 - x1 - 92), fill="#ffffff", font=small_font)
    return True


def _trim_logo_canvas(image: Any) -> Any:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a > 16 and not (r > 244 and g > 244 and b > 244):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        bbox = rgba.getbbox()
        return rgba.crop(bbox) if bbox else rgba
    pad = max(2, int(max(max_x - min_x + 1, max_y - min_y + 1) * 0.08))
    return rgba.crop((max(0, min_x - pad), max(0, min_y - pad), min(width, max_x + pad + 1), min(height, max_y + pad + 1)))


def _fit_logo_image(image: Any, size: int) -> Any:
    from PIL import Image

    fitted = _trim_logo_canvas(image)
    fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
    if fitted.width < int(size * 0.62) and fitted.height < int(size * 0.62):
        scale = min(size / max(1, fitted.width), size / max(1, fitted.height), 3.0)
        fitted = fitted.resize((max(1, int(fitted.width * scale)), max(1, int(fitted.height * scale))), Image.Resampling.LANCZOS)
    return fitted


def _load_remote_logo(logo_url: str, size: int, *, domain: str = ""):
    from PIL import Image

    candidates = _logo_candidates(logo_url, domain)
    if not candidates:
        return None
    LOGO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        cache_path = _logo_cache_path(candidate)
        if cache_path.exists():
            try:
                return _fit_logo_image(Image.open(cache_path).convert("RGBA"), size)
            except Exception:
                try:
                    cache_path.unlink()
                except OSError:
                    pass
    original_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(2.5)
    try:
        for candidate in candidates:
            if _recent_logo_failure(candidate):
                continue
            cache_path = _logo_cache_path(candidate)
            try:
                request = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0 GOODALPHABET-XHS/1.0"})
                with urllib.request.urlopen(request, timeout=2.5) as response:
                    content_type = response.headers.get("content-type", "")
                    if "image" not in content_type and "octet-stream" not in content_type:
                        continue
                    data = response.read(512 * 1024)
                image = _fit_logo_image(Image.open(io.BytesIO(data)).convert("RGBA"), size)
                image.save(cache_path, format="PNG")
                return image
            except Exception:
                _mark_logo_failure(candidate)
                continue
    finally:
        socket.setdefaulttimeout(original_timeout)
    return None


def _draw_brand_header(
    image: Any,
    draw: Any,
    *,
    company_name: str,
    brand_mark: str,
    logo: Any,
    accent: str,
    title_font: Any,
    small_font: Any,
    meta: str,
) -> None:
    logo_box = (104, 96, 232, 224)
    draw.rounded_rectangle(logo_box, radius=26, fill="#ffffff", outline="#e5e7eb", width=2)
    if logo:
        x = 104 + (128 - logo.width) // 2
        y = 96 + (128 - logo.height) // 2
        image.paste(logo, (x, y), logo)
    else:
        draw.rounded_rectangle(logo_box, radius=26, fill=accent)
        mark_font = _load_card_font(26 if len(brand_mark) > 5 else 34, bold=True)
        draw.text((168, 160), brand_mark, anchor="mm", fill="#ffffff", font=mark_font)
    draw.text((256, 108), _truncate_to_width(draw, company_name, title_font, 600), fill="#111827", font=title_font)
    draw.text((256, 154), _truncate_to_width(draw, meta, small_font, 650), fill="#6b7280", font=small_font)


def _draw_chip_row(draw: Any, labels: list[str], *, x: int, y: int, max_width: int, font: Any, fill: str = "#4b5563") -> int:
    chip_x = x
    chip_y = y
    for chip in labels:
        label = _truncate_to_width(draw, chip, font, 280)
        width = _text_width(draw, label, font) + 34
        if chip_x + width > x + max_width:
            chip_x = x
            chip_y += 48
        draw.rounded_rectangle((chip_x, chip_y, chip_x + width, chip_y + 36), radius=18, fill="#f3f4f6")
        draw.text((chip_x + 17, chip_y + 6), label, fill=fill, font=font)
        chip_x += width + 12
    return chip_y + 42


def _draw_gpu_scene(draw: Any, box: tuple[int, int, int, int], accent: str, font: Any) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=30, fill="#101827")
    for i in range(7):
        x = x1 + 54 + i * 96
        draw.line((x, y1 + 44, x + 80, y2 - 44), fill="#1f6f3b", width=3)
    draw.rounded_rectangle((x1 + 92, y1 + 92, x2 - 92, y2 - 120), radius=26, fill="#1f2937", outline=accent, width=3)
    for i in range(4):
        cx = x1 + 178 + i * 150
        draw.rounded_rectangle((cx, y1 + 148, cx + 96, y1 + 244), radius=20, fill="#76b900")
        draw.text((cx + 48, y1 + 182), "GPU", anchor="mm", fill="#ffffff", font=font)
    draw.text((x1 + 92, y2 - 86), "GPU + CUDA + Data Center", fill="#d1fae5", font=font)


def _draw_consumer_scene(draw: Any, box: tuple[int, int, int, int], accent: str, font: Any) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=30, fill="#eef4ff")
    shelf_y = y2 - 96
    draw.rounded_rectangle((x1 + 58, shelf_y, x2 - 58, shelf_y + 18), radius=9, fill="#c7d2fe")
    colors = ["#1d4ed8", "#0ea5e9", "#f59e0b", "#10b981", "#ef4444"]
    labels = ["Tide", "Olay", "Gillette", "Pampers", "Oral-B"]
    for i, label in enumerate(labels):
        px = x1 + 84 + i * 134
        top = y1 + 108 + (i % 2) * 26
        draw.rounded_rectangle((px, top, px + 88, shelf_y), radius=24, fill=colors[i])
        draw.text((px + 44, top + 46), label[:6], anchor="mm", fill="#ffffff", font=font)
    draw.text((x1 + 72, y1 + 48), "Daily routine products", fill=accent, font=font)


def _draw_moutai_scene(draw: Any, box: tuple[int, int, int, int], accent: str, font: Any) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=30, fill="#fff7ed")
    draw.polygon([(x1, y2 - 120), (x1 + 190, y1 + 210), (x1 + 390, y2 - 120)], fill="#fed7aa")
    draw.polygon([(x1 + 260, y2 - 120), (x1 + 520, y1 + 160), (x2, y2 - 120)], fill="#fdba74")
    draw.rounded_rectangle((x1 + 430, y1 + 106, x1 + 560, y2 - 112), radius=36, fill="#9b1c31")
    draw.rounded_rectangle((x1 + 460, y1 + 64, x1 + 530, y1 + 126), radius=16, fill="#7f1d1d")
    draw.text((x1 + 495, y1 + 250), "茅台", anchor="mm", fill="#ffffff", font=font)
    draw.arc((x1 + 80, y2 - 156, x2 - 80, y2 + 70), start=200, end=340, fill="#60a5fa", width=14)
    draw.text((x1 + 72, y1 + 48), "产地 · 工艺 · 稀缺性", fill=accent, font=font)


def _draw_company_scene(draw: Any, *, company_name: str, box: tuple[int, int, int, int], accent: str, font: Any) -> None:
    normalized = _clean_string(company_name).lower()
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return
    height = y2 - y1
    if height < 180:
        draw.rounded_rectangle(box, radius=max(12, min(30, height // 3)), fill="#f3f4f6")
        draw.text((x1 + 28, y1 + max(18, height // 3)), "Product / market / impact", fill="#374151", font=font)
        return
    if "nvidia" in normalized or "英伟达" in normalized:
        _draw_gpu_scene(draw, box, accent, font)
    elif "procter" in normalized or "宝洁" in normalized or "p&g" in normalized:
        _draw_consumer_scene(draw, box, accent, font)
    elif "茅台" in normalized or "moutai" in normalized:
        _draw_moutai_scene(draw, box, accent, font)
    else:
        draw.rounded_rectangle(box, radius=30, fill="#f3f4f6")
        top = y1 + max(44, int(height * 0.18))
        bottom = y2 - max(44, int(height * 0.18))
        bar_height = max(32, bottom - top)
        for i in range(4):
            bar_top = min(bottom - 24, top + i * max(8, int(height * 0.06)))
            left = x1 + 90 + i * 160
            right = min(left + 100, x2 - 70)
            if right > left and bottom > bar_top:
                draw.rounded_rectangle((left, bar_top, right, bottom), radius=20, fill=accent)
        draw.text((x1 + 72, y1 + max(18, int(height * 0.12))), "Product / market / impact", fill="#374151", font=font)


def _draw_timeline(draw: Any, milestones: list[str], *, x: int, y: int, width: int, font: Any, small_font: Any, accent: str) -> int:
    if not milestones:
        return y
    draw.line((x + 24, y + 28, x + width - 24, y + 28), fill="#d1d5db", width=3)
    count = max(1, len(milestones))
    for index, item in enumerate(milestones[:4]):
        px = x + 24 + int((width - 48) * index / max(1, count - 1))
        draw.ellipse((px - 13, y + 15, px + 13, y + 41), fill=accent)
        draw.text((px - 80, y + 58), _truncate_to_width(draw, item, small_font, 170), fill="#4b5563", font=small_font)
    return y + 126


def render_image_cards_to_files(
    note: dict[str, Any],
    batch: dict[str, Any] | None,
    output_dir: str | Path,
    *,
    public_url_prefix: str = "",
) -> list[dict[str, Any]]:
    from PIL import Image, ImageDraw

    cards = build_image_cards(note, batch)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    company_profile = (batch or {}).get("company_profile") if isinstance((batch or {}).get("company_profile"), dict) else {}
    company_name = _short_text(company_profile.get("company_name") or (batch or {}).get("company_name") or cards[0]["subtitle"], "GOODALPHABET")
    ticker = _short_text(company_profile.get("ticker") or (batch or {}).get("company_ticker"))
    industries = [str(item) for item in company_profile.get("industries", [])[:3] if item]
    products = [str(item) for item in company_profile.get("products", [])[:4] if item]
    image_assets = company_profile.get("image_assets") if isinstance(company_profile.get("image_assets"), list) else []
    logo_url = _short_text(company_profile.get("logo_url"))
    style = _profile_style(company_name, ticker)
    accent = style["accent"]
    logo = _load_remote_logo(logo_url, 104, domain=style.get("domain", ""))
    primary_photo_asset = image_assets[0] if image_assets and isinstance(image_assets[0], dict) else {}
    primary_photo = _load_remote_content_image(primary_photo_asset)
    meta_parts = [item for item in [ticker, " / ".join(industries[:2])] if item]
    header_meta = " · ".join(meta_parts) or "Company profile vocabulary"
    colors = {
        "cover": ("#f7f2ea", "#111827", accent),
        "article": ("#fbfaf7", "#111827", accent),
        "visual": ("#f7f2ea", "#111827", accent),
        "vocabulary": ("#eaf5f7", "#111827", "#1f6f78"),
        "cta": ("#f6f2ff", "#111827", "#5b3cc4"),
    }
    header_font = _load_card_font(30, bold=True)
    title_font = _load_card_font(52, bold=True)
    subtitle_font = _load_card_font(32, bold=True)
    body_font = _load_card_font(30, bold=True)
    body_small_font = _load_card_font(26, bold=True)
    small_font = _load_card_font(24, bold=True)
    chip_font = _load_card_font(22, bold=True)
    word_font = _load_card_font(32, bold=True)
    visual_font = _load_card_font(24, bold=True)
    rendered: list[dict[str, Any]] = []
    for index, card in enumerate(cards, start=1):
        bg, fg, accent = colors.get(card["kind"], colors["cover"])
        image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), bg)
        draw = ImageDraw.Draw(image)
        content_x = 128
        content_right = IMAGE_WIDTH - content_x
        content_width = content_right - content_x
        draw.rectangle((0, 0, IMAGE_WIDTH, 18), fill=accent)
        draw.rounded_rectangle((72, 64, IMAGE_WIDTH - 72, IMAGE_HEIGHT - 64), radius=34, fill="#ffffff")
        _draw_brand_header(
            image,
            draw,
            company_name=company_name,
            brand_mark=style["mark"],
            logo=logo,
            accent=accent,
            title_font=header_font,
            small_font=small_font,
            meta=header_meta,
        )
        y = 282
        title_lines = _wrap_text_pixels(draw, card["title"], title_font, content_width, max_lines=3)
        for line in title_lines:
            draw.text((content_x, y), line, fill=fg, font=title_font)
            y += 64
        if card["kind"] == "visual":
            y += 6
            asset = card.get("image_asset") if isinstance(card.get("image_asset"), dict) else primary_photo_asset
            photo = primary_photo if asset == primary_photo_asset else _load_remote_content_image(asset)
            photo_drawn = _draw_photo_panel(
                image,
                draw,
                photo=photo,
                box=(content_x, y, content_right, y + 430),
                accent=accent,
                caption=_clean_string((asset or {}).get("caption")),
                source=_clean_string((asset or {}).get("source")),
                font=visual_font,
                small_font=small_font,
            )
            if not photo_drawn:
                _draw_company_scene(draw, company_name=company_name, box=(content_x, y, content_right, y + 430), accent=accent, font=visual_font)
            y += 474
            y = _draw_wrapped_text(draw, (content_x, y), card.get("body", ""), body_small_font, "#374151", content_width, line_height=36, max_lines=4)
            y += 26
            visual_products = [str(item) for item in card.get("products", []) if item][:6]
            if visual_products:
                draw.text((content_x, y), "代表产品 / 业务", fill=fg, font=subtitle_font)
                y += 48
                y = _draw_chip_row(draw, visual_products, x=content_x, y=y, max_width=content_width - 90, font=chip_font, fill="#4b5563")
            milestones = [str(item) for item in card.get("milestones", []) if item][:4]
            timeline_y = max(y + 38, 1060 if len(visual_products) > 3 else y + 38)
            y = _draw_timeline(draw, milestones, x=112, y=min(timeline_y, 1110), width=850, font=visual_font, small_font=small_font, accent=accent)
        elif card.get("body"):
            y += 22
            if card["kind"] == "cta" and company_profile:
                y = _draw_wrapped_text(
                    draw,
                    (content_x, y),
                    card["body"],
                    body_font,
                    "#374151",
                    content_width,
                    line_height=46,
                    max_lines=3,
                )
                recap_words = [str(item) for item in card.get("recap_words", []) if item][:5]
                if recap_words:
                    panel_y = max(y + 58, 560)
                    draw.rounded_rectangle((content_x, panel_y, content_right, panel_y + 250), radius=28, fill="#f8fafc", outline="#e9d5ff", width=2)
                    draw.text((content_x + 32, panel_y + 32), "本篇词汇回顾", fill=accent, font=subtitle_font)
                    chip_y = panel_y + 94
                    chip_x = content_x + 32
                    for word in recap_words:
                        label = _truncate_to_width(draw, word, chip_font, 260)
                        chip_w = _text_width(draw, label, chip_font) + 42
                        if chip_x + chip_w > content_right - 32:
                            chip_x = content_x + 32
                            chip_y += 56
                        draw.rounded_rectangle((chip_x, chip_y, chip_x + chip_w, chip_y + 42), radius=21, fill="#ede9fe")
                        draw.text((chip_x + 21, chip_y + 8), label, fill=accent, font=chip_font)
                        chip_x += chip_w + 14
                    y = panel_y + 292
            else:
                max_body_lines = 9 if card["kind"] == "cover" and company_profile else (5 if card["kind"] == "cover" else (12 if card["kind"] == "article" else 6))
                y = _draw_wrapped_text(
                    draw,
                    (content_x, y),
                    card["body"],
                    body_font,
                    "#374151",
                    content_width,
                    line_height=44 if card["kind"] != "article" else 48,
                    max_lines=max_body_lines,
                )
        if card["kind"] == "cover":
            y += 30
            chips = [*industries[:3], *products[:3]][:5]
            y = _draw_chip_row(draw, chips, x=content_x, y=y, max_width=content_width, font=chip_font, fill="#4b5563")
            if company_profile:
                scene_y = max(y + 26, 720)
                box = (content_x, scene_y, content_right, min(scene_y + 360, 1200))
                if primary_photo:
                    _draw_photo_panel(
                        image,
                        draw,
                        photo=primary_photo,
                        box=box,
                        accent=accent,
                        caption=_clean_string(primary_photo_asset.get("caption")),
                        source=_clean_string(primary_photo_asset.get("source")),
                        font=visual_font,
                        small_font=small_font,
                        show_label=False,
                    )
                else:
                    _draw_company_scene(draw, company_name=company_name, box=box, accent=accent, font=visual_font)
        if card["kind"] == "article" and card.get("section_index"):
            section_index = int(card.get("section_index") or 1)
            badge = f"0{section_index}"
            draw.rounded_rectangle((IMAGE_WIDTH - 190, 288, IMAGE_WIDTH - 112, 336), radius=24, fill="#f3f4f6")
            draw.text((IMAGE_WIDTH - 151, 299), badge, anchor="mm", fill=accent, font=small_font)
            if y < 820:
                fact_y = 860
                draw.rounded_rectangle((content_x, fact_y, content_right, fact_y + 230), radius=28, fill="#f9fafb", outline="#eef2f7", width=2)
                draw.text((144, fact_y + 30), "这一页在讲", fill=accent, font=subtitle_font)
                prompts = ["公司路径", "产品能力", "市场影响"]
                for prompt_index, prompt in enumerate(prompts):
                    row_y = fact_y + 86 + prompt_index * 42
                    draw.ellipse((148, row_y + 8, 164, row_y + 24), fill=accent)
                    draw.text((180, row_y), prompt, fill="#4b5563", font=body_small_font)
        if card.get("vocabulary"):
            if company_profile and card["kind"] == "vocabulary":
                intro_y = max(y + 26, 376)
                draw.rounded_rectangle((content_x, intro_y, content_right, intro_y + 72), radius=24, fill="#f8fafc", outline="#dbeafe", width=2)
                draw.text((content_x + 32, intro_y + 20), "把封面里的英文词拆开看：含义、语境、记忆点一次对齐", fill="#374151", font=small_font)
                y = intro_y + 102
            else:
                y = max(y + 20, 720)
            compact_vocabulary = bool(company_profile and len(card["vocabulary"]) >= 5)
            row_height = 122 if compact_vocabulary else 132
            row_gap = 134 if compact_vocabulary else 148
            word_y_offset = 12
            detail_y_offset = 58
            for item_index, item in enumerate(card["vocabulary"][:5], start=1):
                word = _short_text(item.get("word"))
                definition = _short_text(item.get("definition"))
                usage = _short_text(item.get("usage"))
                if y + row_height + 8 > IMAGE_HEIGHT - 172:
                    break
                draw.rounded_rectangle((content_x, y, content_right, y + row_height), radius=20, fill="#f3f4f6")
                if company_profile:
                    draw.rounded_rectangle((content_x + 20, y + 18, content_x + 62, y + 60), radius=21, fill=accent)
                    draw.text((content_x + 41, y + 39), f"{item_index}", anchor="mm", fill="#ffffff", font=small_font)
                    text_x = content_x + 84
                    draw.text((text_x, y + word_y_offset), _truncate_to_width(draw, word, word_font, 520), fill=accent, font=word_font)
                    draw.text((text_x, y + detail_y_offset), _truncate_to_width(draw, f"核心含义：{definition}", small_font, content_width - 110), fill="#374151", font=small_font)
                    if usage:
                        draw.text((text_x, y + detail_y_offset + 36), _truncate_to_width(draw, f"公司语境：{usage}", small_font, content_width - 110), fill="#4b5563", font=small_font)
                else:
                    draw.text((content_x + 24, y + word_y_offset), _truncate_to_width(draw, word, word_font, 360), fill=accent, font=word_font)
                    draw.text((content_x + 24, y + detail_y_offset), _truncate_to_width(draw, definition, small_font, 390), fill="#374151", font=small_font)
                    if usage:
                        draw.text((560, y + detail_y_offset), _truncate_to_width(draw, usage, small_font, 360), fill="#4b5563", font=small_font)
                y += row_gap
        if card["kind"] == "cta" and card.get("cta"):
            y = min(max(y + 34, 760), 1020)
            draw.rounded_rectangle((content_x, y, content_right, y + 96), radius=24, fill="#f9fafb", outline="#ede9fe", width=2)
            _draw_wrapped_text(draw, (content_x + 28, y + 22), card["cta"], body_small_font, "#4b5563", content_width - 56, line_height=36, max_lines=2)
            if company_profile:
                prompt_y = y + 128
                draw.rounded_rectangle((content_x, prompt_y, content_right, prompt_y + 82), radius=24, fill="#ffffff", outline="#f3e8ff", width=2)
                draw.text((content_x + 28, prompt_y + 24), "下一篇想看哪家公司 / 产品？", fill=accent, font=body_small_font)
        footer = " ".join(card.get("hashtags", [])[:4]) or _short_text(card.get("cta"), "GOODALPHABET")
        draw.line((content_x, IMAGE_HEIGHT - 178, content_right, IMAGE_HEIGHT - 178), fill="#e5e7eb", width=1)
        footer_prefix = "GOODALPHABET · 读公司学单词"
        footer_text = f"{footer_prefix}  {footer}" if company_profile else footer
        draw.text((content_x, IMAGE_HEIGHT - 142), _truncate_to_width(draw, footer_text, small_font, content_width - 120), fill="#6b7280", font=small_font)
        filename = f"card_{index}_{card['kind']}.png"
        path = target_dir / filename
        image.save(path, format="PNG", optimize=True)
        url = f"{public_url_prefix.rstrip('/')}/{filename}" if public_url_prefix else str(path)
        rendered.append({**card, "image_path": str(path), "image_url": url})
    return rendered
