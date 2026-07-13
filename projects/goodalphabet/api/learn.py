import json
import os
import re
import threading
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from database import get_db
from auth import get_current_user
from api.common import call_ai, call_ai_stream

router = APIRouter()


def _get_active_plan(db, uid):
    return db.execute("SELECT * FROM user_plan WHERE user_id=? AND active=1", (uid,)).fetchone()


@router.get("/today")
async def get_today(request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    plan = _get_active_plan(db, uid)
    if not plan:
        db.close()
        raise HTTPException(404, "请先创建学习计划")

    plan_id = plan["id"]
    dl = db.execute(
        "SELECT * FROM daily_lists WHERE plan_id=? AND learned=0 ORDER BY day_number LIMIT 1", (plan_id,)
    ).fetchone()
    if not dl:
        db.close()
        return {"finished": True}

    word_ids = json.loads(dl["word_ids"])
    placeholders = ",".join(["?"] * len(word_ids))
    words = db.execute(
        f"SELECT * FROM words WHERE id IN ({placeholders}) ORDER BY seq", word_ids
    ).fetchall()

    language = db.execute(
        "SELECT language FROM wordbooks WHERE id=?", (plan["book_id"],)
    ).fetchone()["language"]

    db.close()
    return {
        "list_id": dl["id"], "day_number": dl["day_number"],
        "story": dl["story"], "words": words, "language": language,
    }


@router.get("/lists/learned")
async def get_learned_lists(request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    plan = _get_active_plan(db, uid)
    if not plan:
        db.close()
        return []
    rows = db.execute(
        "SELECT id, day_number FROM daily_lists WHERE plan_id=? AND learned=1 ORDER BY day_number", (plan["id"],)
    ).fetchall()
    db.close()
    return rows


@router.get("/lists/{list_id}")
async def get_list(list_id: int, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    dl = db.execute("SELECT * FROM daily_lists WHERE id=? AND user_id=?", (list_id, uid)).fetchone()
    if not dl:
        db.close()
        raise HTTPException(404, "课程不存在")
    plan = _get_active_plan(db, uid)
    word_ids = json.loads(dl["word_ids"])
    placeholders = ",".join(["?"] * len(word_ids))
    words = db.execute(
        f"SELECT * FROM words WHERE id IN ({placeholders}) ORDER BY seq", word_ids
    ).fetchall()
    language = db.execute(
        "SELECT language FROM wordbooks WHERE id=?", (plan["book_id"],)
    ).fetchone()["language"]
    db.close()
    return {
        "list_id": dl["id"], "day_number": dl["day_number"],
        "story": dl["story"], "words": words, "language": language,
    }


@router.post("/today/{list_id}/done")
async def mark_done(list_id: int, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    db.execute("UPDATE daily_lists SET learned=1 WHERE id=? AND user_id=?", (list_id, uid))

    today = date.today()
    review_date = (today + timedelta(days=1)).isoformat()
    db.execute(
        "INSERT INTO reviews (list_id, user_id, review_date, round) VALUES (?,?,?,1)",
        (list_id, uid, review_date),
    )
    db.commit()
    db.close()
    return {"ok": True}


@router.post("/generate-story/{list_id}")
async def generate_story(list_id: int, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    dl = db.execute("SELECT * FROM daily_lists WHERE id=? AND user_id=?", (list_id, uid)).fetchone()
    if not dl:
        db.close()
        raise HTTPException(404, "List not found")

    word_ids = json.loads(dl["word_ids"])
    placeholders = ",".join(["?"] * len(word_ids))
    words = db.execute(
        f"SELECT id, word, definition FROM words WHERE id IN ({placeholders})", word_ids
    ).fetchall()
    words = [dict(w) for w in words]

    plan = _get_active_plan(db, uid)
    lang = "en"
    if plan:
        lang_row = db.execute("SELECT language FROM wordbooks WHERE id=?", (plan["book_id"],)).fetchone()
        if lang_row:
            lang = lang_row["language"]

    interests = json.loads(plan["interests"]) if plan and plan.get("interests") else []
    db.close()

    interest_hint = ("话题方向：" + "、".join(interests) + "\n") if interests else ""
    word_list = "\n".join(f"- {w['word']}: {w['definition']}" for w in words)

    if lang == "ja":
        ja_words = "、".join(w['word'] for w in words)
        topic_ja = f"テーマ：{'、'.join(interests)}\n" if interests else ""
        prompt = f"""以下の日本語の単語をすべて自然に使って、面白い日本語の短編ストーリー（300〜500字程度）を書いてください。

ルール：
- ストーリーは必ず日本語で書くこと（英語は使わないでください）
- 各単語が初めて登場する際は **太字** にすること（例：**食べる**）
- ストーリーは面白く、ストーリー性があること
{topic_ja}
単語：{ja_words}"""
    else:
        prompt = f"""请根据以下单词列表，写一篇有趣的英文短文（根据单词列表单词数来确定短文词数，不要超过1000词）。
要求：
1. 必须自然地使用所有给定单词
2. 短文要有趣、有情节
3. 用词难度适中，除了给定单词外其他词汇不要太难
4. 在短文中，给定单词首次出现时用 **加粗** 标记
{interest_hint}
单词列表：
{word_list}"""

    auth0_uid = user["auth0_user_id"]
    word_names = [w['word'] for w in words]
    word_ids_list = [w['id'] for w in words]

    def stream_gen():
        chunks = []
        error = False
        try:
            for chunk in call_ai_stream(prompt, auth0_uid, max_tokens=2000):
                chunks.append(chunk)
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            error = True
            error_msg = str(e)
            yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"

        if not error and chunks:
            story = "".join(chunks)
            save_db = get_db()
            save_db.execute("UPDATE daily_lists SET story=? WHERE id=?", (story, list_id))
            save_db.commit()
            save_db.close()
            threading.Thread(
                target=_bg_extract_and_translate,
                args=(list_id, story, word_names, word_ids_list, auth0_uid),
                daemon=True,
            ).start()

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _bg_extract_and_translate(list_id, story, word_names, word_ids_list, auth0_user_id):
    """后台：正则提取句子，轻量API翻译，存入DB"""
    db = get_db()
    # 正则提取句子
    clean = re.sub(r'^#+\s*.*$', '', story, flags=re.MULTILINE)
    plain = clean.replace("**", "")
    sents = re.split(r'(?<=[.!?。！？])\s+', plain)
    sents = [s.strip() for s in sents if s.strip()]
    word_map = {name.lower(): wid for name, wid in zip(word_names, word_ids_list)}
    extracted = []  # [(word_id, sentence, word_name)]
    matched = set()
    for sent in sents:
        sent_lower = sent.lower()
        for wl, wid in word_map.items():
            if wl not in matched and re.search(r'\b' + re.escape(wl) + r'\b', sent_lower):
                extracted.append((wid, sent, wl))
                matched.add(wl)
    if not extracted:
        db.close()
        return
    # 轻量API批量翻译
    sentences_text = "\n".join(f"{i+1}. {e[1]}" for i, e in enumerate(extracted))
    prompt = f"将以下英文句子逐句翻译成中文，每行一句，只输出翻译结果，用数字编号对应：\n{sentences_text}"
    translations = [""] * len(extracted)
    try:
        raw = call_ai(prompt, auth0_user_id, max_tokens=2000)
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        for line in lines:
            m = re.match(r'(\d+)[.、:：\s]\s*(.*)', line)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(translations):
                    translations[idx] = m.group(2)
    except Exception as e:
        # 记录翻译失败，但不中断存储句子的过程
        error_msg = str(e)
        if "token" in error_msg.lower() or "quota" in error_msg.lower():
            print(f"[后台翻译] List {list_id}: Token 不足或配额已用尽 - {error_msg}", flush=True)
        else:
            print(f"[后台翻译] List {list_id} 翻译失败: {error_msg}", flush=True)
    
    for i, (wid, sent, wname) in enumerate(extracted):
        db.execute(
            "INSERT INTO review_sentences (list_id, word_id, sentence, translation, blank_word) VALUES (?,?,?,?,?)",
            (list_id, wid, sent, translations[i], wname),
        )
    db.commit()
    db.close()


# ---- TTS 代理（公开） ----

@router.get("/tts")
async def tts_proxy(text: str, lang: str = "en"):
    from fastapi.responses import Response
    import edge_tts, tempfile

    voice = "ja-JP-NanamiNeural" if lang == "ja" else "en-GB-SoniaNeural"
    try:
        tmp = tempfile.mktemp(suffix=".mp3")
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(tmp)
        with open(tmp, "rb") as f:
            data = f.read()
        os.remove(tmp)
        return Response(content=data, media_type="audio/mpeg")
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, str(e))


# ---- 逐行翻译 ----

class TranslateRequest(BaseModel):
    texts: list[str]
    source_lang: str = "en"


@router.post("/translate-lines")
async def translate_lines(req: TranslateRequest, request: Request):
    user = get_current_user(request)
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(req.texts))
    lang_name = "日语" if req.source_lang == "ja" else "英语"
    prompt = f"将以下{lang_name}段落逐行翻译为中文，保持编号格式，只输出翻译结果：\n{numbered}"

    try:
        raw = call_ai(prompt, user["auth0_user_id"], max_tokens=2000)
    except Exception as e:
        error_msg = str(e)
        raise HTTPException(status_code=500, detail=f"翻译失败: {error_msg}")

    lines = raw.strip().split("\n")
    translations = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^\d+[.、]\s*", "", line)
        translations.append(cleaned)

    while len(translations) < len(req.texts):
        translations.append("")

    return {"translations": translations[:len(req.texts)]}


@router.post("/translate-lines/stream")
async def translate_lines_stream(req: TranslateRequest, request: Request):
    user = get_current_user(request)
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(req.texts))
    lang_name = "日语" if req.source_lang == "ja" else "英语"
    prompt = f"将以下{lang_name}段落逐行翻译为中文，保持编号格式，只输出翻译结果：\n{numbered}"

    def stream_gen():
        error = False
        try:
            for chunk in call_ai_stream(prompt, user["auth0_user_id"], max_tokens=2000):
                payload = json.dumps({"chunk": chunk}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as e:
            error = True
            error_msg = str(e)
            yield f"data: {json.dumps({'error': f'翻译失败: {error_msg}'}, ensure_ascii=False)}\n\n"
        
        if not error:
            yield "data: [DONE]\n\n"

    return StreamingResponse(stream_gen(), media_type="text/event-stream")
