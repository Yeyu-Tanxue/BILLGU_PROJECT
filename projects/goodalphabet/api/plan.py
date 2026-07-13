import json
from datetime import date
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from database import get_db
from auth import get_current_user
from api.common import DEFAULT_LIGHT_KEY, DEFAULT_LIGHT_URL, DEFAULT_LIGHT_MODEL
from wordbook_catalog import ensure_words_downloaded

router = APIRouter()


# ---- 词书（公开） ----

@router.get("/wordbooks")
async def list_wordbooks():
    db = get_db()
    rows = db.execute("SELECT * FROM wordbooks").fetchall()
    db.close()
    return rows


@router.get("/wordbooks/{book_id}/words")
async def list_words(book_id: int):
    db = get_db()
    rows = db.execute("SELECT * FROM words WHERE book_id=? ORDER BY seq", (book_id,)).fetchall()
    db.close()
    return rows


# ---- 计划 ----

class PlanCreate(BaseModel):
    book_id: int
    daily_count: int
    interests: list[str] = []


@router.post("/plan")
async def create_plan(plan: PlanCreate, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]

    try:
        if not ensure_words_downloaded(plan.book_id):
            raise HTTPException(500, "词书下载失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"词书加载出错：{e}")

    db = get_db()

    # 检查外键引用
    user_exists = db.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    book_exists = db.execute("SELECT id FROM wordbooks WHERE id=?", (plan.book_id,)).fetchone()
    if not user_exists:
        db.close()
        raise HTTPException(500, f"用户 {uid} 不存在")
    if not book_exists:
        db.close()
        raise HTTPException(500, f"词书 {plan.book_id} 不存在，请刷新页面重试")

    # 同一词书不允许重复创建
    existing = db.execute(
        "SELECT id FROM user_plan WHERE user_id=? AND book_id=? AND active=1", (uid, plan.book_id)
    ).fetchone()
    if existing:
        db.close()
        raise HTTPException(400, "该词书已有进行中的计划，请先在设置页切换或归档")

    today = date.today().isoformat()

    # 旧计划设为不活跃
    db.execute("UPDATE user_plan SET active=0 WHERE user_id=? AND active=1", (uid,))

    # 插入新计划
    db.execute(
        "INSERT INTO user_plan (user_id, book_id, daily_count, start_date, interests, active) VALUES (?,?,?,?,?,1)",
        (uid, plan.book_id, plan.daily_count, today, json.dumps(plan.interests, ensure_ascii=False)),
    )
    db.commit()

    # 获取新计划 id
    new_plan = db.execute(
        "SELECT id FROM user_plan WHERE user_id=? AND active=1", (uid,)
    ).fetchone()
    plan_id = new_plan["id"]

    words = db.execute(
        "SELECT id FROM words WHERE book_id=? ORDER BY seq", (plan.book_id,)
    ).fetchall()
    word_ids = [w["id"] for w in words]

    day = 1
    for i in range(0, len(word_ids), plan.daily_count):
        chunk = word_ids[i : i + plan.daily_count]
        db.execute(
            "INSERT INTO daily_lists (plan_id, user_id, day_number, word_ids) VALUES (?,?,?,?)",
            (plan_id, uid, day, json.dumps(chunk)),
        )
        day += 1

    db.commit()
    db.close()
    return {"total_days": day - 1}


@router.get("/plan")
async def get_plan(request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    plan = db.execute("SELECT * FROM user_plan WHERE user_id=? AND active=1", (uid,)).fetchone()
    if not plan:
        db.close()
        return None
    plan_id = plan["id"]
    total_lists = db.execute("SELECT COUNT(*) as c FROM daily_lists WHERE plan_id=?", (plan_id,)).fetchone()["c"]
    learned = db.execute("SELECT COUNT(*) as c FROM daily_lists WHERE plan_id=? AND learned=1", (plan_id,)).fetchone()["c"]
    book = db.execute("SELECT name FROM wordbooks WHERE id=?", (plan["book_id"],)).fetchone()
    db.close()
    return {**plan, "total_lists": total_lists, "learned_lists": learned, "book_name": book["name"] if book else ""}


class InterestsUpdate(BaseModel):
    interests: list[str] = []


@router.put("/plan/interests")
async def update_interests(req: InterestsUpdate, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    db.execute(
        "UPDATE user_plan SET interests=? WHERE user_id=? AND active=1",
        (json.dumps(req.interests, ensure_ascii=False), uid),
    )
    db.commit()
    db.close()
    return {"ok": True}


@router.get("/plan/history")
async def get_plan_history(request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    plans = db.execute(
        "SELECT up.*, wb.name as book_name FROM user_plan up "
        "JOIN wordbooks wb ON wb.id=up.book_id "
        "WHERE up.user_id=? AND up.active=0 ORDER BY up.id DESC", (uid,)
    ).fetchall()
    result = []
    for p in plans:
        total = db.execute("SELECT COUNT(*) as c FROM daily_lists WHERE plan_id=?", (p["id"],)).fetchone()["c"]
        learned = db.execute("SELECT COUNT(*) as c FROM daily_lists WHERE plan_id=? AND learned=1", (p["id"],)).fetchone()["c"]
        result.append({**p, "total_lists": total, "learned_lists": learned})
    db.close()
    return result


@router.post("/plan/{plan_id}/restore")
async def restore_plan(plan_id: int, request: Request):
    """恢复一个历史计划为当前活跃计划"""
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    plan = db.execute("SELECT * FROM user_plan WHERE id=? AND user_id=?", (plan_id, uid)).fetchone()
    if not plan:
        db.close()
        raise HTTPException(404, "计划不存在")
    # 当前活跃计划归档
    db.execute("UPDATE user_plan SET active=0 WHERE user_id=? AND active=1", (uid,))
    # 恢复目标计划
    db.execute("UPDATE user_plan SET active=1 WHERE id=?", (plan_id,))
    db.commit()
    db.close()
    return {"ok": True}


@router.delete("/plan/{plan_id}")
async def delete_plan(plan_id: int, request: Request):
    """删除一个计划及其所有关联数据"""
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    plan = db.execute("SELECT * FROM user_plan WHERE id=? AND user_id=?", (plan_id, uid)).fetchone()
    if not plan:
        db.close()
        raise HTTPException(404, "计划不存在")
    # 删除关联数据：review_sentences → reviews → daily_lists → user_plan
    list_ids = db.execute("SELECT id FROM daily_lists WHERE plan_id=?", (plan_id,)).fetchall()
    for l in list_ids:
        db.execute("DELETE FROM review_sentences WHERE list_id=?", (l["id"],))
        db.execute("DELETE FROM reviews WHERE list_id=?", (l["id"],))
    db.execute("DELETE FROM daily_lists WHERE plan_id=?", (plan_id,))
    db.execute("DELETE FROM user_plan WHERE id=?", (plan_id,))
    db.commit()
    db.close()
    return {"ok": True}


# ---- API 设置 ----

class ApiSettingsModel(BaseModel):
    primary_url: str = ""
    primary_key: str = ""
    primary_model: str = ""
    light_url: str = ""
    light_key: str = ""
    light_model: str = ""


@router.get("/api-settings")
async def get_api_settings_endpoint(request: Request):
    user = get_current_user(request)
    db = get_db()
    s = db.execute("SELECT * FROM api_settings WHERE user_id=?", (user["user_id"],)).fetchone()
    db.close()
    if not s:
        return {"primary_url": "", "primary_key": "", "primary_model": "",
                "light_url": "", "light_key": "", "light_model": ""}
    s = dict(s)
    for k in ("primary_key", "light_key"):
        v = s[k]
        if v and len(v) > 8:
            s[k] = v[:4] + "****" + v[-4:]
    return s


@router.post("/api-settings")
async def save_api_settings(req: ApiSettingsModel, request: Request):
    user = get_current_user(request)
    uid = user["user_id"]
    db = get_db()
    existing = db.execute("SELECT * FROM api_settings WHERE user_id=?", (uid,)).fetchone()

    pk = req.primary_key
    lk = req.light_key
    if existing:
        if "****" in pk:
            pk = existing["primary_key"]
        if "****" in lk:
            lk = existing["light_key"]

    if _is_pg():
        db.execute(
            "INSERT INTO api_settings (user_id, primary_url, primary_key, primary_model, light_url, light_key, light_model) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT (user_id) DO UPDATE SET primary_url=EXCLUDED.primary_url, primary_key=EXCLUDED.primary_key, "
            "primary_model=EXCLUDED.primary_model, light_url=EXCLUDED.light_url, light_key=EXCLUDED.light_key, light_model=EXCLUDED.light_model",
            (uid, req.primary_url, pk, req.primary_model, req.light_url, lk, req.light_model),
        )
    else:
        db.execute(
            "INSERT OR REPLACE INTO api_settings (user_id, primary_url, primary_key, primary_model, light_url, light_key, light_model) "
            "VALUES (?,?,?,?,?,?,?)",
            (uid, req.primary_url, pk, req.primary_model, req.light_url, lk, req.light_model),
        )
    db.commit()
    db.close()
    return {"ok": True}


@router.post("/api-settings/test")
async def test_api(req: ApiSettingsModel, request: Request, tier: str = "light"):
    user = get_current_user(request)
    try:
        if tier == "primary":
            url = req.primary_url or ""
            key = req.primary_key or ""
            model = req.primary_model or ""
        else:
            url = req.light_url or DEFAULT_LIGHT_URL
            key = req.light_key or DEFAULT_LIGHT_KEY
            model = req.light_model or DEFAULT_LIGHT_MODEL

        if not url or not key or not model:
            return {"ok": False, "error": "请填写完整的 URL、Key 和模型"}

        if "****" in key:
            db = get_db()
            settings = db.execute("SELECT * FROM api_settings WHERE user_id=?", (user["user_id"],)).fetchone()
            db.close()
            if settings:
                key = settings["primary_key"] if tier == "primary" else settings["light_key"]

        import urllib.request
        api_url = url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "回复OK两个字母"}],
            "max_tokens": 10, "temperature": 0.1,
        }).encode()
        req2 = urllib.request.Request(
            api_url, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        resp = json.loads(urllib.request.urlopen(req2, timeout=30).read())
        reply = resp["choices"][0]["message"]["content"].strip()[:50]
        return {"ok": True, "reply": reply}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}
