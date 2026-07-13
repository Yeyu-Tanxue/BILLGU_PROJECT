import json

import pytest

import api.xhs_factory as xhs_factory
from api.xhs_factory import (
    DEFAULT_NOTE_COUNT,
    DEFAULT_WORDS_PER_NOTE,
    build_company_generation_prompt,
    build_company_intro_prompt,
    build_generation_prompt,
    build_image_cards,
    chunk_vocabulary,
    get_options,
    match_company_vocabulary,
    normalize_company_profile,
    parse_company_generation_response,
    parse_generation_response,
    render_image_cards_to_files,
    sample_words,
    search_company_profile,
    validate_company_notes,
    validate_metrics_update,
)


class FakeDb:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        sql, params = self.calls[-1]
        if "FROM wordbooks" in sql:
            return [
                {"id": 1, "name": "GRE", "language": "en"},
                {"id": 2, "name": "JLPT N2", "language": "ja"},
            ]
        if "FROM words" in sql:
            _book_id, limit, offset = params
            words = [
                {"id": 10, "word": "resilient", "phonetic": "", "definition": "able to recover", "seq": 1},
                {"id": 11, "word": "meticulous", "phonetic": "", "definition": "very careful", "seq": 2},
            ]
            return words[offset: offset + limit]
        return []


def test_get_options_returns_wordbooks_and_defaults():
    payload = get_options(FakeDb())

    assert payload["defaults"] == {"note_count": DEFAULT_NOTE_COUNT, "words_per_note": DEFAULT_WORDS_PER_NOTE}
    assert payload["wordbooks"][0]["name"] == "GRE"
    assert "exam_anxiety" in [scene["value"] for scene in payload["scenes"]]
    assert "story" in [style["value"] for style in payload["styles"]]


def test_sample_words_returns_requested_words_from_wordbook():
    words = sample_words(FakeDb(), wordbook_id=1, count=2)

    assert [word["word"] for word in words] == ["resilient", "meticulous"]


def test_sample_words_rejects_empty_result():
    class EmptyDb(FakeDb):
        def fetchall(self):
            if "FROM words" in self.calls[-1][0]:
                return []
            return super().fetchall()

    with pytest.raises(ValueError, match="No words available"):
        sample_words(EmptyDb(), wordbook_id=99, count=5)


def test_build_generation_prompt_contains_topic_product_and_words():
    prompt = build_generation_prompt(
        scene="workplace",
        topic="interview panic",
        style="comedy",
        note_count=3,
        words_per_note=2,
        language="en",
        words=[
            {"word": "resilient", "definition": "able to recover"},
            {"word": "meticulous", "definition": "very careful"},
        ],
    )

    assert "interview panic" in prompt
    assert "AI vocabulary learning product" in prompt
    assert "resilient: able to recover" in prompt
    assert '"notes"' in prompt
    assert "3 notes" in prompt


def test_match_company_vocabulary_selects_relevant_mandarin_words():
    company_profile = {
        "company": "宝洁",
        "summary": "宝洁是一家消费品公司，主要销售洗发水、牙膏、清洁用品和护理产品，品牌影响全球消费者。",
        "keywords": ["消费品", "洗发水", "牙膏", "清洁", "品牌", "消费者"],
    }
    vocab = [
        {"hanzi": "公司", "pinyin": "gōng sī", "meaning": "company"},
        {"hanzi": "产品", "pinyin": "chǎn pǐn", "meaning": "product"},
        {"hanzi": "洗", "pinyin": "xǐ", "meaning": "to wash"},
        {"hanzi": "影响", "pinyin": "yǐng xiǎng", "meaning": "influence"},
        {"hanzi": "昨天", "pinyin": "zuó tiān", "meaning": "yesterday"},
    ]

    matched = match_company_vocabulary(company_profile, vocab, limit=4)

    assert [item["hanzi"] for item in matched] == ["公司", "产品", "洗", "影响"]


