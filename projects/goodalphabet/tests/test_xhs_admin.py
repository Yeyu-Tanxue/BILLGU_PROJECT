import json
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.admin as admin_api
import database
import main


def table_columns(db_path, table_name):
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    finally:
        conn.close()


def test_init_db_creates_xhs_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "vocab.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(database, "DATABASE_URL", "")

    database.init_db()

    batch_columns = table_columns(db_path, "xhs_note_batches")
    note_columns = table_columns(db_path, "xhs_notes")

    assert {"id", "wordbook_id", "scene", "topic", "status", "error_message"} <= batch_columns
    assert {
        "id",
        "batch_id",
        "status",
        "selected_title",
        "body",
        "published_url",
        "views",
        "likes",
        "favorites",
        "comments",
    } <= note_columns


@pytest.fixture()
def admin_client(tmp_path, monkeypatch):
    db_path = tmp_path / "vocab.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(database, "DATABASE_URL", "")
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        admin_api,
        "get_current_user",
        lambda _request: {"email": "admin@example.com", "auth0_user_id": "auth0|admin", "user_id": 1},
    )

    database.init_db()
    db = database.get_db()
    db.execute("INSERT INTO wordbooks (name, language) VALUES (?,?)", ("GRE", "en"))
    wordbook_id = db.execute("SELECT id FROM wordbooks WHERE name=?", ("GRE",)).fetchone()["id"]
    db.execute(
        "INSERT INTO words (book_id, word, phonetic, definition, seq) VALUES (?,?,?,?,?)",
        (wordbook_id, "resilient", "", "able to recover", 1),
    )
    db.execute(
        "INSERT INTO words (book_id, word, phonetic, definition, seq) VALUES (?,?,?,?,?)",
        (wordbook_id, "meticulous", "", "very careful", 2),
    )
    db.commit()
    db.close()

    return TestClient(main.app)


def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_xhs_options_returns_wordbooks_and_defaults(admin_client):
    response = admin_client.get("/api/admin/xhs/options", headers=auth_headers())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["wordbooks"][0]["name"] == "GRE"
    assert payload["wordbooks"][0]["word_count"] == 2
    assert payload["defaults"]["note_count"] == 1


