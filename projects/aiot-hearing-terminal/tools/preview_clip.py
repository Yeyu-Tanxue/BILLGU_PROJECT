"""
把一组采集帧拼成预览图 + 叠加 MediaPipe 检测结果，
肉眼判断 ESP32 摄像头实拍质量 / 为什么抽不到手。

用法：
    python tools/preview_clip.py E:\ESP-S3\captures\20260606_161105
    python tools/preview_clip.py <dir> --cols 8
输出：
    <dir>/_preview.jpg          原始帧九宫格
    <dir>/_preview_hands.jpg    叠加 MediaPipe 关键点的九宫格
    控制台：每帧尺寸 / 平均亮度 / 是否检测到手
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir")
    ap.add_argument("--cols", type=int, default=8)
    args = ap.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    clip_dir = Path(args.clip_dir)
    jpgs = sorted(clip_dir.glob("frame_*.jpg"))
    if not jpgs:
        print(f"没找到 frame_*.jpg in {clip_dir}")
        return

    import mediapipe as mp
    hands = mp.solutions.hands.Hands(
        static_image_mode=True,         # 静态图模式（单张独立检测）
        max_num_hands=2,
        min_detection_confidence=0.3,   # 调低阈值，尽量多检
    )
    mp_draw = mp.solutions.drawing_utils

    raw_imgs, hand_imgs = [], []
    n_detected = 0
    print(f"\n  共 {len(jpgs)} 帧")
    print(f"  {'帧':<12}{'尺寸':<12}{'平均亮度':<10}{'检测到手'}")
    print("  " + "-" * 44)

    for jp in jpgs:
        img = cv2.imread(str(jp))
        if img is None:
            continue
        h, w = img.shape[:2]
        bright = float(np.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        res = hands.process(rgb)
        got = bool(res.multi_hand_landmarks)
        if got:
            n_detected += 1

        annotated = img.copy()
        if got:
            for hlm in res.multi_hand_landmarks:
                mp_draw.draw_landmarks(
                    annotated, hlm, mp.solutions.hands.HAND_CONNECTIONS
                )

        mark = "✓" if got else "✗"
        print(f"  {jp.name:<12}{w}x{h:<8}{bright:<10.1f}{mark}")

        raw_imgs.append(img)
        hand_imgs.append(annotated)

    print("  " + "-" * 44)
    print(f"  MediaPipe 检测到手: {n_detected}/{len(raw_imgs)} 帧")
    avg_bright = np.mean([np.mean(cv2.cvtColor(i, cv2.COLOR_BGR2GRAY)) for i in raw_imgs])
    print(f"  整组平均亮度: {avg_bright:.1f}  (参考：<60 偏暗, 60-180 正常, >200 过曝)")

    def make_grid(imgs, cols):
        if not imgs:
            return None
        h, w = imgs[0].shape[:2]
        rows = (len(imgs) + cols - 1) // cols
        grid = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)
        for i, im in enumerate(imgs):
            r, c = divmod(i, cols)
            if im.shape[:2] != (h, w):
                im = cv2.resize(im, (w, h))
            grid[r * h:(r + 1) * h, c * w:(c + 1) * w] = im
        return grid

    raw_grid = make_grid(raw_imgs, args.cols)
    hand_grid = make_grid(hand_imgs, args.cols)
    if raw_grid is not None:
        out1 = clip_dir / "_preview.jpg"
        cv2.imwrite(str(out1), raw_grid)
        print(f"\n  原始预览     → {out1}")
    if hand_grid is not None:
        out2 = clip_dir / "_preview_hands.jpg"
        cv2.imwrite(str(out2), hand_grid)
        print(f"  叠加手部预览 → {out2}")
    print()


if __name__ == "__main__":
    main()