def test_match_company_vocabulary_falls_back_for_english_wordbooks_without_keyword_hits():
    profile = {
        "company_name": "NVIDIA",
        "source_summary": "NVIDIA designs GPUs, semiconductors, AI computing platforms and software.",
    }
    words = [
        {"id": 1, "word": "aloft", "definition": "in flight", "seq": 1},
        {"id": 2, "word": "abide", "definition": "to tolerate", "seq": 2},
    ]

    matched = match_company_vocabulary(profile, words, limit=2, angle="technology_product")

    assert [item["word"] for item in matched] == ["aloft", "abide"]


def test_match_company_vocabulary_prioritizes_company_friendly_english_fallbacks():
    profile = {
        "company_name": "NVIDIA",
        "source_summary": "NVIDIA designs GPUs, semiconductors, AI computing platforms and software.",
    }
    words = [
        {"id": 1, "word": "hale", "definition": "健壮的", "seq": 1},
        {"id": 2, "word": "belligerent", "definition": "好斗的", "seq": 2},
        {"id": 3, "word": "innovative", "definition": "创新的", "seq": 2085},
        {"id": 4, "word": "robust", "definition": "强健的", "seq": 1459},
    ]

    matched = match_company_vocabulary(profile, words, limit=2, angle="technology_product")

    assert [item["word"] for item in matched] == ["robust", "innovative"]


def test_match_company_vocabulary_demotes_awkward_gre_words_for_company_intro():
    profile = normalize_company_profile(
        company_name="NVIDIA",
        ticker="NVDA",
        provider_payloads=[search_company_profile("NVIDIA", ticker="NVDA")],
    )
    words = [
        {"id": 1, "word": "ruffle", "definition": "扰乱，打扰；disturb", "seq": 1},
        {"id": 2, "word": "elevate", "definition": "提升；improve", "seq": 2},
        {"id": 3, "word": "surly", "definition": "脾气不好的；churlish", "seq": 3},
        {"id": 4, "word": "elaborate", "definition": "详细的，复杂的；complexity", "seq": 4},
        {"id": 5, "word": "guzzle", "definition": "狂饮；drink greedily", "seq": 5},
        {"id": 6, "word": "advocate", "definition": "支持，提倡；support", "seq": 6},
        {"id": 7, "word": "document", "definition": "证实；show truth by evidence", "seq": 7},
        {"id": 8, "word": "propagate", "definition": "传播，宣传；spread out", "seq": 8},
        {"id": 9, "word": "unflagging", "definition": "不懈的；not declining in strength", "seq": 9},
        {"id": 10, "word": "fluent", "definition": "表达流利的；able to express well", "seq": 10},
    ]

    matched = match_company_vocabulary(profile, words, limit=6, angle="technology_product")

    assert [item["word"] for item in matched[:6]] == [
        "elevate",
        "elaborate",
        "advocate",
        "propagate",
        "document",
        "unflagging",
    ]
    assert "surly" not in [item["word"] for item in matched[:6]]
    assert "guzzle" not in [item["word"] for item in matched[:6]]


def test_match_company_vocabulary_uses_chinese_industry_context_for_english_words():
    words = [
        {"id": 1, "word": "household", "definition": "consumer goods used in home care", "seq": 1},
        {"id": 2, "word": "aircraft", "definition": "airplane used for flight and aviation", "seq": 2},
        {"id": 3, "word": "compute", "definition": "data center semiconductor computing", "seq": 3},
    ]

    consumer_matches = match_company_vocabulary(
        {"company_name": "宝洁", "industries": ["日化消费品", "家庭护理"], "source_summary": "洗衣和个人护理品牌"},
        words,
        limit=2,
        angle="company_overview",
    )
    aviation_matches = match_company_vocabulary(
        {"company_name": "Boeing", "industries": ["航空航天", "商用飞机"], "source_summary": "飞机制造和航空服务"},
        words,
        limit=2,
        angle="aviation_travel",
    )

    assert consumer_matches[0]["word"] == "household"
    assert aviation_matches[0]["word"] == "aircraft"


