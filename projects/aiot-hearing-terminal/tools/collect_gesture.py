"""
端侧手势数据采集 —— 读 gesture_cam 固件的灰度帧，存成训练图片。

固件：esp32_firmware/gesture_cam（灰度 96x96 连续串口流）
协议：每行 "GFRAME <len> <base64>"，len=9216（96x96 灰度）

用法：
    python tools/collect_gesture.py --label fist
    python tools/collect_gesture.py --label palm --n 400
    （每个手势跑一次，--label 换成该手势名）

操作：
    弹出预览窗口，手放画面里做该手势，移动/转动/远近变化采多样本。
    空格 = 暂停/继续保存（重新摆位时先暂停，避免存到过渡帧）
    q    = 结束
保存到 gesture_data/<label>/<label>_<序号>.png
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import serial

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
GFRAME_RE = re.compile(r"^GFRAME\s+(\d+)\s+(.+)$")
SIZE = 96
IMG_BYTES = SIZE * SIZE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="手势名（存到 gesture_data/<label>/）")
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--n", type=int, default=300, help="目标张数 (默认 300)")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "gesture_data"))
    args = ap.parse_args()

    out_dir = Path(args.out) / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    # 接着已有序号往后存，不覆盖
    existing = sorted(out_dir.glob(f"{args.label}_*.png"))
    idx = (int(existing[-1].stem.split("_")[-1]) + 1) if existing else 0
    start_idx = idx

    print(f"  采集手势「{args.label}」→ {out_dir}")
    print(f"  已有 {len(existing)} 张，本次目标 +{args.n}")
    print(f"  打开 {args.port} @ {args.baud}")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=2)
    except serial.SerialException as e:
        print(f"  ✗ 串口打开失败: {e}")
        sys.exit(1)

    print("  摆好手势后按【空格】开始保存；再按空格暂停；q=结束\n")
    saving = False   # 默认暂停，避免采到没摆好的过渡帧
    win = f"collect: {args.label}"

    try:
        while idx - start_idx < args.n:
            raw = ser.readline()
            if not raw:
                continue
            line = ANSI_RE.sub("", raw.decode("utf-8", errors="ignore")).strip()
            if not line:
                continue
            m = GFRAME_RE.match(line)
            if not m:
                if not line.startswith("GFRAME"):
                    print(f"  [esp] {line}", file=sys.stderr)
                continue

            declared = int(m.group(1))
            try:
                buf = base64.b64decode(m.group(2))
            except Exception:
                continue
            if len(buf) != declared or len(buf) != IMG_BYTES:
                continue

            img = np.frombuffer(buf, dtype=np.uint8).reshape(SIZE, SIZE)

            if saving:
                cv2.imwrite(str(out_dir / f"{args.label}_{idx:04d}.png"), img)
                idx += 1

            # 预览（放大 4 倍 + 叠加信息）
            disp = cv2.cvtColor(cv2.resize(img, (SIZE * 4, SIZE * 4),
                                           interpolation=cv2.INTER_NEAREST),
                                cv2.COLOR_GRAY2BGR)
            txt = f"{args.label}  {idx - start_idx}/{args.n}  {'SAVING' if saving else 'PAUSED'}"
            color = (0, 255, 0) if saving else (0, 165, 255)
            cv2.putText(disp, txt, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            cv2.imshow(win, disp)

            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            if k == ord(" "):
                saving = not saving
                print(f"  {'▶ 继续保存' if saving else '⏸ 暂停'}")

    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        cv2.destroyAllWindows()

    print(f"\n  完成。本次新增 {idx - start_idx} 张，{args.label} 共 {idx} 张 → {out_dir}")


if __name__ == "__main__":
    main()
