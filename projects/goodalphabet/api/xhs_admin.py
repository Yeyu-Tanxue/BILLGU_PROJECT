from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.admin import _require_admin
from api.common import call_ai
from api.xhs_factory import (
    DEFAULT_COMPANY_VOCAB_POOL,
    GENERATED_ROOT,
    build_company_generation_prompt,
    build_image_cards,
    build_company_retry_prompt,
    build_generation_prompt,
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
from database import get_db
from wordbook_catalog import ensure_words_downloaded

router = APIRouter()

NOTE_STATUSES = {"draft", "needs_edit", "approved", "published", "rejected"}

XHS_COMPANY_SEED_WORDS = {
    "innovative",
    "sophisticated",
    "robust",
    "dominant",
    "ubiquitous",
    "pioneer",
    "proliferate",
    "proficient",
    "ascendant",
    "transfigure",
    "hasten",
}


class BatchCreateRequest(BaseModel):
    mode: str = "scene"
    wordbook_id: int
    scene: str
    topic: str = Field(min_length=1)
    style: str
    note_count: int = Field(default=10, ge=1, le=20)
    words_per_note: int = Field(default=5, ge=1, le=20)
    company_name: str | None = None
    company_ticker: str | None = None
    company_logo_url: str | None = None
    company_source_language: str = "zh"
    manual_company_profile: str | None = None
    angle: str | None = None
    matched_vocabulary: list[dict[str, Any]] | None = None


class CompanyPreviewRequest(BaseModel):
    wordbook_id: int
    company_name: str = Field(min_length=1)
    company_ticker: str | None = None
    company_logo_url: str | None = None
    company_source_language: str = "zh"
    manual_company_profile: str | None = None
    angle: str = "company_overview"
    note_count: int = Field(default=1, ge=1, le=20)
    words_per_note: int = Field(default=5, ge=1, le=20)


class CompanyBatchCreateRequest(BaseModel):
    company: str = Field(min_length=1)
    note_count: int = Field(default=3, ge=1, le=12)
    search_enabled: bool = True


class NoteUpdateRequest(BaseModel):
    status: str | None = None
    selected_title: str | None = None
    body: str | None = None
    cover_text: str | None = None
    image_prompt: str | None = None
    cta: str | None = None
    published_url: str | None = None
    published_at: str | None = None
    operator_notes: str | None = None
    views: int | None = None
    likes: int | None = None
    favorites: int | None = None
    comments: int | None = None
    profile_visits: int | None = None
    product_visits: int | None = None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _insert_returning_id(db: Any, sql: str, params: tuple[Any, ...]) -> int:
    row = db.execute(f"{sql} RETURNING id", params).fetchone()
    return int(row["id"])


def _serialize_batch(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row.get("created_at"),
        "created_by": row.get("created_by"),
        "wordbook_id": row.get("wordbook_id"),
        "language": row.get("language"),
        "mode": row.get("mode") or "scene",
        "scene": row.get("scene"),
        "topic": row.get("topic"),
        "style": row.get("style"),
        "note_count": row.get("note_count"),
        "words_per_note": row.get("words_per_note"),
        "company_name": row.get("company_name") or "",
        "company_ticker": row.get("company_ticker") or "",
        "company_angle": row.get("company_angle") or "",
        "company_profile": _json_loads(row.get("company_profile_json"), {}),
        "matched_vocabulary": _json_loads(row.get("matched_vocabulary_json"), []),
        "source_urls": _json_loads(row.get("source_urls_json"), []),
        "source_warnings": _json_loads(row.get("source_warnings_json"), []),
        "status": row.get("status"),
        "error_message": row.get("error_message"),
    }


def _serialize_note(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "status": row.get("status"),
        "selected_title": row.get("selected_title"),
        "titles": _json_loads(row.get("titles_json"), []),
        "body": row.get("body"),
        "vocabulary": _json_loads(row.get("vocabulary_json"), []),
        "cover_text": row.get("cover_text"),
        "image_prompt": row.get("image_prompt"),
        "hashtags": _json_loads(row.get("hashtags_json"), []),
        "cta": row.get("cta"),
        "quality_notes": _json_loads(row.get("quality_notes_json"), []),
        "risk_flags": _json_loads(row.get("risk_flags_json"), []),
        "visual_header": _json_loads(row.get("visual_header_json"), {}),
        "company_facts_used": _json_loads(row.get("company_facts_used_json"), []),
        "fact_check_notes": _json_loads(row.get("fact_check_notes_json"), []),
        "word_context_map": _json_loads(row.get("word_context_map_json"), []),
        "published_url": row.get("published_url"),
        "published_at": row.get("published_at"),
        "views": row.get("views"),
        "likes": row.get("likes"),
        "favorites": row.get("favorites"),
        "comments": row.get("comments"),
        "profile_visits": row.get("profile_visits"),
        "product_visits": row.get("product_visits"),
        "operator_notes": row.get("operator_notes"),
    }


def _get_wordbook(db: Any, wordbook_id: int) -> dict[str, Any]:
    row = db.execute(
        "SELECT id, name, language FROM wordbooks WHERE id=?",
        (wordbook_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Wordbook not found")
    return dict(row)


def _seed_xhs_local_word_sample(wordbook_id: int) -> bool:
    db = get_db()
    try:
        count = db.execute("SELECT COUNT(*) AS c FROM words WHERE book_id=?", (wordbook_id,)).fetchone()["c"]
        book = db.execute("SELECT name, language FROM wordbooks WHERE id=?", (wordbook_id,)).fetchone()
        if count > 0 and (not book or book["language"] != "en" or "3000" not in book["name"]):
            return True
        if not book or book["language"] != "en" or "3000" not in book["name"]:
            return False
        path = Path(__file__).resolve().parents[1] / "data" / "gre3000.json"
        if not path.exists():
            return False
        words = json.loads(path.read_text(encoding="utf-8"))
        selected_words = words[:240]
        selected_words.extend(item for item in words if item["word"].lower() in XHS_COMPANY_SEED_WORDS)
        existing_words = {
            row["word"].lower()
            for row in db.execute("SELECT word FROM words WHERE book_id=?", (wordbook_id,)).fetchall()
        }
        rows = [
            (wordbook_id, item["word"], item.get("reading", ""), item["definition"], item["seq"])
            for item in selected_words
            if item["word"].lower() not in existing_words
        ]
        if rows:
            db.executemany(
                "INSERT INTO words (book_id, word, phonetic, definition, seq) VALUES (?,?,?,?,?)",
                rows,
            )
            db.commit()
        return True
    finally:
        db.close()


def _ensure_wordbook_ready(wordbook_id: int) -> None:
    if _seed_xhs_local_word_sample(wordbook_id):
        return
    try:
        ready = ensure_words_downloaded(wordbook_id)
    except Exception as exc:
        raise ValueError("Could not load words for the selected wordbook. Try another wordbook or import it first.") from exc
    if not ready:
        raise ValueError("No words available for the selected wordbook.")


def _build_company_preview(db: Any, payload: CompanyPreviewRequest | BatchCreateRequest) -> dict[str, Any]:
    company_name = payload.company_name or payload.topic
    searched_profile = search_company_profile(company_name, ticker=payload.company_ticker or "")
    profile = normalize_company_profile(
        company_name=company_name,
        manual_company_profile=payload.manual_company_profile or "",
        ticker=payload.company_ticker or "",
        source_language=payload.company_source_language,
        logo_url=payload.company_logo_url or "",
        provider_payloads=[searched_profile],
    )
    _ensure_wordbook_ready(payload.wordbook_id)
    words = sample_words(db, payload.wordbook_id, DEFAULT_COMPANY_VOCAB_POOL)
    selected_vocabulary = getattr(payload, "matched_vocabulary", None)
    vocabulary_limit = min(max(payload.note_count * payload.words_per_note, payload.words_per_note, 12), 30)
    matched = selected_vocabulary or match_company_vocabulary(
        profile,
        words,
        limit=vocabulary_limit,
        angle=payload.angle or "company_overview",
    )
    return {
        "company_profile": profile,
        "matched_vocabulary": matched,
        "source_urls": profile.get("source_urls", []),
        "source_warnings": profile.get("source_warnings", []),
    }


def _parse_valid_company_generation(
    *,
    raw: str,
    requested_count: int,
    company_name: str,
    words_per_note: int = 5,
) -> dict[str, Any]:
    parsed = parse_company_generation_response(raw, requested_count=requested_count)
    min_vocabulary_count = max(3, min(int(words_per_note), 10))
    validate_company_notes(
        parsed["notes"],
        company_name=company_name,
        min_vocabulary_count=min_vocabulary_count,
        min_body_chars=120,
    )
    return parsed


@router.get("/admin/xhs/options")
async def xhs_options(request: Request):
    _require_admin(request)
    db = get_db()
    try:
        return get_options(db)
    finally:
        db.close()


@router.post("/admin/xhs/company-preview")
async def preview_xhs_company(payload: CompanyPreviewRequest, request: Request):
    _require_admin(request)
    db = get_db()
    try:
        _get_wordbook(db, payload.wordbook_id)
        return _build_company_preview(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        db.close()


@router.post("/admin/xhs/company-batches")
async def create_company_xhs_batch(payload: CompanyBatchCreateRequest, request: Request):
    admin = _require_admin(request)
    db = get_db()
    try:
        wordbook = db.execute("SELECT id, language FROM wordbooks ORDER BY id LIMIT 1").fetchone()
        if not wordbook:
            raise HTTPException(status_code=400, detail="No wordbook is available.")
        searched = search_company_profile(payload.company) if payload.search_enabled else {
            "company": payload.company,
            "summary": f"{payload.company} 的公司或产品资料由运营人员补充。",
        }
        profile = normalize_company_profile(
            company_name=payload.company,
            manual_company_profile="" if payload.search_enabled else searched.get("summary") or "",
            provider_payloads=[searched] if payload.search_enabled else [],
        )
        _ensure_wordbook_ready(int(wordbook["id"]))
        words = sample_words(db, int(wordbook["id"]), DEFAULT_COMPANY_VOCAB_POOL)
        matched = match_company_vocabulary(profile, words, limit=18, angle="company_overview")
        prompt = build_company_generation_prompt(
            profile=profile,
            style="profile",
            angle="company_overview",
            note_count=payload.note_count,
            words_per_note=6,
            language=wordbook["language"],
            words=matched,
        )
    finally:
        db.close()

    try:
        raw = call_ai(prompt, admin.get("auth0_user_id") or admin.get("email") or "admin", max_tokens=5000)
        try:
            parsed = _parse_valid_company_generation(
                raw=raw,
                requested_count=payload.note_count,
                company_name=profile["company_name"],
                words_per_note=6,
            )
        except Exception as first_validation_error:
            retry_prompt = build_company_retry_prompt(
                original_prompt=prompt,
                validation_error=str(first_validation_error),
                rejected_response=raw,
            )
            raw = call_ai(retry_prompt, admin.get("auth0_user_id") or admin.get("email") or "admin", max_tokens=5000)
            parsed = _parse_valid_company_generation(
                raw=raw,
                requested_count=payload.note_count,
                company_name=profile["company_name"],
                words_per_note=6,
            )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(exc) or "Company Xiaohongshu generation failed") from exc

    return {
        "company_profile": {
            "company": profile["company_name"],
            "summary": profile["source_summary"],
            "search_provider": "manual",
            "logo_url": profile.get("logo_url", ""),
            "industries": profile.get("industries", []),
        },
        "matched_vocabulary": matched,
        "operation_plan": parsed.get("operation_plan") or {
            "positioning": "客观公司/产品介绍图文，正文用中文自然标注英文词汇",
            "weekly_calendar": ["科技公司", "消费品牌", "航空出行", "产品功能"],
            "content_series": ["公司资料卡", "产品资料卡"],
            "title_formulas": ["{company}：一句话看懂它的业务", "{company} 的行业关键词"],
            "review_checklist": ["核对公司事实", "检查中文（英文）格式", "避免投资建议"],
        },
        "notes": parsed["notes"],
        "samples": parsed.get("samples", []),
        "warning": parsed.get("warning"),
    }


@router.post("/admin/xhs/batches")
async def create_xhs_batch(payload: BatchCreateRequest, request: Request):
    admin = _require_admin(request)
    db = get_db()
    try:
        wordbook = _get_wordbook(db, payload.wordbook_id)
        company_preview: dict[str, Any] = {
            "company_profile": {},
            "matched_vocabulary": [],
            "source_urls": [],
            "source_warnings": [],
        }
        if payload.mode == "company_profile":
            company_preview = _build_company_preview(db, payload)
            prompt = build_company_generation_prompt(
                profile=company_preview["company_profile"],
                style=payload.style,
                angle=payload.angle or "company_overview",
                note_count=payload.note_count,
                words_per_note=payload.words_per_note,
                language=wordbook["language"],
                words=company_preview["matched_vocabulary"],
            )
        else:
            _ensure_wordbook_ready(payload.wordbook_id)
            words = sample_words(
                db,
                wordbook_id=payload.wordbook_id,
                count=payload.note_count * payload.words_per_note,
            )
            prompt = build_generation_prompt(
                scene=payload.scene,
                topic=payload.topic.strip(),
                style=payload.style,
                note_count=payload.note_count,
                words_per_note=payload.words_per_note,
                language=wordbook["language"],
                words=words,
            )
        batch_id = _insert_returning_id(
            db,
            """
            INSERT INTO xhs_note_batches (
                created_by, wordbook_id, language, mode, scene, topic, style,
                note_count, words_per_note, generation_prompt, company_name,
                company_ticker, company_angle, company_profile_json,
                matched_vocabulary_json, source_urls_json, source_warnings_json, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                admin.get("email"),
                payload.wordbook_id,
                wordbook["language"],
                payload.mode,
                payload.scene,
                payload.topic.strip(),
                payload.style,
                payload.note_count,
                payload.words_per_note,
                prompt,
                payload.company_name or "",
                payload.company_ticker or "",
                payload.angle or "",
                _json_dumps(company_preview["company_profile"]),
                _json_dumps(company_preview["matched_vocabulary"]),
                _json_dumps(company_preview["source_urls"]),
                _json_dumps(company_preview["source_warnings"]),
                "generating",
            ),
        )
        try:
            raw = call_ai(prompt, admin.get("auth0_user_id") or admin.get("email") or "admin", max_tokens=4000)
            if payload.mode == "company_profile":
                company_name = company_preview["company_profile"].get("company_name") or payload.company_name or payload.topic
                try:
                    parsed = _parse_valid_company_generation(
                        raw=raw,
                        requested_count=payload.note_count,
                        company_name=company_name,
                        words_per_note=payload.words_per_note,
                    )
                except Exception as first_validation_error:
                    retry_prompt = build_company_retry_prompt(
                        original_prompt=prompt,
                        validation_error=str(first_validation_error),
                        rejected_response=raw,
                    )
                    raw = call_ai(retry_prompt, admin.get("auth0_user_id") or admin.get("email") or "admin", max_tokens=4000)
                    parsed = _parse_valid_company_generation(
                        raw=raw,
                        requested_count=payload.note_count,
                        company_name=company_name,
                        words_per_note=payload.words_per_note,
                    )
            else:
                parsed = parse_generation_response(raw, requested_count=payload.note_count)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                error_detail = str(exc.detail) if exc.detail else "Xiaohongshu note generation failed"
                status_code = exc.status_code
            else:
                error_detail = str(exc) or "Xiaohongshu note generation failed"
                status_code = 500
            db.execute(
                "UPDATE xhs_note_batches SET status=?, error_message=? WHERE id=?",
                ("failed", error_detail, batch_id),
            )
            db.commit()
            raise HTTPException(status_code=status_code, detail=error_detail) from exc

        note_ids: list[int] = []
        for note in parsed["notes"]:
            note_id = _insert_returning_id(
                db,
                """
                INSERT INTO xhs_notes (
                    batch_id, status, selected_title, titles_json, body, vocabulary_json,
                    cover_text, image_prompt, hashtags_json, cta, quality_notes_json, risk_flags_json,
                    visual_header_json, company_facts_used_json, fact_check_notes_json, word_context_map_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    batch_id,
                    "draft",
                    note["selected_title"],
                    _json_dumps(note["titles"]),
                    note["body"],
                    _json_dumps(note["vocabulary"]),
                    note["cover_text"],
                    note["image_prompt"],
                    _json_dumps(note["hashtags"]),
                    note["cta"],
                    _json_dumps(note["quality_notes"]),
                    _json_dumps(note["risk_flags"]),
                    _json_dumps(note.get("visual_header", {})),
                    _json_dumps(note.get("company_facts_used", [])),
                    _json_dumps(note.get("fact_check_notes", [])),
                    _json_dumps(note.get("word_context_map", [])),
                ),
            )
            note_ids.append(note_id)

        db.execute(
            "UPDATE xhs_note_batches SET status=?, error_message=? WHERE id=?",
            ("completed", parsed.get("warning"), batch_id),
        )
        db.commit()

        batch = db.execute("SELECT * FROM xhs_note_batches WHERE id=?", (batch_id,)).fetchone()
        notes = []
        if note_ids:
            placeholders = ",".join(["?"] * len(note_ids))
            notes = db.execute(
                f"SELECT * FROM xhs_notes WHERE id IN ({placeholders}) ORDER BY id",
                tuple(note_ids),
            ).fetchall()
        return {"batch": _serialize_batch(batch), "notes": [_serialize_note(note) for note in notes]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        db.close()


@router.get("/admin/xhs/batches")
async def list_xhs_batches(request: Request, limit: int = 50):
    _require_admin(request)
    safe_limit = min(max(limit, 1), 100)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM xhs_note_batches ORDER BY id DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
        return {"batches": [_serialize_batch(row) for row in rows]}
    finally:
        db.close()


@router.get("/admin/xhs/batches/{batch_id}")
async def get_xhs_batch(batch_id: int, request: Request):
    _require_admin(request)
    db = get_db()
    try:
        batch = db.execute("SELECT * FROM xhs_note_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        notes = db.execute(
            "SELECT * FROM xhs_notes WHERE batch_id=? ORDER BY id",
            (batch_id,),
        ).fetchall()
        return {"batch": _serialize_batch(batch), "notes": [_serialize_note(note) for note in notes]}
    finally:
        db.close()


@router.patch("/admin/xhs/notes/{note_id}")
async def update_xhs_note(note_id: int, payload: NoteUpdateRequest, request: Request):
    _require_admin(request)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in NOTE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid note status")

    try:
        metrics = validate_metrics_update(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    text_fields = {
        "status",
        "selected_title",
        "body",
        "cover_text",
        "image_prompt",
        "cta",
        "published_url",
        "published_at",
        "operator_notes",
    }
    updates: list[str] = []
    params: list[Any] = []
    for key in text_fields:
        if key in data:
            updates.append(f"{key}=?")
            params.append(data[key])
    for key, value in metrics.items():
        updates.append(f"{key}=?")
        params.append(value)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at=?")
    params.append(datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    params.append(note_id)
    db = get_db()
    try:
        db.execute(
            f"UPDATE xhs_notes SET {', '.join(updates)} WHERE id=?",
            tuple(params),
        )
        db.commit()
        row = db.execute("SELECT * FROM xhs_notes WHERE id=?", (note_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Note not found")
        return _serialize_note(row)
    finally:
        db.close()


@router.get("/admin/xhs/notes/{note_id}/image-cards")
async def get_xhs_note_image_cards(note_id: int, request: Request):
    _require_admin(request)
    db = get_db()
    try:
        note = db.execute("SELECT * FROM xhs_notes WHERE id=?", (note_id,)).fetchone()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        batch = db.execute(
            "SELECT * FROM xhs_note_batches WHERE id=?",
            (note["batch_id"],),
        ).fetchone()
        serialized_note = _serialize_note(note)
        serialized_batch = _serialize_batch(batch) if batch else None
        return {"cards": build_image_cards(serialized_note, serialized_batch)}
    finally:
        db.close()


@router.post("/admin/xhs/notes/{note_id}/image-cards/rendered")
async def render_xhs_note_image_cards(note_id: int, request: Request):
    _require_admin(request)
    db = get_db()
    try:
        note = db.execute("SELECT * FROM xhs_notes WHERE id=?", (note_id,)).fetchone()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        batch = db.execute(
            "SELECT * FROM xhs_note_batches WHERE id=?",
            (note["batch_id"],),
        ).fetchone()
        serialized_note = _serialize_note(note)
        serialized_batch = _serialize_batch(batch) if batch else None
        output_dir = GENERATED_ROOT / "xhs" / f"note_{note_id}"
        cards = render_image_cards_to_files(
            serialized_note,
            serialized_batch,
            output_dir,
            public_url_prefix=f"/generated/xhs/note_{note_id}",
        )
        return {"cards": cards}
    finally:
        db.close()