def test_match_company_vocabulary_diversifies_gre_fallbacks_by_company_context():
    words = [
        {"id": 1, "word": "elevate", "definition": "提升；improve", "seq": 1},
        {"id": 2, "word": "elaborate", "definition": "复杂的；complex", "seq": 2},
        {"id": 3, "word": "advocate", "definition": "支持；support", "seq": 3},
        {"id": 4, "word": "propagate", "definition": "传播；spread", "seq": 4},
        {"id": 5, "word": "aloft", "definition": "in flight; in the air", "seq": 5},
        {"id": 6, "word": "maven", "definition": "expert in a market or consumer category", "seq": 6},
        {"id": 7, "word": "perceptive", "definition": "showing consumer insight and understanding", "seq": 7},
        {"id": 8, "word": "robust", "definition": "strong and resilient", "seq": 8},
    ]

    tech = match_company_vocabulary(
        {"company_name": "NVIDIA", "industries": ["半导体", "AI 计算"], "source_summary": "GPU 数据中心 人工智能 软件平台"},
        words,
        limit=5,
        angle="company_overview",
    )
    consumer = match_company_vocabulary(
        {"company_name": "宝洁", "industries": ["日化消费品", "家庭护理"], "source_summary": "洗衣 护理 消费者 品牌"},
        words,
        limit=5,
        angle="company_overview",
    )
    aviation = match_company_vocabulary(
        {"company_name": "Boeing", "industries": ["航空航天", "商用飞机"], "source_summary": "飞机 航空 服务 安全"},
        words,
        limit=5,
        angle="company_overview",
    )

    assert [item["word"] for item in consumer[:3]] != [item["word"] for item in tech[:3]]
    assert aviation[0]["word"] == "aloft"
    assert consumer[0]["word"] in {"maven", "perceptive"}


def test_search_company_profile_returns_enriched_nvidia_facts_without_manual_text():
    profile = search_company_profile("NVIDIA", ticker="NVDA")

    assert profile["company"] == "NVIDIA"
    assert profile["search_provider"] in {"known_profile", "wikipedia"}
    assert "GPU" in profile["summary"] or "graphics processing" in profile["summary"].lower()
    assert "semiconductor" in " ".join(profile["industries"]).lower()
    assert any("CUDA" in product for product in profile["products"])
    assert profile["source_urls"]


@pytest.mark.parametrize(
    ("company", "ticker", "expected"),
    [
        ("Procter & Gamble", "PG", "consumer goods"),
        ("Boeing", "BA", "aerospace"),
        ("贵州茅台", "600519", "baijiu"),
        ("HESAI", "HSAI", "lidar"),
    ],
)
def test_search_company_profile_returns_known_profiles_for_more_companies(company, ticker, expected):
    profile = search_company_profile(company, ticker=ticker)

    assert profile["search_provider"] == "known_profile"
    assert expected in " ".join(profile["industries"]).lower()
    assert profile["products"]
    assert profile["logo_url"].startswith("https://")
    assert profile["source_urls"]


def test_search_company_profile_returns_specific_hesai_products():
    profile = search_company_profile("HESAI")

    profile_text = " ".join([profile["summary"], *profile["products"], *profile["industries"]])
    assert profile["search_provider"] == "known_profile"
    assert "AT128" in profile_text
    assert "Pandar" in profile_text
    assert "ADAS" in profile_text
    assert "运营人员补充" not in profile["summary"]


def test_build_company_generation_prompt_keeps_company_subject_and_forbids_word_list_body():
    profile = normalize_company_profile(
        company_name="NVIDIA",
        ticker="NVDA",
        provider_payloads=[search_company_profile("NVIDIA", ticker="NVDA")],
    )
    prompt = build_company_generation_prompt(
        profile=profile,
        style="story",
        angle="technology_product",
        note_count=1,
        words_per_note=20,
        language="en",
        words=[
            {"word": "elevate", "definition": "提升；improve", "company_context": "提升 AI 计算能力（elevate）"},
            {"word": "elaborate", "definition": "复杂的；complex", "company_context": "复杂生态（elaborate ecosystem）"},
            {"word": "advocate", "definition": "支持；support", "company_context": "支持开发者生态（advocate）"},
        ],
    )

    assert "Company/product to introduce: NVIDIA" in prompt
    assert "GOODALPHABET must not be the subject" in prompt
    assert "Do not append a vocabulary list after the body" in prompt
    assert "Use the most natural subset" in prompt
    assert "中文表达（English term）" in prompt


