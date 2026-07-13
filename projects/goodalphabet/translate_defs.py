"""批量翻译日语词书的英文释义为中文"""
import json, os, time

BASE_URL = "https://api.minimaxi.com/v1"
API_KEY = os.getenv("GOODALPHABET_TRANSLATE_API_KEY", "")
DATA_DIR = "D:/背单词工具/data"
BATCH = 50  # 每批翻译50个词

def translate_batch(entries):
    """调用 qwen 翻译一批词条"""
    import urllib.request
    lines = "\n".join(f"{i+1}. {e['word']} — {e['definition']}" for i, e in enumerate(entries))
    prompt = f"""请将以下日语单词的英文释义翻译成简洁的中文释义。每行格式：序号. 中文释义
不要输出单词本身，只输出序号和中文释义。保持简洁，每个不超过15个字。

{lines}"""

    body = json.dumps({
        "model": "auto",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception as e:
        error_msg = str(e)
        # 检查是否是token不足或配额错误
        if "token" in error_msg.lower() or "quota" in error_msg.lower() or "limit" in error_msg.lower():
            raise RuntimeError(f"Token 不足或配额已用尽: {error_msg}")
        raise RuntimeError(f"API 调用失败: {error_msg}")
    
    # 检查响应中的错误
    if "error" in resp:
        error_info = resp["error"]
        if isinstance(error_info, dict):
            error_msg = error_info.get("message", str(error_info))
        else:
            error_msg = str(error_info)
        if "token" in error_msg.lower() or "quota" in error_msg.lower():
            raise RuntimeError(f"Token 不足或配额已用尽: {error_msg}")
        raise RuntimeError(f"API 错误: {error_msg}")
    
    if "choices" not in resp or not resp["choices"]:
        raise RuntimeError(f"API 响应无效: {resp}")
    
    text = resp["choices"][0]["message"]["content"]

    # 解析结果
    results = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # 匹配 "1. xxx" 或 "1、xxx"
        for sep in [". ", "、", "．"]:
            if sep in line:
                parts = line.split(sep, 1)
                try:
                    idx = int(parts[0].strip()) - 1
                    results[idx] = parts[1].strip()
                except (ValueError, IndexError):
                    pass
                break
    return results


def process_file(filename):
    path = os.path.join(DATA_DIR, filename)
    words = json.load(open(path, encoding="utf-8"))
    print(f"\n处理 {filename}: {len(words)} 词", flush=True)

    for i in range(0, len(words), BATCH):
        batch = words[i:i+BATCH]
        try:
            translations = translate_batch(batch)
            for idx, cn in translations.items():
                if 0 <= idx < len(batch):
                    batch[idx]["definition"] = cn
            print(f"  {min(i+BATCH, len(words))}/{len(words)} done", flush=True)
        except RuntimeError as e:
            print(f"  批次 {i} 失败: {e}", flush=True)
            # 如果是token不足错误，停止处理
            if "token" in str(e).lower() or "quota" in str(e).lower():
                print(f"  错误：{e}。请检查 API 配额后重新运行。", flush=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(words, f, ensure_ascii=False, indent=1)
                raise
        except Exception as e:
            print(f"  批次 {i} 失败: {e}", flush=True)
        time.sleep(0.5)  # 避免限流

    with open(path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=1)
    print(f"  已保存 {filename}")


if __name__ == "__main__":
    if not API_KEY:
        print("错误: 请设置 API_KEY")
        exit(1)
    for f in ["jlpt_n5n4.json", "jlpt_n3n2.json", "jlpt_n1.json"]:
        process_file(f)
    print("\n全部完成!")
