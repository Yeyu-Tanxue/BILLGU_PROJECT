import json
import re
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from database import get_db
from auth import get_current_user
from api.common import call_ai

router = APIRouter()

NEXT_ROUND_DELTA = {1: 3, 2: 7, 3: 15, 4: 30}
ROUND_NAMES = {1: "翻译练习", 2: "填空练习", 3: "造句练习", 4: "综合复习", 5: "综合复习"}


def _get_active_plan(db, uid):
    return db.execute("SELECT * FROM user_plan WHERE user_id=? AND active=1", (uid,)).fetchone()


def _build_item(s, exercise_type):
    item = {"id": s["id"], "word": s["word"], "definition": s["definition"]}
    if exercise_type == "translate":
        item.update(type="translate", prompt=s["sentence"], answer=s["translation"])
    elif exercise_type == "fill":
        item.update(type="fill", prompt=s["translation"],
                    blank_sentence=s["sentence"].replace(s["blank_word"], "______"), answer=s["blank_word"])
    elif exercise_type == "write":
        item.update(type="write", prompt=s["translation"], answer=s["sentence"], hint_word=s["blank_word"])
    elif exercise_type == "word_def":
        item.update(type="word_def", prompt=s["word"], answer=s["definition"])
    elif exercise_type == "def_word":
        item.update(type="def_word", prompt=s["definition"], answer=s["word"])
    return item


def _get_sentences(db, list_id, auth0_user_id):
    rows = db.execute(
        "SELECT rs.*, w.word, w.definition FROM review_sentences rs "
        "JOIN words w ON w.id=rs.word_id WHERE rs.list_id=?", (list_id,)
    ).fetchall()
    if not rows:
        dl = db.execute("SELECT story, word_ids, user_id FROM daily_lists WHERE id=?", (list_id,)).fetchone()
        if dl and dl["story"]:
            _extract_and_translate(db, list_id, dl["story"], json.loads(dl["word_ids"]), auth0_user_id)
            rows = db.execute(
                "SELECT rs.*, w.word, w.definition FROM review_sentences rs "
                "JOIN words w ON w.id=rs.word_id WHERE rs.list_id=?", (list_id,)
            ).fetchall()
    seen = set()
    sentences = []
    for s in rows:
        if s["sentence"] not in seen:
            seen.add(s["sentence"])
            sentences.append(s)
    return sentences


def _extract_and_translate(db, list_id, story, word_ids, auth0_user_id):
    """正则提取句子 + 轻量API翻译"""
    placeholders = ",".join(["?"] * len(word_ids))
    words = db.execute(
        f"SELECT id, word, definition FROM words WHERE id IN ({placeholders})", word_ids
    ).fetchall()
    clean = re.sub(r'^#+\s*.*$', '', story, flags=re.MULTILINE)
    plain = clean.replace("**", "")
    sents = re.split(r'(?<=[.!?。！？])\s+', plain)
    sents = [s.strip() for s in sents if s.strip()]
    word_map = {w['word'].lower(): w for w in words}
    extracted = []
    matched = set()
    for sent in sents:
        sent_lower = sent.lower()
        for wl, w in word_map.items():
            if wl not in matched and re.search(r'\b' + re.escape(wl) + r'\b', sent_lower):
                extracted.append((w['id'], sent, w['word']))
                matched.add(wl)
    if not extracted:
        return
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
    except Exception:
        pass
    for i, (wid, sent, wname) in enumerate(extracted):
        db.execute(
            "INSERT INTO review_sentences (list_id, word_id, sentence, translation, blank_word) VALUES (?,?,?,?,?)",
            (list_id, wid, sent, translations[i], wname),
        )
    db.commit()


def _get_language(db, uid):
    plan = _get_active_plan(db, uid)
    if plan:
        lang = db.execute("SELECT language FROM wordbooks WHERE id=?", (plan["book_id"],)).fetchone()
        if lang:
            return lang["language"]
    return "en"


def _build_exercise_items(sentences, rnd):
    items = []
    for s in sentences:
        if rnd == 1:
            items.append(_build_item(s, "translate"))
        elif rnd == 2:
            items.append(_build_item(s, "fill"))
        elif rnd == 3:
            items.append(_build_item(s, "write"))
        else:
            items.append(_build_item(s, "write"))

    if rnd >= 4:
        import random
        all_types = ["translate", "fill", "write", "word_def", "def_word"]
        items = [_build_item(sentences[i], all_types[i % len(all_types)]) for i in range(len(sentences))]
        random.shuffle(items)
    return items


# ---- 复习列表 ----