def test_build_company_generation_prompt_requires_vivid_connected_narrative_and_manual_publishing():
    profile = normalize_company_profile(
        company_name="NVIDIA",
        ticker="NVDA",
        provider_payloads=[search_company_profile("NVIDIA", ticker="NVDA")],
    )
    prompt = build_company_generation_prompt(
        profile=profile,
        style="story",
        angle="technology_product",
        note_count=1,
        words_per_note=8,
        language="en",
        words=[
            {"word": "elevate", "definition": "提升；improve", "company_context": "提升 AI 计算能力（elevate）"},
            {"word": "propagate", "definition": "传播；spread", "company_context": "传播到开发者生态（propagate）"},
        ],
    )

    assert "Narrative guidance:" in prompt
    assert "Use a connected story arc" in prompt
    assert "fact chain" in prompt
    assert "Manual publishing only" in prompt
    assert "Do not include claims that the note was automatically posted" in prompt


def test_validate_company_notes_rejects_goodalphabet_ad_subject():
    notes = [
        {
            "selected_title": "GOODALPHABET: Your AI-Powered Vocabulary Learning Companion",
            "titles": ["GOODALPHABET: Your AI-Powered Vocabulary Learning Companion"],
            "body": "GOODALPHABET是一款人工智能词汇学习产品。它能有效提升（elevate）你的词汇量。",
            "vocabulary": [{"word": "elevate", "definition": "提升"}],
        }
    ]

    with pytest.raises(ValueError, match="Company note 1 is about GOODALPHABET"):
        validate_company_notes(notes, company_name="NVIDIA")


def test_validate_company_notes_rejects_body_without_target_company():
    notes = [
        {
            "selected_title": "AI 词汇学习工具",
            "titles": ["AI 词汇学习工具"],
            "body": "这款工具能提升（elevate）学习效率，并提供流畅（fluent）的复习体验。",
            "vocabulary": [{"word": "elevate", "definition": "提升"}],
        }
    ]

    with pytest.raises(ValueError, match="must mention NVIDIA"):
        validate_company_notes(notes, company_name="NVIDIA")


def test_validate_company_notes_rejects_pasted_vocabulary_list_body():
    notes = [
        {
            "selected_title": "NVIDIA 公司资料卡",
            "titles": ["NVIDIA 公司资料卡"],
            "body": "NVIDIA 通过平台提升（elevate）AI 计算能力。\n\n提升（elevate）\n复杂（elaborate）",
            "vocabulary": [{"word": "elevate", "definition": "提升"}],
        }
    ]

    with pytest.raises(ValueError, match="pasted vocabulary list"):
        validate_company_notes(notes, company_name="NVIDIA")


def test_validate_company_notes_rejects_too_short_body_for_company_intro():
    notes = [
        {
            "selected_title": "NVIDIA 公司资料卡",
            "titles": ["NVIDIA 公司资料卡"],
            "body": "NVIDIA 提升（elevate）AI 计算。",
            "vocabulary": [{"word": "elevate", "definition": "提升"}],
        }
    ]

    with pytest.raises(ValueError, match="too short"):
        validate_company_notes(notes, company_name="NVIDIA", min_body_chars=80)


def test_validate_company_notes_rejects_too_few_embedded_words():
    notes = [
        {
            "selected_title": "NVIDIA 公司资料卡",
            "titles": ["NVIDIA 公司资料卡"],
            "body": "NVIDIA 从图形处理器起家，后来用 CUDA 和数据中心平台提升（elevate）AI 训练效率，并把软硬件生态带到云服务、科研和自动驾驶场景。",
            "vocabulary": [{"word": "elevate", "definition": "提升"}],
        }
    ]

    with pytest.raises(ValueError, match="must embed at least 3"):
        validate_company_notes(notes, company_name="NVIDIA", min_vocabulary_count=3)


