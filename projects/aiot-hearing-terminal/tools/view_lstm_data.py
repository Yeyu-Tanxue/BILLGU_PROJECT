"""
view_lstm_data.py —— 回放查看采集的 LSTM 手语数据（骨架动画）
================================================================
把某个词某一组的 45 帧手部关键点还原成骨架，用 OpenCV 动画播放。
数据格式见 hand_features.py：每只手 66 维 = 63(21点相对手腕) + 3(手腕绝对)，
双手 132 维。还原某点坐标 = 相对 + 手腕绝对 → 回到 MediaPipe 原始归一化坐标。

用法（在 E:\\ESP-S3 根目录，split 环境）：
  python tools/view_lstm_data.py 我
  python tools/view_lstm_data.py 我 -i 3            # 看第 3 组
  python tools/view_lstm_data.py 5 --aug            # 用 ID=5，看增广数据
  python tools/view_lstm_data.py 喝水 --fps 30      # 播放更快
  python tools/view_lstm_data.py 我 --shot out.png  # 只导出中间帧 PNG（不开窗口）

窗口按键：ESC/q 退出 · 空格 暂停/继续 · n 下一组 · p 上一组 · a 切换 原始/增广
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "lstm_data"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SEQ_LEN = 45
PER_HAND = 66
CANVAS_W, CANVAS_H = 960, 720
WIN = "LSTM data"

# MediaPipe 手部 21 点标准连接
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),            # 拇指
    (0, 5), (5, 6), (6, 7), (7, 8),            # 食指
    (5, 9), (9, 10), (10, 11), (11, 12),       # 中指
    (9, 13), (13, 14), (14, 15), (15, 16),     # 无名指
    (13, 17), (17, 18), (18, 19), (19, 20),    # 小指
    (0, 17),                                   # 掌根→小指根
]
HAND_COLORS = [(0, 255, 0), (0, 200, 255)]     # 手1 绿 / 手2 橙（BGR）


def load_font(size: int):
    for fp in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
               "C:/Windows/Fonts/simsun.ttc"):
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


FONT = load_font(30)
FONT_S = load_font(22)


def restore_hand(feat66: np.ndarray):
    """还原一只手的 21 个关键点归一化 (x,y)。返回 (21,2) 或 None（该手不存在）。"""
    if not np.any(feat66):
        return None
    rel = feat66[:63].reshape(21, 3)
    wrist = feat66[63:66]
    return rel[:, :2] + wrist[:2]      # 相对 + 手腕绝对 = 原始归一化坐标


def draw_frame(feat132: np.ndarray, meta: tuple) -> np.ndarray:
    word, idx, total, frame_i, aug = meta
    canvas = np.full((CANVAS_H, CANVAS_W, 3), 30, dtype=np.uint8)

    n_hands = 0
    for h in range(2):
        hand = restore_hand(feat132[h * PER_HAND:(h + 1) * PER_HAND])
        if hand is None:
            continue
        n_hands += 1
        color = HAND_COLORS[h]
        pts = [(int(x * CANVAS_W), int(y * CANVAS_H)) for x, y in hand]
        for a, b in HAND_CONNECTIONS:
            cv2.line(canvas, pts[a], pts[b], color, 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(canvas, p, 5, color, -1, cv2.LINE_AA)
            cv2.circle(canvas, p, 5, (255, 255, 255), 1, cv2.LINE_AA)

    # 中文信息用 PIL 叠（cv2.putText 画不了中文）
    img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)
    tag = "  [增广]" if aug else "  [原始]"
    d.text((16, 12), f"词：{word}{tag}", font=FONT, fill=(255, 255, 255))
    d.text((16, 54), f"组 {idx + 1}/{total}   帧 {frame_i + 1}/{SEQ_LEN}   手数 {n_hands}",
           font=FONT_S, fill=(180, 220, 255))
    d.text((16, CANVAS_H - 34), "空格 暂停 | n/p 切组 | a 原始/增广 | ESC 退出",
           font=FONT_S, fill=(150, 150, 150))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def load_group_file(gid: int, aug: bool):
    f = DATA_DIR / f"gesture_{gid:03d}{'_aug' if aug else ''}.npy"
    if not f.exists():
        return None
    arr = np.load(f, allow_pickle=True)
    return arr if len(arr) else None


def main():
    ap = argparse.ArgumentParser(description="回放查看 LSTM 手语采集数据（骨架动画）")
    ap.add_argument("word", help="词名(中文)或 ID(0-27)")
    ap.add_argument("-i", "--index", type=int, default=0, help="第几组（默认 0）")
    ap.add_argument("--aug", action="store_true", help="查看增广数据（默认原始）")
    ap.add_argument("--fps", type=float, default=20, help="播放帧率（默认 20）")
    ap.add_argument("--shot", help="只渲染一帧存 PNG（不开窗口），用于预览/导出")
    ap.add_argument("--frame", type=int, default=SEQ_LEN // 2,
                    help="--shot 时渲染第几帧（默认中间帧）")
    args = ap.parse_args()

    label_map = json.loads((DATA_DIR / "label_map.json").read_text(encoding="utf-8"))
    name2id = {v: int(k) for k, v in label_map.items()}
    if args.word.isdigit():
        gid = int(args.word)
    elif args.word in name2id:
        gid = name2id[args.word]
    else:
        print(f"找不到词「{args.word}」。可选：{list(name2id)}")
        return
    if str(gid) not in label_map:
        print(f"ID {gid} 超出范围 0-{len(label_map) - 1}")
        return
    word = label_map[str(gid)]

    aug = args.aug
    data = load_group_file(gid, aug)
    if data is None:
        print(f"无数据：gesture_{gid:03d}{'_aug' if aug else ''}.npy 不存在或为空")
        return
    total = len(data)
    idx = min(max(args.index, 0), total - 1)

    # —— 单帧导出模式 ——
    if args.shot:
        fi = min(max(args.frame, 0), SEQ_LEN - 1)
        cv2.imwrite(args.shot, draw_frame(data[idx][fi], (word, idx, total, fi, aug)))
        print(f"已保存「{word}」第 {idx + 1}/{total} 组 第 {fi + 1} 帧 → {args.shot}")
        return

    # —— 动画播放模式 ——
    print(f"播放「{word}」(ID {gid})：{total} 组，每组 {SEQ_LEN} 帧。"
          f"空格暂停 / n,p 切组 / a 原始增广 / ESC 退出")
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, CANVAS_W, CANVAS_H)
    delay = max(1, int(1000 / args.fps))
    frame_i, paused = 0, False
    while True:
        cv2.imshow(WIN, draw_frame(data[idx][frame_i], (word, idx, total, frame_i, aug)))
        key = cv2.waitKey(delay) & 0xFF
        if key in (27, ord("q")):
            break
        elif key == ord(" "):
            paused = not paused
        elif key == ord("n"):
            idx = (idx + 1) % total; frame_i = 0
        elif key == ord("p"):
            idx = (idx - 1) % total; frame_i = 0
        elif key == ord("a"):
            nd = load_group_file(gid, not aug)
            if nd is not None:
                aug = not aug; data = nd; total = len(data); idx = 0; frame_i = 0
            else:
                print("（该词没有对应的原始/增广文件）")
        if not paused:
            frame_i = (frame_i + 1) % SEQ_LEN

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
