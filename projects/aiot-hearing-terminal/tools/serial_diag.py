"""
串口诊断：监听 N 秒，原始字节存盘 + 行分类统计。
用来确认 ESP32 到底在往串口吐什么格式，定位 PC 端解析问题。

用法：
    python tools/serial_diag.py --port COM7 --seconds 20
"""

import argparse
import sys
import time
from pathlib import Path

import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--seconds", type=float, default=20)
    args = ap.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"监听 {args.port} @ {args.baud}，{args.seconds}s ...")
    s = serial.Serial(args.port, args.baud, timeout=0.2)

    t0 = time.time()
    buf = bytearray()
    while time.time() - t0 < args.seconds:
        chunk = s.read(s.in_waiting or 1)
        if chunk:
            buf += chunk
    s.close()

    dump = Path(__file__).resolve().parent.parent / "serial_dump.bin"
    dump.write_bytes(buf)
    print(f"\n收到 {len(buf)} 字节，已存到 {dump}")

    # 去掉 ANSI 颜色码后按行分类
    txt = buf.decode("utf-8", errors="replace")
    # 简单剥离 ESC[ ... m 颜色码
    import re
    txt_clean = re.sub(r"\x1b\[[0-9;]*m", "", txt)

    lines = txt_clean.splitlines()
    counts = {
        "CLIP_START": 0, "CLIP_END": 0, "FRAME ": 0,
        "FRAME_SKIP": 0, "FRAME_ERR": 0,
        "countdown": 0, "log_other": 0, "empty": 0,
    }
    samples = {}
    for ln in lines:
        st = ln.strip()
        if st == "":
            counts["empty"] += 1
        elif ln.startswith("CLIP_START"):
            counts["CLIP_START"] += 1
            samples.setdefault("CLIP_START", ln)
        elif ln.startswith("CLIP_END"):
            counts["CLIP_END"] += 1
            samples.setdefault("CLIP_END", ln)
        elif ln.startswith("FRAME_SKIP"):
            counts["FRAME_SKIP"] += 1
            samples.setdefault("FRAME_SKIP", ln)
        elif ln.startswith("FRAME_ERR"):
            counts["FRAME_ERR"] += 1
            samples.setdefault("FRAME_ERR", ln)
        elif ln.startswith("FRAME "):
            counts["FRAME "] += 1
            samples.setdefault("FRAME ", ln[:80] + " ...(截断)")
        elif "..." in ln and ("capture" in ln):
            counts["countdown"] += 1
        else:
            counts["log_other"] += 1
            if counts["log_other"] <= 8:
                samples.setdefault(f"log_{counts['log_other']}", ln[:120])

    print("\n=== 行分类统计 ===")
    for k, v in counts.items():
        print(f"  {k:14s}: {v}")

    print("\n=== 各类型首行样本 ===")
    for k, v in samples.items():
        print(f"  [{k}] {v}")


if __name__ == "__main__":
    main()