def test_validate_company_notes_accepts_coherent_company_intro():
    notes = [
        {
            "selected_title": "NVIDIA 如何成为 AI 基础设施公司",
            "titles": ["NVIDIA 如何成为 AI 基础设施公司"],
            "body": "NVIDIA 从图形处理器起家，后来用 CUDA 和数据中心平台提升（elevate）AI 训练效率，并把复杂（elaborate）的软硬件生态传播（propagate）到云服务、科研和自动驾驶场景。",
            "vocabulary": [
                {"word": "elevate", "definition": "提升"},
                {"word": "elaborate", "definition": "复杂的"},
                {"word": "propagate", "definition": "传播"},
            ],
        }
    ]

    validate_company_notes(notes, company_name="NVIDIA", min_vocabulary_count=3, min_body_chars=80)


def test_build_company_intro_prompt_requires_chinese_xhs_notes_cards_and_plan():
    prompt = build_company_intro_prompt(
        company_profile={
            "company": "宝洁",
            "summary": "宝洁是一家消费品公司，旗下产品涉及洗护、口腔护理和清洁。",
            "sources": [{"title": "P&G overview", "url": "https://example.com"}],
            "keywords": ["消费品", "洗护", "清洁"],
        },
        vocabulary=[
            {"hanzi": "公司", "pinyin": "gōng sī", "meaning": "company"},
            {"hanzi": "产品", "pinyin": "chǎn pǐn", "meaning": "product"},
        ],
        note_count=2,
    )

    assert "中文小红书图文笔记" in prompt
    assert "宝洁" in prompt
    assert "公司资料摘要" in prompt
    assert "自然引出中文词汇" in prompt
    assert "operation_plan" in prompt
    assert "image_cards" in prompt
    assert "不要编造未经来源支持的公司事实" in prompt


def test_parse_company_generation_response_normalizes_plan_notes_and_examples():
    raw = json.dumps(
        {
            "company": "宝洁",
            "company_profile": {"summary": "消费品公司"},
            "matched_vocabulary": [{"hanzi": "公司", "pinyin": "gōng sī", "meaning": "company"}],
            "operation_plan": {
                "positioning": "用公司故事学中文商业词",
                "weekly_calendar": ["周一 公司历史"],
                "content_series": ["品牌词汇"],
                "title_formulas": ["从{company}学{word}"],
                "review_checklist": ["事实需要来源"],
            },
            "notes": [
                {
                    "titles": ["从宝洁学中文商业词"],
                    "body": "宝洁是一家消费品公司。",
                    "vocabulary": [{"hanzi": "公司", "pinyin": "gōng sī", "meaning": "company", "usage": "一家大公司"}],
                    "cover_text": "宝洁公司词汇",
                    "image_prompt": "clean xhs cards",
                    "image_cards": [{"kind": "cover", "title": "宝洁"}],
                    "hashtags": ["#中文学习"],
                    "cta": "关注继续学",
                    "quality_notes": ["自然"],
                    "risk_flags": [],
                }
            ],
            "samples": [{"company": "宝洁", "topic": "产品与品牌"}],
        },
        ensure_ascii=False,
    )

    parsed = parse_company_generation_response(raw, requested_count=1)

    assert parsed["company"] == "宝洁"
    assert parsed["operation_plan"]["positioning"] == "用公司故事学中文商业词"
    assert parsed["notes"][0]["selected_title"] == "从宝洁学中文商业词"
    assert parsed["notes"][0]["vocabulary"][0]["word"] == "公司"
    assert parsed["notes"][0]["image_cards"][0]["kind"] == "cover"
    assert parsed["samples"][0]["topic"] == "产品与品牌"


def test_parse_company_generation_response_accepts_single_note_object():
    raw = json.dumps(
        {
            "titles": ["NVIDIA 公司资料卡"],
            "body": "NVIDIA 的图形处理器（graphics processor）常用于数据中心。",
            "vocabulary": [{"word": "processor", "definition": "处理器"}],
            "cover_text": "NVIDIA 资料卡",
            "image_prompt": "company profile card",
            "hashtags": ["#英语词汇"],
            "cta": "收藏这张资料卡",
            "quality_notes": [],
            "risk_flags": [],
        },
        ensure_ascii=False,
    )

    parsed = parse_company_generation_response(raw, requested_count=1)

    assert parsed["notes"][0]["selected_title"] == "NVIDIA 公司资料卡"