@router.get("/reviews/today")
async def get_today_reviews(request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    today = date.today().isoformat()
    rows = db.execute(
        "SELECT r.id as review_id, r.list_id, r.round, dl.day_number FROM reviews r "
        "JOIN daily_lists dl ON dl.id=r.list_id "
        "WHERE r.review_date<=? AND r.completed=0 AND r.user_id=?",
        (today, uid),
    ).fetchall()
    db.close()
    return rows


@router.post("/reviews/{review_id}/done")
async def mark_review_done(review_id: int, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    review = db.execute("SELECT * FROM reviews WHERE id=? AND user_id=?", (review_id, uid)).fetchone()
    if not review:
        db.close()
        raise HTTPException(404, "复习不存在")

    today = date.today()
    db.execute(
        "UPDATE reviews SET completed=1, completed_date=? WHERE id=?",
        (today.isoformat(), review_id),
    )

    current_round = review["round"]
    if current_round in NEXT_ROUND_DELTA:
        next_round = current_round + 1
        delta = NEXT_ROUND_DELTA[current_round]
        next_date = (today + timedelta(days=delta)).isoformat()
        db.execute(
            "INSERT INTO reviews (list_id, user_id, review_date, round) VALUES (?,?,?,?)",
            (review["list_id"], uid, next_date, next_round),
        )

    db.commit()
    db.close()
    return {"ok": True}


# ---- 练习引擎 ----

@router.get("/reviews/{review_id}/exercise")
async def get_exercise(review_id: int, request: Request, offset: int = 0, limit: int = 0):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    review = db.execute("SELECT * FROM reviews WHERE id=? AND user_id=?", (review_id, uid)).fetchone()
    if not review:
        db.close()
        raise HTTPException(404, "复习不存在")

    sentences = _get_sentences(db, review["list_id"], user["auth0_user_id"])
    language = _get_language(db, uid)
    db.close()

    items = _build_exercise_items(sentences, review["round"])
    total = len(items)
    if limit > 0:
        items = items[offset:offset + limit]
    elif offset > 0:
        items = items[offset:]
    return {
        "review_id": review_id, "round": review["round"],
        "round_name": ROUND_NAMES.get(review["round"], "复习"),
        "language": language, "items": items, "total": total,
    }


# ---- 自主练习 ----

@router.get("/practice/lists")
async def practice_lists(request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    plan = _get_active_plan(db, uid)
    if not plan:
        db.close()
        return []
    rows = db.execute(
        "SELECT dl.id, dl.day_number, "
        "CASE WHEN dl.story IS NOT NULL AND dl.story != '' THEN 1 ELSE 0 END as has_sentences "
        "FROM daily_lists dl WHERE dl.plan_id=? AND dl.learned=1 ORDER BY dl.day_number",
        (plan["id"],),
    ).fetchall()
    db.close()
    return rows


@router.get("/practice/{list_id}/exercise")
async def practice_exercise(list_id: int, request: Request, round: int = 1, offset: int = 0, limit: int = 0):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    sentences = _get_sentences(db, list_id, user["auth0_user_id"])
    language = _get_language(db, uid)
    db.close()

    if not sentences:
        return {"items": [], "round": round, "round_name": "练习", "language": language, "total": 0}

    items = _build_exercise_items(sentences, round)
    total = len(items)
    if limit > 0:
        items = items[offset:offset + limit]
    elif offset > 0:
        items = items[offset:]
    return {"round": round, "round_name": ROUND_NAMES.get(round, "练习"), "language": language, "items": items, "total": total}


# ---- 评分 ----

class ScoreRequest(BaseModel):
    user_answer: str
    correct_answer: str
    exercise_type: str
    language: str = "en"


@router.post("/reviews/score")
async def score_answer(req: ScoreRequest, request: Request):
    user = get_current_user(request)

    if req.exercise_type in ("fill", "def_word"):
        passed = req.user_answer.strip().lower() == req.correct_answer.strip().lower()
        return {"passed": passed, "feedback": "正确！" if passed else f"正确答案：{req.correct_answer}"}

    if req.exercise_type == "word_def":
        prompt = f"""判断用户写的单词释义是否语义正确。
参考释义：{req.correct_answer}
用户释义：{req.user_answer}
只回复JSON：{{"passed":true/false,"feedback":"简短反馈"}}"""
    elif req.exercise_type == "translate":
        prompt = f"""判断用户的中文翻译是否语义正确。
参考翻译：{req.correct_answer}
用户翻译：{req.user_answer}
只回复JSON：{{"passed":true/false,"feedback":"简短反馈"}}"""
    else:
        lang_name = "日语" if req.language == "ja" else "英语"
        prompt = f"""判断用户写的{lang_name}句子是否语义正确且语法基本通顺。
参考句子：{req.correct_answer}
用户句子：{req.user_answer}
只回复JSON：{{"passed":true/false,"feedback":"简短反馈"}}"""

    try:
        raw = call_ai(prompt, user["auth0_user_id"], max_tokens=200)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        print(f"[评分] AI返回无法解析JSON: {raw[:200]}")
    except Exception as e:
        print(f"[评分] 异常: {e}")
    return {"passed": False, "feedback": "评分失败，请重试"}


# ---- 提示 ----

class HintRequest(BaseModel):
    sentence: str
    word: str


@router.post("/reviews/hint")
async def get_hint(req: HintRequest):
    first_letter = req.word[0] + "..." if req.word else ""
    return {"first_letter": first_letter, "length": len(req.word)}


# ---- 日历 ----

@router.get("/reviews/calendar")
async def get_calendar(year: int, month: int, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    prefix = f"{year}-{month:02d}"
    rows = db.execute(
        "SELECT review_date, round, completed FROM reviews WHERE review_date LIKE ? AND user_id=?",
        (prefix + "%", uid),
    ).fetchall()
    db.close()

    cal = {}
    for r in rows:
        d = r["review_date"]
        if d not in cal:
            cal[d] = {"date": d, "total": 0, "done": 0}
        cal[d]["total"] += 1
        if r["completed"]:
            cal[d]["done"] += 1
    return list(cal.values())


@router.get("/reviews/by-date")
async def get_reviews_by_date(date: str, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    rows = db.execute(
        "SELECT r.id as review_id, r.list_id, r.round, r.completed, dl.day_number "
        "FROM reviews r JOIN daily_lists dl ON dl.id=r.list_id "
        "WHERE r.review_date=? AND r.user_id=? ORDER BY r.round",
        (date, uid),
    ).fetchall()
    db.close()
    return rows


# ---- 进度 ----

@router.get("/progress")
async def get_progress(request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    plan = _get_active_plan(db, uid)
    if not plan:
        db.close()
        return None

    plan_id = plan["id"]
    total_words = db.execute(
        "SELECT COUNT(*) as c FROM words WHERE book_id=?", (plan["book_id"],)
    ).fetchone()["c"]
    total_lists = db.execute("SELECT COUNT(*) as c FROM daily_lists WHERE plan_id=?", (plan_id,)).fetchone()["c"]
    learned_lists = db.execute("SELECT COUNT(*) as c FROM daily_lists WHERE plan_id=? AND learned=1", (plan_id,)).fetchone()["c"]
    pending_reviews = db.execute(
        "SELECT COUNT(*) as c FROM reviews WHERE review_date<=? AND completed=0 AND user_id=?",
        (date.today().isoformat(), uid),
    ).fetchone()["c"]

    book_name = db.execute("SELECT name FROM wordbooks WHERE id=?", (plan["book_id"],)).fetchone()
    book_name = book_name["name"] if book_name else ""

    # 所有计划进度
    all_plans_rows = db.execute(
        "SELECT up.id, up.book_id, up.daily_count, up.start_date, up.active, wb.name as book_name "
        "FROM user_plan up JOIN wordbooks wb ON wb.id=up.book_id "
        "WHERE up.user_id=? ORDER BY up.active DESC, up.id DESC", (uid,)
    ).fetchall()
    all_plans = []
    for p in all_plans_rows:
        tl = db.execute("SELECT COUNT(*) as c FROM daily_lists WHERE plan_id=?", (p["id"],)).fetchone()["c"]
        ll = db.execute("SELECT COUNT(*) as c FROM daily_lists WHERE plan_id=? AND learned=1", (p["id"],)).fetchone()["c"]
        all_plans.append({
            "book_name": p["book_name"], "daily_count": p["daily_count"],
            "start_date": p["start_date"], "active": p["active"],
            "total_lists": tl, "learned_lists": ll,
        })

    # 总已学单词（跨所有计划）
    total_learned_words_all = 0
    for p in all_plans:
        total_learned_words_all += p["learned_lists"] * p["daily_count"]

    # 总学习天数
    total_days = db.execute(
        "SELECT COUNT(DISTINCT day_number || '-' || plan_id) as c FROM daily_lists WHERE user_id=? AND learned=1", (uid,)
    ).fetchone()["c"]

    db.close()
    return {
        "total_words": total_words, "total_lists": total_lists,
        "learned_lists": learned_lists, "learned_words": learned_lists * plan["daily_count"],
        "pending_reviews": pending_reviews,
        "book_name": book_name, "daily_count": plan["daily_count"],
        "start_date": plan["start_date"],
        "all_plans": all_plans, "total_learned_words_all": total_learned_words_all,
        "total_study_days": total_days,
    }
