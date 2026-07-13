"""词书目录 — 启动时注册目录，用户选择时才下载"""

import os
import urllib.request
import zipfile
import io
import json
from database import get_db

_BASE_DIR = os.path.dirname(__file__)

CATALOG = [
    {"name": "新东方 GRE 词汇", "language": "en", "book_id": "GRE_3",
     "url": "https://raw.githubusercontent.com/kajweb/dict/master/book/1521164677706_GRE_3.zip"},
    {"name": "GRE 词汇", "language": "en", "book_id": "GRE_2",
     "url": "https://raw.githubusercontent.com/kajweb/dict/master/book/1521164637271_GRE_2.zip"},
    {"name": "新东方雅思词汇", "language": "en", "book_id": "IELTS_3",
     "url": "https://raw.githubusercontent.com/kajweb/dict/master/book/1521164666922_IELTS_3.zip"},
    {"name": "雅思词汇", "language": "en", "book_id": "IELTS_2",
     "url": "https://raw.githubusercontent.com/kajweb/dict/master/book/1521164657744_IELTS_2.zip"},
    {"name": "新东方 TOEFL 词汇", "language": "en", "book_id": "TOEFL_3",
     "url": "https://raw.githubusercontent.com/kajweb/dict/master/book/1521164667985_TOEFL_3.zip"},
    {"name": "TOEFL 词汇", "language": "en", "book_id": "TOEFL_2",
     "url": "https://raw.githubusercontent.com/kajweb/dict/master/book/1521164640451_TOEFL_2.zip"},
    {"name": "新东方四级词汇", "language": "en", "book_id": "CET4_3",
     "url": "https://raw.githubusercontent.com/kajweb/dict/master/book/1521164643060_CET4_3.zip"},
    {"name": "新东方六级词汇", "language": "en", "book_id": "CET6_3",
     "url": "https://raw.githubusercontent.com/kajweb/dict/master/book/1521164633851_CET6_3.zip"},
    {"name": "GRE 要你命3000", "language": "en", "book_id": "GRE_3000",
     "source": "local", "file": "gre3000.json"},
    {"name": "JLPT N5-N4 基础", "language": "ja", "book_id": "JLPT_N5N4",
     "source": "local", "file": "jlpt_n5n4.json"},
    {"name": "JLPT N3-N2 进阶", "language": "ja", "book_id": "JLPT_N3N2",
     "source": "local", "file": "jlpt_n3n2.json"},
    {"name": "JLPT N1 高级", "language": "ja", "book_id": "JLPT_N1",
     "source": "local", "file": "jlpt_n1.json"},
]

# book_id -> catalog entry 的映射
_CATALOG_MAP = {e["book_id"]: e for e in CATALOG}


def register_catalog():
    """启动时把词书目录写入数据库（不下载词汇数据）"""
    db = get_db()
    for entry in CATALOG:
        existing = db.execute("SELECT id FROM wordbooks WHERE name=?", (entry["name"],)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO wordbooks (name, language) VALUES (?,?)",
                (entry["name"], entry["language"]),
            )
    db.commit()
    db.close()


def _parse_definition(content: dict) -> str:
    word_content = content.get("word", {}).get("content", {})
    trans = word_content.get("trans", [])
    if trans:
        parts = []
        for t in trans:
            pos = t.get("pos", "")
            tran = t.get("tranCn", "") or t.get("tran", "")
            parts.append(f"{pos} {tran}" if pos else tran)
        return "；".join(parts)
    synos = word_content.get("syno", {}).get("synos", [])
    if synos:
        parts = []
        for s in synos:
            pos = s.get("pos", "")
            tran = s.get("tran", "")
            parts.append(f"{pos} {tran}" if pos else tran)
        return "；".join(parts)
    return ""


def ensure_words_downloaded(book_id: int) -> bool:
    """确保某本词书的单词已下载。返回 True 表示已就绪。"""
    db = get_db()
    count = db.execute("SELECT COUNT(*) as c FROM words WHERE book_id=?", (book_id,)).fetchone()["c"]
    if count > 0:
        db.close()
        return True

    # 找到对应的词书名和 catalog entry
    book = db.execute("SELECT name FROM wordbooks WHERE id=?", (book_id,)).fetchone()
    if not book:
        db.close()
        return False

    # 通过名字找 catalog entry
    entry = None
    for e in CATALOG:
        if e["name"] == book["name"]:
            entry = e
            break
    if not entry:
        db.close()
        return False

    # 本地词书：从 data/ 目录加载 JSON
    if entry.get("source") == "local":
        path = os.path.join(_BASE_DIR, "data", entry["file"])
        if not os.path.exists(path):
            db.close()
            return False
        words = json.loads(open(path, encoding="utf-8").read())
        for w in words:
            db.execute(
                "INSERT INTO words (book_id, word, phonetic, definition, seq) VALUES (?,?,?,?,?)",
                (book_id, w["word"], w.get("reading", ""), w["definition"], w["seq"]),
            )
        db.commit()
        db.close()
        print(f"  导入完成: {len(words)} 个单词")
        return True

    print(f"正在下载: {entry['name']}...")
    req = urllib.request.Request(entry["url"], headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=60).read()
    z = zipfile.ZipFile(io.BytesIO(data))

    json_file = [n for n in z.namelist() if n.endswith(".json")][0]
    lines = z.read(json_file).decode("utf-8").strip().split("\n")

    imported = 0
    for line in lines:
        try:
            w = json.loads(line)
        except json.JSONDecodeError:
            continue
        word = w.get("headWord", "")
        if not word:
            continue
        content = w.get("content", {})
        wc = content.get("word", {}).get("content", {})
        phonetic = wc.get("usphone", "") or wc.get("ukphone", "")
        definition = _parse_definition(content)
        seq = w.get("wordRank", imported + 1)
        db.execute(
            "INSERT INTO words (book_id, word, phonetic, definition, seq) VALUES (?,?,?,?,?)",
            (book_id, word, phonetic, definition, seq),
        )
        imported += 1

    db.commit()
    db.close()
    print(f"  导入完成: {imported} 个单词")
    return True