def test_parse_company_generation_response_accepts_title_content_object():
    raw = json.dumps(
        {
            "title": "NVIDIA 一句话资料卡",
            "content": "NVIDIA 的平台（platform）覆盖 AI 和数据中心。",
            "vocabulary": [{"word": "platform", "definition": "平台"}],
        },
        ensure_ascii=False,
    )

    parsed = parse_company_generation_response(raw, requested_count=1)

    assert parsed["notes"][0]["selected_title"] == "NVIDIA 一句话资料卡"
    assert "平台（platform）" in parsed["notes"][0]["body"]


def test_search_company_profile_falls_back_without_search_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setenv("XHS_CODEX_PROFILE_ENABLED", "0")

    profile = search_company_profile("不存在的测试公司XYZ")

    assert profile["company"] == "不存在的测试公司XYZ"
    assert profile["search_provider"] == "fallback"
    assert "不存在的测试公司XYZ" in profile["summary"]


def test_codex_company_profile_is_enabled_by_default(monkeypatch, tmp_path):
    output = {
        "company": "HESAI",
        "summary": "Hesai develops lidar sensors including AT128 for ADAS and Pandar products for robotics.",
        "industries": ["lidar", "autonomous driving"],
        "products": ["AT128", "Pandar"],
        "source_urls": ["https://www.hesaitech.com/"],
    }

    def fake_run(command, **kwargs):
        output_path = command[command.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(output))

    monkeypatch.delenv("XHS_CODEX_PROFILE_ENABLED", raising=False)
    monkeypatch.setattr(xhs_factory.subprocess, "run", fake_run)

    profile = xhs_factory._codex_company_profile("HESAI")

    assert profile
    assert profile["search_provider"] == "codex_exec"
    assert "AT128" in profile["summary"]
    assert "Pandar" in profile["products"]


def test_codex_company_profile_can_be_disabled(monkeypatch):
    monkeypatch.setenv("XHS_CODEX_PROFILE_ENABLED", "false")

    assert xhs_factory._codex_company_profile("HESAI") is None


def test_parse_generation_response_normalizes_notes_and_count_warning():
    raw = json.dumps({
        "notes": [
            {
                "titles": ["Title A", "Title B", "Title C"],
                "body": "Body",
                "vocabulary": [{"word": "resilient", "definition": "able to recover"}],
                "cover_text": "Cover",
                "image_prompt": "Image",
                "hashtags": ["#gre"],
                "cta": "Light CTA",
                "quality_notes": ["natural"],
                "risk_flags": [],
            }
        ]
    })

    parsed = parse_generation_response(raw, requested_count=2)

    assert parsed["warning"] == "Generated 1 notes, requested 2."
    assert parsed["notes"][0]["selected_title"] == "Title A"
    assert parsed["notes"][0]["hashtags"] == ["#gre"]


def test_parse_generation_response_rejects_invalid_json():
    with pytest.raises(ValueError, match="valid JSON"):
        parse_generation_response("not json", requested_count=1)


def test_parse_generation_response_accepts_markdown_json_fence():
    raw = """```json
    {"notes":[{"titles":["Title"],"body":"Body","vocabulary":[],"cover_text":"","image_prompt":"","hashtags":[],"cta":"","quality_notes":[],"risk_flags":[]}]}
    ```"""

    parsed = parse_generation_response(raw, requested_count=1)

    assert parsed["notes"][0]["selected_title"] == "Title"


def test_parse_generation_response_extracts_json_from_surrounding_text():
    raw = """
    好的，下面是生成结果：
    {
      "notes": [
        {
          "titles": ["Title"],
          "body": "Body",
          "vocabulary": [],
          "cover_text": "",
          "image_prompt": "",
          "hashtags": [],
          "cta": "",
          "quality_notes": [],
          "risk_flags": []
        }
      ]
    }
    以上内容可直接使用。
    """

    parsed = parse_generation_response(raw, requested_count=1)

    assert parsed["notes"][0]["selected_title"] == "Title"


def test_validate_metrics_update_accepts_non_negative_numbers():
    payload = validate_metrics_update({"views": 100, "likes": "12", "comments": None})

    assert payload == {"views": 100, "likes": 12, "comments": None}


def test_validate_metrics_update_rejects_negative_numbers():
    with pytest.raises(ValueError, match="must be non-negative"):
        validate_metrics_update({"views": -1})


