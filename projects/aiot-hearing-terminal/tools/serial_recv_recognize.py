"""
读 ESP32 COM7 (CH340/UART, 115200) 的 base64 行协议 → 收齐 45 帧
→ MediaPipe 抽关键点 → LSTM 推理 → 打印 top-3 识别结果。

依赖：
    pip install pyserial opencv-python mediapipe tensorflow numpy

用法：
    python tools/serial_recv_recognize.py                 # 默认 COM7
    python tools/serial_recv_recognize.py --port COM7 --save

协议（与 capture_for_lstm 固件配对，走 COM7）：
    CLIP_START <total>
    FRAME <idx>/<total> <jpeg_len> <base64...>
    ...
    CLIP_END <got>
    其余行（ESP_LOG，含倒计时 POSE）按 [esp] 显示。
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import re
import sys
import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import serial

# 把项目根加入 sys.path，方便 import hand_features / real_time_lstm
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from hand_features import (   # noqa: E402
    FEATURE_DIM,
    SEQ_LEN,
    extract_all_hands,
    normalize_sequence,
)

FRAME_RE = re.compile(r"^FRAME\s+(\d+)/(\d+)\s+(\d+)\s+(.+)$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")   # 剥 ESP_LOG 颜色码


# --------------------------------------------------------------
# LSTM 加载（复用 real_time_lstm.LSTMPredictor）
# --------------------------------------------------------------
def load_predictor(model_dir: Path):
    from real_time_lstm import LSTMPredictor
    return LSTMPredictor(str(model_dir))


def init_mediapipe():
    import mediapipe as mp

    return mp.solutions.hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.6,
    )


# --------------------------------------------------------------
# 推理
# --------------------------------------------------------------
def jpegs_to_features(jpegs: list[Optional[bytes]], hands_detector):
    """45 帧 JPEG bytes → (45, 132) 特征数组，返回 (features, hands_per_frame)"""
    feats = np.zeros((SEQ_LEN, FEATURE_DIM), dtype=np.float32)
    hands_per_frame = []
    for i in range(SEQ_LEN):
        jpeg = jpegs[i] if i < len(jpegs) else None
        if not jpeg:
            hands_per_frame.append(0)
            continue
        img = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            hands_per_frame.append(0)
            continue
        combined, n_hands, _ = extract_all_hands(img, hands_detector)
        feats[i] = combined
        hands_per_frame.append(n_hands)
    return feats, hands_per_frame


def predict_topk(predictor, sequence: np.ndarray, k: int = 3):
    """直接调底层 interpreter，拿到完整概率分布做 top-k"""
    seq = normalize_sequence(sequence)
    input_data = seq.astype(np.float32).reshape(1, SEQ_LEN, FEATURE_DIM)

    if predictor.use_tflite:
        in_dt = predictor.input_details[0]["dtype"]
        if in_dt == np.int8:
            s, z = predictor.input_details[0]["quantization"]
            input_data = (input_data / s + z).astype(np.int8)
        predictor.interpreter.set_tensor(
            predictor.input_details[0]["index"], input_data
        )
        predictor.interpreter.invoke()
        out = predictor.interpreter.get_tensor(
            predictor.output_details[0]["index"]
        )
        if predictor.output_details[0]["dtype"] == np.int8:
            s, z = predictor.output_details[0]["quantization"]
            out = (out.astype(np.float32) - z) * s
        probs = out[0]
    elif predictor.model is not None:
        probs = predictor.model.predict(input_data, verbose=0)[0]
    else:
        return []

    top_idx = np.argsort(probs)[::-1][:k]
    return [
        (int(i), predictor.label_map.get(int(i), str(int(i))), float(probs[int(i)]))
        for i in top_idx
    ]


def process_clip(
    jpegs: list[Optional[bytes]],
    hands_detector,
    predictor,
    save_dir: Optional[Path],
):
    n_got = sum(1 for j in jpegs if j is not None)
    print(f"\n  ━━━ 收齐 {n_got}/{SEQ_LEN} 帧, 开始推理 ━━━")

    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        for i, jpeg in enumerate(jpegs):
            if jpeg:
                (save_dir / f"frame_{i:02d}.jpg").write_bytes(jpeg)
        print(f"  💾 已保存原始帧 → {save_dir}")

    feats, hands_per_frame = jpegs_to_features(jpegs, hands_detector)
    n_detected = sum(1 for h in hands_per_frame if h > 0)
    print(f"  📊 MediaPipe: {n_detected}/{SEQ_LEN} 帧检测到手")
    if n_detected < SEQ_LEN * 0.5:
        print(f"  ⚠ 超过一半帧无手，识别结果可能不可靠")

    top3 = predict_topk(predictor, feats, k=3)
    if not top3:
        print(f"  ✗ 模型未加载，无法推理")
        return None
    print(f"  🎯 Top-3 识别结果：")
    for rank, (cid, name, conf) in enumerate(top3, 1):
        bar = "█" * int(conf * 30)
        print(f"     #{rank}  [{cid:2d}] {name:8s}  {conf * 100:5.1f}%  {bar}")
    # 返回 top-1 (词, 置信度) 供累积成句
    _, name, conf = top3[0]
    return name, conf


# --------------------------------------------------------------
# 串口监听主循环
# --------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM7", help="串口号 (默认 COM7)")
    ap.add_argument("--baud", type=int, default=921600, help="波特率 (默认 921600；乱码就降到 460800)")
    ap.add_argument("--save", action="store_true", help="保存原始帧到 captures/<时间戳>/")
    ap.add_argument("--no-polish", action="store_true", help="关闭大模型润色（只识别单词）")
    ap.add_argument("--conf", type=float, default=0.6, help="累积成句的置信度阈值 (默认 0.6)")
    ap.add_argument(
        "--model-dir", default=str(PROJECT_ROOT / "lstm_models"),
        help="LSTM 模型目录 (默认 lstm_models/)",
    )
    args = ap.parse_args()

    # 润色函数（火山方舟 Doubao-Seed-1.6，密钥在 .env 的 ARK_API_KEY）
    polish_fn = None
    if not args.no_polish:
        try:
            from cloud import polish as polish_fn
            print(f"  ✓ 大模型润色已启用 (cloud.polish)")
        except Exception as e:
            print(f"  ⚠ 润色不可用（{e}），只做单词识别")

    print(f"  加载 LSTM ...")
    predictor = load_predictor(Path(args.model_dir))

    print(f"  初始化 MediaPipe ...")
    hands_detector = init_mediapipe()

    print(f"\n  打开串口 {args.port} @ {args.baud}")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=2)
    except serial.SerialException as e:
        print(f"  ✗ 串口打开失败: {e}")
        print(f"    检查：1) 串口号对不对；2) VSCode Monitor / 别的脚本没占用 COM7")
        sys.exit(1)

    # 累句状态 + 后台键盘线程：回车=润色成句，输入 c=清空
    sentence_words: list[str] = []
    finalize_flag = threading.Event()
    clear_flag = threading.Event()

    def stdin_watcher():
        while True:
            try:
                cmd = sys.stdin.readline()
            except Exception:
                return
            if cmd == "":          # EOF
                return
            if cmd.strip().lower() in ("c", "clear", "清空"):
                clear_flag.set()
            else:                  # 回车（空行）或其它 → 润色成句
                finalize_flag.set()

    if polish_fn is not None:
        threading.Thread(target=stdin_watcher, daemon=True).start()

    print(f"\n  ✓ 就绪。对着摄像头做手势，每组保持 ~1.5 秒")
    if polish_fn is not None:
        print(f"  比完一句后【回车】→ 大模型润色成句；输入 c + 回车 → 清空重来")
    print(f"  Ctrl+C 退出\n")

    def do_finalize():
        if not sentence_words:
            print(f"  （还没识别到词，先做几个手势）")
            return
        words = list(sentence_words)
        sentence_words.clear()
        print(f"\n  🧩 词序列: {words}")
        try:
            sentence = polish_fn(words)
            print(f"  📝 润色成句 → 「{sentence}」\n")
        except Exception as e:
            print(f"  ✗ 润色失败: {e}（原始词: {' '.join(words)}）\n")

    state = "IDLE"
    jpegs: list[Optional[bytes]] = [None] * SEQ_LEN

    try:
        while True:
            # 处理键盘命令（回车润色 / c 清空），readline 超时即检查
            if polish_fn is not None:
                if finalize_flag.is_set():
                    finalize_flag.clear()
                    do_finalize()
                if clear_flag.is_set():
                    clear_flag.clear()
                    sentence_words.clear()
                    print(f"  🧹 已清空词序列\n")

            raw = ser.readline()
            if not raw:
                continue
            line = ANSI_RE.sub("", raw.decode("utf-8", errors="ignore")).strip()
            if not line:
                continue

            if line.startswith("CLIP_START"):
                print(f"\n┌─ {line} ─────────")
                jpegs = [None] * SEQ_LEN
                state = "RECV"
                continue

            if line.startswith("CLIP_END"):
                if state == "RECV":
                    got = sum(1 for j in jpegs if j is not None)
                    print(f"\n└─ {line} (实收 {got}/{SEQ_LEN})")
                    if got >= SEQ_LEN * 0.6:
                        save_dir = None
                        if args.save:
                            ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                            save_dir = PROJECT_ROOT / "captures" / ts
                        result = process_clip(jpegs, hands_detector, predictor, save_dir)
                        if result and polish_fn is not None:
                            word, conf = result
                            if conf >= args.conf:
                                sentence_words.append(word)
                                print(f"  ➕ 累计词序列: {sentence_words}"
                                      f"   （回车=润色成句, c=清空）")
                            else:
                                print(f"  ↷ 置信度 {conf*100:.0f}% < {args.conf*100:.0f}%，不计入（可重做这个词）")
                    else:
                        print(f"  ⚠ 帧数太少 ({got}/{SEQ_LEN})，跳过推理")
                state = "IDLE"
                continue

            if state == "RECV":
                m = FRAME_RE.match(line)
                if m:
                    idx = int(m.group(1))
                    declared = int(m.group(3))
                    try:
                        jpeg = base64.b64decode(m.group(4))
                    except Exception:
                        continue
                    if 0 <= idx < SEQ_LEN and len(jpeg) == declared:
                        jpegs[idx] = jpeg
                        got = sum(1 for j in jpegs if j is not None)
                        if got % 5 == 0 or got == SEQ_LEN:
                            print(f"│  ... {got}/{SEQ_LEN} frames", end="\r")
                            sys.stdout.flush()
                    continue

            # 其余（ESP_LOG，含 POSE 倒计时）
            print(f"  [esp] {line}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\n\n  收到 Ctrl+C, 退出")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
