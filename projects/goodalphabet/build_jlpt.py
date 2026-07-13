"""从 kaikki 词典 + JLPT 分级表生成日语词书 JSON"""
import json
import os

KAIKKI_PATH = "D:/Download/kaikki.org-dictionary-Japanese.jsonl"
JLPT_PATH = "D:/Download/jlpt_levels.json"
OUTPUT_DIR = "D:/背单词工具/data"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 加载 JLPT 分级
with open(JLPT_PATH, encoding="utf-8") as f:
    jlpt = json.load(f)

# 从 kaikki 提取词条信息
kaikki = {}  # word -> {reading, definition}
for line in open(KAIKKI_PATH, encoding="utf-8"):
    d = json.loads(line)
    if d.get("pos") in ("romanization", "soft-redirect", "character", "syllable", "name"):
        continue
    word = d.get("word", "")
    if word not in jlpt or word in kaikki:
        continue

    # 提取读音
    reading = ""
    # 1. sounds 里的 other 字段通常是完整假名读音
    for s in d.get("sounds", []):
        candidate = s.get("other", "")
        if candidate and any(0x3040 <= ord(c) <= 0x30FF for c in candidate):
            reading = candidate
            break
    # 2. head_templates args
    if not reading:
        for ht in d.get("head_templates", []):
            for key in ["1", "2"]:
                candidate = ht.get("args", {}).get(key, "").replace("%", "")
                if candidate and any(0x3040 <= ord(c) <= 0x309F for c in candidate):
                    reading = candidate
                    break
            if reading:
                break

    # 提取英文释义
    glosses = []
    for s in d.get("senses", []):
        for g in s.get("glosses", []):
            if "synonym of" not in g.lower() and "alternative" not in g.lower():
                glosses.append(g)
                break
        if len(glosses) >= 2:
            break
    definition = "; ".join(glosses)

    if definition:
        kaikki[word] = {"reading": reading, "definition": definition}

print(f"JLPT 词表: {len(jlpt)} 词, kaikki 匹配: {len(kaikki)} 词")

# 按级别分组输出
BOOKS = {
    "jlpt_n5n4.json": {"levels": ["N5", "N4"], "name": "JLPT N5-N4 基础"},
    "jlpt_n3n2.json": {"levels": ["N3", "N2"], "name": "JLPT N3-N2 进阶"},
    "jlpt_n1.json": {"levels": ["N1"], "name": "JLPT N1 高级"},
}

for filename, info in BOOKS.items():
    words = []
    seq = 1
    for w, level in jlpt.items():
        if level in info["levels"] and w in kaikki:
            entry = kaikki[w]
            words.append({
                "word": w,
                "reading": entry["reading"],
                "definition": entry["definition"],
                "seq": seq,
            })
            seq += 1

    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=1)
    print(f"{info['name']}: {len(words)} 词 -> {path}")