def test_chunk_vocabulary_groups_items_in_fours():
    vocabulary = [{"word": f"word{i}", "definition": f"def{i}"} for i in range(9)]

    chunks = chunk_vocabulary(vocabulary, chunk_size=4)

    assert [len(chunk) for chunk in chunks] == [4, 4, 1]


def test_build_image_cards_creates_cover_vocab_and_cta_cards():
    note = {
        "id": 42,
        "selected_title": "考前崩溃时我这样背 GRE",
        "body": "我把 resilient 和 meticulous 放进一个面试故事里，突然就记住了。",
        "vocabulary": [
            {"word": "resilient", "definition": "有韧性的；能恢复的", "usage": "bounce back after stress"},
            {"word": "meticulous", "definition": "一丝不苟的", "usage": "meticulous notes"},
        ],
        "cover_text": "别再硬刷单词表",
        "hashtags": ["#GRE", "#背单词"],
        "cta": "用 AI 把单词变成故事背。",
    }
    batch = {"topic": "考前崩溃", "scene": "exam_anxiety"}

    cards = build_image_cards(note, batch)

    assert [card["kind"] for card in cards] == ["cover", "vocabulary", "cta"]
    assert all(card["width"] == 1080 and card["height"] == 1440 for card in cards)
    assert cards[0]["title"] == "考前崩溃时我这样背 GRE"
    assert cards[1]["vocabulary"][0]["definition"] == "有韧性的；能恢复的"
    assert cards[1]["vocabulary"][1]["usage"] == "meticulous notes"
    assert cards[2]["cta"] == "用 AI 把单词变成故事背。"


def test_build_company_image_cards_keep_intro_on_cover_and_skip_article_pages():
    note = {
        "id": "nvidia",
        "selected_title": "读 NVIDIA 学 3 个英文词",
        "body": "NVIDIA 建立了 AI 基础设施（infrastructure），用战略性的（strategic）平台推动创新（innovation）。",
        "vocabulary": [
            {"word": "infrastructure", "definition": "基础设施", "usage": "基础设施（infrastructure）"},
            {"word": "strategic", "definition": "战略性的", "usage": "战略性的（strategic）平台"},
            {"word": "innovation", "definition": "创新", "usage": "创新（innovation）"},
        ],
        "cover_text": "NVIDIA 是 AI 计算公司。",
        "hashtags": ["#GOODALPHABET"],
        "cta": "用 GOODALPHABET 把公司故事变成单词记忆。",
    }
    batch = {
        "topic": "NVIDIA",
        "company_profile": {
            "company_name": "NVIDIA",
            "industries": ["半导体"],
            "products": ["GPU"],
            "image_assets": [{"url": "https://example.com/nvidia.jpg"}],
        },
    }

    cards = build_image_cards(note, batch)

    assert [card["kind"] for card in cards] == ["cover", "vocabulary", "cta"]
    assert cards[0]["body"] == note["body"]
    assert cards[0]["image_asset"] == {"url": "https://example.com/nvidia.jpg"}
    assert cards[-1]["body"] != note["body"]


def test_build_company_image_cards_filter_vocabulary_to_words_used_in_body():
    note = {
        "id": "pg",
        "selected_title": "读宝洁学词",
        "body": "宝洁用产品组合（portfolio）覆盖日常需求，并保持品牌韧性（resilience）。",
        "vocabulary": [
            {"word": "portfolio", "definition": "产品组合", "usage": "产品组合（portfolio）"},
            {"word": "resilience", "definition": "韧性", "usage": "韧性（resilience）"},
            {"word": "sustainable", "definition": "可持续的", "usage": "可持续的（sustainable）增长"},
        ],
        "cover_text": "宝洁公司介绍",
        "hashtags": ["#GOODALPHABET"],
    }
    batch = {"topic": "宝洁", "company_profile": {"company_name": "宝洁"}}

    cards = build_image_cards(note, batch)
    vocabulary_words = [
        item["word"]
        for card in cards
        for item in card.get("vocabulary", [])
    ]

    assert vocabulary_words == ["portfolio", "resilience"]


