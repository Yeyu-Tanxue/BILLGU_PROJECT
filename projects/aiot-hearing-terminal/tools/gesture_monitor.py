"""
端侧手势监视器 —— 读 ESP32 本地识别结果（COM7 @921600），显示 + 联动动作。

ESP32 端在本地跑 CNN，串口输出：
    det: <gesture> <conf>     稳定手势
    ACTION <gesture>          确认触发
本脚本显示这些，并把 ACTION 映射成动作：
    fist→唤醒  one→手语识别  two→语音识别  palm→紧急求助(推微信)

用法：
    python tools/gesture_monitor.py
    python tools/gesture_monitor.py --no-push   # 不真的推送紧急求助
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
import threading
from pathlib import Path

import cv2
import numpy as np
import serial

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
GFRAME_RE = re.compile(r"^GFRAME\s+(\d+)\s+(.+)$")
SIZE = 96
IMG_BYTES = SIZE * SIZE

ACTION_DESC = {
    "one":     "🤟 进入手语识别模式",
    "palm":    "🚨 紧急求助",
    "thumbup": "🔓 唤醒/成句",
    "two":     "🎤 进入语音识别模式",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--no-push", action="store_true", help="palm 不真的推送紧急求助")
    ap.add_argument("--verbose", action="store_true", help="显示连续 det 流 + ESP 日志（调试用）")
    args = ap.parse_args()

    notify = None
    if not args.no_push:
        try:
            from cloud import notify as notify
        except Exception as e:
            print(f"  ⚠ 紧急推送不可用（{e}），palm 仅显示不推送")

    print(f"  打开 {args.port} @ {args.baud}")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=2)
    except serial.SerialException as e:
        print(f"  ✗ 串口打开失败: {e}")
        sys.exit(1)

    print("  ✓ 监视端侧手势中（对摄像头做手势）。预览窗 q 或 Ctrl+C 退出\n")
    win = "ESP32 gesture (edge AI)"
    last_label = "..."          # 最近 det 结果，叠加到预览
    last_conf = {}              # 各手势最近置信度
    flash = 0                   # ACTION 时闪一下
    try:
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = ANSI_RE.sub("", raw.decode("utf-8", errors="ignore")).strip()
            if not line:
                continue

            mf = GFRAME_RE.match(line)
            if mf:
                try:
                    buf = base64.b64decode(mf.group(2))
                except Exception:
                    continue
                if len(buf) != IMG_BYTES:
                    continue
                img = np.frombuffer(buf, np.uint8).reshape(SIZE, SIZE)
                disp = cv2.cvtColor(cv2.resize(img, (SIZE * 5, SIZE * 5),
                                    interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
                col = (0, 0, 255) if flash > 0 else (0, 255, 0)
                cv2.putText(disp, last_label, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
                if flash > 0:
                    flash -= 1
                cv2.imshow(win, disp)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
                continue

            if line.startswith("ACTION "):
                g = line.split()[1] if len(line.split()) > 1 else "?"
                desc = ACTION_DESC.get(g, g)
                conf = last_conf.get(g, 0.0)
                last_label = f"ACTION: {g}"
                flash = 8
                # 一行干净输出：手势 + 置信度 + 动作
                print(f"  ✅ {g:5s} {conf:.2f}  →  {desc}")
                if g == "palm" and notify is not None:
                    # 后台线程发推送，避免 HTTP 阻塞读取循环 → 串口缓冲错位
                    def _push():
                        try:
                            notify("我需要帮助，请马上联系我。", title="🚨 紧急求助（手势触发）")
                            print("      ✅ 已推送紧急求助到微信")
                        except Exception as e:
                            print(f"      ✗ 推送失败: {e}")
                    threading.Thread(target=_push, daemon=True).start()
            elif line.startswith("det:"):
                # det 只更新预览叠加 + 记录置信度，不刷屏打印
                parts = line.split()
                if len(parts) >= 3:
                    last_label = f"{parts[1]} {parts[2]}"
                    try:
                        last_conf[parts[1]] = float(parts[2])
                    except ValueError:
                        pass
                if args.verbose:
                    print(f"  · {line}")
            elif args.verbose and len(line) < 160:
                print(f"  [esp] {line}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\n  退出")
    finally:
        ser.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