def test_company_preview_loads_empty_wordbook_before_sampling(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    db = database.get_db()
    db.execute("INSERT INTO wordbooks (name, language) VALUES (?,?)", ("IELTS", "en"))
    wordbook_id = db.execute("SELECT id FROM wordbooks WHERE name=?", ("IELTS",)).fetchone()["id"]
    db.commit()
    db.close()

    calls = []

    def fake_ensure(book_id):
        calls.append(book_id)
        db = database.get_db()
        db.execute(
            "INSERT INTO words (book_id, word, phonetic, definition, seq) VALUES (?,?,?,?,?)",
            (book_id, "infrastructure", "", "基础设施", 1),
        )
        db.execute(
            "INSERT INTO words (book_id, word, phonetic, definition, seq) VALUES (?,?,?,?,?)",
            (book_id, "innovation", "", "创新", 2),
        )
        db.commit()
        db.close()
        return True

    monkeypatch.setattr(xhs_admin, "ensure_words_downloaded", fake_ensure)

    response = admin_client.post(
        "/api/admin/xhs/company-preview",
        headers=auth_headers(),
        json={
            "wordbook_id": wordbook_id,
            "company_name": "波音",
            "manual_company_profile": "波音是一家航空航天公司，业务包括飞机制造、航空服务和基础设施支持。",
            "angle": "product_innovation",
            "note_count": 1,
            "words_per_note": 2,
        },
    )

    assert response.status_code == 200, response.text
    assert calls == [wordbook_id]
    db = database.get_db()
    imported_count = db.execute("SELECT COUNT(*) AS c FROM words WHERE book_id=?", (wordbook_id,)).fetchone()["c"]
    db.close()
    assert imported_count == 2


def test_xhs_batch_generation_saves_notes(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    def fake_generate(prompt, auth0_user_id, max_tokens=4000):
        assert "interview panic" in prompt
        assert auth0_user_id == "auth0|admin"
        return """
        {
          "notes": [
            {
              "titles": ["GRE words I finally remembered", "Interview panic words", "Stop memorizing lists"],
              "body": "I remembered resilient and meticulous through one interview story.",
              "vocabulary": [{"word": "resilient", "definition": "able to recover", "usage": "bounce back"}],
              "cover_text": "2 GRE words from one story",
              "image_prompt": "clean desk, interview notes",
              "hashtags": ["#GRE", "#背单词"],
              "cta": "I used AI to turn the list into a short story.",
              "quality_notes": ["natural vocabulary"],
              "risk_flags": []
            }
          ]
        }
        """

    monkeypatch.setattr(xhs_admin, "call_ai", fake_generate)

    options = admin_client.get("/api/admin/xhs/options", headers=auth_headers()).json()
    wordbook_id = options["wordbooks"][0]["id"]
    response = admin_client.post(
        "/api/admin/xhs/batches",
        headers=auth_headers(),
        json={
            "wordbook_id": wordbook_id,
            "scene": "workplace",
            "topic": "interview panic",
            "style": "story",
            "note_count": 1,
            "words_per_note": 2,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["batch"]["topic"] == "interview panic"
    assert payload["notes"][0]["selected_title"] == "GRE words I finally remembered"
    assert payload["notes"][0]["hashtags"] == ["#GRE", "#背单词"]


def test_xhs_batch_generation_returns_ai_error_detail(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    monkeypatch.setattr(
        xhs_admin,
        "call_ai",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("AI returned invalid JSON")),
    )

    wordbook_id = admin_client.get("/api/admin/xhs/options", headers=auth_headers()).json()["wordbooks"][0]["id"]
    response = admin_client.post(
        "/api/admin/xhs/batches",
        headers=auth_headers(),
        json={
            "wordbook_id": wordbook_id,
            "scene": "workplace",
            "topic": "interview panic",
            "style": "story",
            "note_count": 1,
            "words_per_note": 2,
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "AI returned invalid JSON"


def test_xhs_batch_generation_preserves_ai_http_status(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    monkeypatch.setattr(
        xhs_admin,
        "call_ai",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HTTPException(status_code=402, detail="Token 不足")),
    )

    wordbook_id = admin_client.get("/api/admin/xhs/options", headers=auth_headers()).json()["wordbooks"][0]["id"]
    response = admin_client.post(
        "/api/admin/xhs/batches",
        headers=auth_headers(),
        json={
            "wordbook_id": wordbook_id,
            "scene": "workplace",
            "topic": "interview panic",
            "style": "story",
            "note_count": 1,
            "words_per_note": 2,
        },
    )

    assert response.status_code == 402
    assert response.json()["detail"] == "Token 不足"


def test_company_profile_batch_rejects_goodalphabet_ad_output(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    monkeypatch.setattr(
        xhs_admin,
        "call_ai",
        lambda *_args, **_kwargs: json.dumps(
            {
                "notes": [
                    {
                        "titles": ["GOODALPHABET: Your AI-Powered Vocabulary Learning Companion"],
                        "body": "GOODALPHABET是一款人工智能词汇学习产品。它能有效提升（elevate）你的词汇量。",
                        "vocabulary": [{"word": "elevate", "definition": "提升"}],
                        "cover_text": "AI 背词工具",
                        "image_prompt": "vocabulary learning app",
                        "hashtags": ["#背单词"],
                        "cta": "快来试试",
                        "quality_notes": [],
                        "risk_flags": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    wordbook_id = admin_client.get("/api/admin/xhs/options", headers=auth_headers()).json()["wordbooks"][0]["id"]
    response = admin_client.post(
        "/api/admin/xhs/batches",
        headers=auth_headers(),
        json={
            "mode": "company_profile",
            "wordbook_id": wordbook_id,
            "scene": "company_profile",
            "topic": "NVIDIA",
            "company_name": "NVIDIA",
            "company_ticker": "NVDA",
            "style": "story",
            "angle": "technology_product",
            "note_count": 1,
            "words_per_note": 1,
        },
    )

    assert response.status_code == 500
    assert "GOODALPHABET" in response.json()["detail"]

    db = database.get_db()
    saved_notes = db.execute("SELECT COUNT(*) AS c FROM xhs_notes").fetchone()["c"]
    failed_batches = db.execute("SELECT COUNT(*) AS c FROM xhs_note_batches WHERE status='failed'").fetchone()["c"]
    db.close()
    assert saved_notes == 0
    assert failed_batches == 1


def test_company_profile_batch_retries_bad_company_output(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    calls = []

    def fake_ai(prompt, *_args, **_kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps(
                {
                    "notes": [
                        {
                            "titles": ["GOODALPHABET: Your AI-Powered Vocabulary Learning Companion"],
                            "body": "GOODALPHABET是一款人工智能词汇学习产品。它能有效提升（elevate）你的词汇量。",
                            "vocabulary": [{"word": "elevate", "definition": "提升"}],
                            "cover_text": "AI 背词工具",
                            "image_prompt": "vocabulary learning app",
                            "hashtags": ["#背单词"],
                            "cta": "快来试试",
                            "quality_notes": [],
                            "risk_flags": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        assert "Rewrite the rejected company/product Xiaohongshu note" in prompt
        assert "GOODALPHABET" in prompt
        return json.dumps(
            {
                "notes": [
                    {
                        "titles": ["NVIDIA 如何把 GPU 变成 AI 基础设施"],
                        "body": "NVIDIA 从图形处理器起家，后来用 CUDA 和数据中心平台提升（elevate）AI 训练效率。它把复杂（elaborate）的软硬件生态传播（propagate）到云服务、科研和自动驾驶场景，也让开发者更容易验证（document）模型性能、支持（advocate）新的 AI 应用，并用不懈（unflagging）的产品迭代维持技术影响力。",
                        "vocabulary": [
                            {"word": "elevate", "definition": "提升", "usage": "提升（elevate）"},
                            {"word": "elaborate", "definition": "复杂的", "usage": "复杂（elaborate）"},
                            {"word": "propagate", "definition": "传播", "usage": "传播（propagate）"},
                            {"word": "document", "definition": "验证", "usage": "验证（document）"},
                            {"word": "advocate", "definition": "支持", "usage": "支持（advocate）"},
                            {"word": "unflagging", "definition": "不懈的", "usage": "不懈（unflagging）"},
                        ],
                        "cover_text": "NVIDIA 的 AI 基础设施故事",
                        "image_prompt": "objective NVIDIA AI infrastructure xhs card",
                        "hashtags": ["#NVIDIA", "#GRE词汇"],
                        "cta": "收藏这张公司词汇卡",
                        "quality_notes": [],
                        "risk_flags": [],
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(xhs_admin, "call_ai", fake_ai)

    wordbook_id = admin_client.get("/api/admin/xhs/options", headers=auth_headers()).json()["wordbooks"][0]["id"]
    response = admin_client.post(
        "/api/admin/xhs/batches",
        headers=auth_headers(),
        json={
            "mode": "company_profile",
            "wordbook_id": wordbook_id,
            "scene": "company_profile",
            "topic": "NVIDIA",
            "company_name": "NVIDIA",
            "company_ticker": "NVDA",
            "style": "story",
            "angle": "technology_product",
            "note_count": 1,
            "words_per_note": 3,
        },
    )

    assert response.status_code == 200, response.text
    assert len(calls) == 2
    payload = response.json()
    assert payload["notes"][0]["selected_title"].startswith("NVIDIA")
    assert "GOODALPHABET" not in payload["notes"][0]["body"]
    assert "提升（elevate）" in payload["notes"][0]["body"]


def test_xhs_batch_list_detail_and_note_update(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    monkeypatch.setattr(
        xhs_admin,
        "call_ai",
        lambda *_args, **_kwargs: '{"notes":[{"titles":["Title"],"body":"Body","vocabulary":[],"cover_text":"Cover","image_prompt":"Image","hashtags":["#tag"],"cta":"CTA","quality_notes":[],"risk_flags":[]}]}',
    )
    wordbook_id = admin_client.get("/api/admin/xhs/options", headers=auth_headers()).json()["wordbooks"][0]["id"]
    created = admin_client.post(
        "/api/admin/xhs/batches",
        headers=auth_headers(),
        json={
            "wordbook_id": wordbook_id,
            "scene": "exam_anxiety",
            "topic": "last week sprint",
            "style": "list",
            "note_count": 1,
            "words_per_note": 1,
        },
    ).json()

    batch_id = created["batch"]["id"]
    note_id = created["notes"][0]["id"]

    list_response = admin_client.get("/api/admin/xhs/batches", headers=auth_headers())
    detail_response = admin_client.get(f"/api/admin/xhs/batches/{batch_id}", headers=auth_headers())
    patch_response = admin_client.patch(
        f"/api/admin/xhs/notes/{note_id}",
        headers=auth_headers(),
        json={
            "status": "published",
            "selected_title": "Updated title",
            "published_url": "https://www.xiaohongshu.com/explore/test",
            "views": 123,
            "likes": 10,
            "favorites": 5,
            "comments": 2,
        },
    )

    assert list_response.status_code == 200
    assert list_response.json()["batches"][0]["id"] == batch_id
    assert detail_response.status_code == 200
    assert detail_response.json()["notes"][0]["id"] == note_id
    assert patch_response.status_code == 200
    updated = patch_response.json()
    assert updated["status"] == "published"
    assert updated["selected_title"] == "Updated title"
    assert updated["views"] == 123


def test_xhs_note_image_cards_api(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    monkeypatch.setattr(
        xhs_admin,
        "call_ai",
        lambda *_args, **_kwargs: '{"notes":[{"titles":["Title"],"body":"Body with resilient.","vocabulary":[{"word":"resilient","definition":"有韧性的","usage":"bounce back"}],"cover_text":"Cover","image_prompt":"Image","hashtags":["#tag"],"cta":"AI 故事背词","quality_notes":[],"risk_flags":[]}]}',
    )
    wordbook_id = admin_client.get("/api/admin/xhs/options", headers=auth_headers()).json()["wordbooks"][0]["id"]
    created = admin_client.post(
        "/api/admin/xhs/batches",
        headers=auth_headers(),
        json={
            "wordbook_id": wordbook_id,
            "scene": "exam_anxiety",
            "topic": "last week sprint",
            "style": "list",
            "note_count": 1,
            "words_per_note": 1,
        },
    ).json()

    note_id = created["notes"][0]["id"]
    response = admin_client.get(f"/api/admin/xhs/notes/{note_id}/image-cards", headers=auth_headers())

    assert response.status_code == 200
    cards = response.json()["cards"]
    assert cards[0]["kind"] == "cover"
    assert cards[1]["kind"] == "vocabulary"
    assert cards[1]["vocabulary"][0]["definition"] == "有韧性的"
    assert cards[-1]["kind"] == "cta"

    monkeypatch.setattr(
        xhs_admin,
        "render_image_cards_to_files",
        lambda _note, _batch, _output_dir, public_url_prefix="": [
            {"kind": "cover", "image_url": f"{public_url_prefix}/card_1_cover.png", "image_path": "mock.png"}
        ],
    )
    rendered_response = admin_client.post(f"/api/admin/xhs/notes/{note_id}/image-cards/rendered", headers=auth_headers())
    assert rendered_response.status_code == 200
    assert rendered_response.json()["cards"][0]["image_url"].endswith("/card_1_cover.png")


def test_company_xhs_batch_generation_returns_profile_plan_notes_and_cards(admin_client, monkeypatch):
    import api.xhs_admin as xhs_admin

    def fake_profile(company):
        assert company == "宝洁"
        return {
            "company": "宝洁",
            "summary": "宝洁是一家消费品公司，产品覆盖洗护、口腔护理和清洁。",
            "keywords": ["消费品", "产品", "清洁", "品牌"],
            "sources": [{"title": "P&G overview", "url": "https://example.com/pg"}],
            "search_provider": "test",
        }

    def fake_ai(prompt, auth0_user_id, max_tokens=5000):
        assert "中文小红书图文笔记" in prompt
        assert "宝洁" in prompt
        assert auth0_user_id == "auth0|admin"
        return json.dumps(
            {
                "company": "宝洁",
                "company_profile": {"summary": "宝洁是一家消费品公司。"},
                "matched_vocabulary": [{"hanzi": "公司", "pinyin": "gōng sī", "meaning": "company"}],
                "operation_plan": {
                    "positioning": "用公司介绍自然学习中文商业词",
                    "weekly_calendar": ["周一 公司历史", "周三 产品词汇"],
                    "content_series": ["公司故事", "产品功能"],
                    "title_formulas": ["从宝洁学会{word}"],
                    "review_checklist": ["事实有来源", "词汇自然出现"],
                },
                "notes": [
                    {
                        "titles": ["从宝洁学中文商业词"],
                        "body": "宝洁是一家消费品公司（company），产品覆盖洗护、口腔护理和家庭清洁等日常场景。它通过品牌（brand）组合和产品（product）创新影响消费者选择，也需要用清晰（fluent）的表达介绍功能、用证据（document）支撑卖点，并在不同市场传播（propagate）稳定的护理理念。",
                        "vocabulary": [
                            {"word": "company", "definition": "公司", "usage": "公司（company）"},
                            {"word": "brand", "definition": "品牌", "usage": "品牌（brand）"},
                            {"word": "product", "definition": "产品", "usage": "产品（product）"},
                            {"word": "fluent", "definition": "清晰流畅的", "usage": "清晰（fluent）"},
                            {"word": "document", "definition": "用证据证明", "usage": "证据（document）"},
                            {"word": "propagate", "definition": "传播", "usage": "传播（propagate）"},
                        ],
                        "cover_text": "宝洁公司词汇",
                        "image_prompt": "xhs clean business vocabulary cards",
                        "image_cards": [{"kind": "cover", "title": "宝洁公司词汇"}],
                        "hashtags": ["#中文学习", "#小红书图文"],
                        "cta": "关注我，用公司故事学中文",
                        "quality_notes": ["自然引出词汇"],
                        "risk_flags": [],
                    }
                ],
                "samples": [{"company": "宝洁", "topic": "产品影响"}],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(xhs_admin, "search_company_profile", fake_profile)
    monkeypatch.setattr(xhs_admin, "call_ai", fake_ai)

    response = admin_client.post(
        "/api/admin/xhs/company-batches",
        headers=auth_headers(),
        json={"company": "宝洁", "level": "HSK3", "note_count": 1, "search_enabled": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["company_profile"]["company"] == "宝洁"
    assert payload["operation_plan"]["positioning"] == "用公司介绍自然学习中文商业词"
    assert payload["notes"][0]["selected_title"] == "从宝洁学中文商业词"
    assert payload["notes"][0]["image_cards"][0]["title"] == "宝洁公司词汇"
    assert payload["samples"][0]["topic"] == "产品影响"