def test_build_company_vocabulary_card_body_matches_only_its_vocabulary():
    note = {
        "id": "moutai",
        "selected_title": "读茅台学词",
        "body": "茅台形成商业基础设施（infrastructure），也需要品牌韧性（resilience）。未展示的词不应进入词汇页。",
        "vocabulary": [
            {"word": "infrastructure", "definition": "基础设施", "usage": "商业基础设施（infrastructure）"},
            {"word": "resilience", "definition": "韧性", "usage": "品牌韧性（resilience）"},
            {"word": "sustainable", "definition": "可持续的", "usage": "可持续的（sustainable）"},
        ],
        "cover_text": "茅台公司介绍",
    }
    batch = {"topic": "贵州茅台", "company_profile": {"company_name": "贵州茅台"}}

    cards = build_image_cards(note, batch)
    vocab_card = next(card for card in cards if card["kind"] == "vocabulary")

    assert vocab_card["title"] == "词汇深挖"
    assert vocab_card["body"] == ""
    assert "sustainable" not in vocab_card["body"]
    assert [item["word"] for item in vocab_card["vocabulary"]] == ["infrastructure", "resilience"]


def test_render_image_cards_to_files_creates_png_cards(tmp_path):
    from PIL import Image

    note = {
        "id": 7,
        "selected_title": "NVIDIA 如何成为 AI 基础设施公司",
        "body": "NVIDIA 用复杂（elaborate）的平台提升（elevate）AI 训练效率，并把生态传播（propagate）到更多场景。",
        "vocabulary": [
            {"word": "elaborate", "definition": "复杂的", "usage": "复杂（elaborate）"},
            {"word": "elevate", "definition": "提升", "usage": "提升（elevate）"},
        ],
        "cover_text": "NVIDIA 的 AI 基础设施故事",
        "hashtags": ["#NVIDIA", "#GRE词汇"],
        "cta": "收藏这张公司词汇卡",
    }
    batch = {
        "topic": "NVIDIA",
        "company_name": "NVIDIA",
        "company_profile": {"company_name": "NVIDIA", "logo_url": ""},
    }

    rendered = render_image_cards_to_files(note, batch, tmp_path, public_url_prefix="/generated/test")

    assert len(rendered) >= 3
    assert rendered[0]["image_url"].startswith("/generated/test/")
    for card in rendered:
        path = card["image_path"]
        assert path.endswith(".png")
        with Image.open(path) as image:
            assert image.size == (1080, 1440)


def test_render_hesai_company_cards_without_remote_image_does_not_crash(tmp_path):
    from PIL import Image

    profile = normalize_company_profile(
        company_name="HESAI",
        ticker="HSAI",
        provider_payloads=[search_company_profile("HESAI", ticker="HSAI")],
    )
    note = {
        "selected_title": "读 HESAI 学 4 个英文词",
        "body": (
            "HESAI 围绕激光雷达和三维感知（perception）展开业务，产品覆盖面向乘用车 ADAS 的 AT128、"
            "用于自动驾驶和机器人场景的 Pandar 系列，以及 ET/ETX、FT/FTX 等传感器。它把硬件、算法和制造能力"
            "整合成更完整的平台（platform），帮助车辆和机器人获得更稳定的环境感知能力（capability），"
            "也让 lidar 从实验室走向量产应用（application）。"
        ),
        "vocabulary": [
            {"word": "perception", "definition": "感知", "usage": "三维感知（perception）"},
            {"word": "platform", "definition": "平台", "usage": "完整的平台（platform）"},
            {"word": "capability", "definition": "能力", "usage": "环境感知能力（capability）"},
            {"word": "application", "definition": "应用", "usage": "量产应用（application）"},
        ],
        "cover_text": "",
        "hashtags": [],
        "cta": "收藏这张公司词汇卡",
    }
    batch = {
        "topic": "HESAI",
        "company_name": "HESAI",
        "company_ticker": "HSAI",
        "company_profile": {**profile, "image_assets": []},
    }

    rendered = render_image_cards_to_files(note, batch, tmp_path, public_url_prefix="/generated/test")

    assert len(rendered) >= 3
    with Image.open(rendered[0]["image_path"]) as image:
        assert image.size == (1080, 1440)
