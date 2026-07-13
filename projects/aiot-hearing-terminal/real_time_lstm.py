# ============================================================
# 实时 LSTM 手语识别
# 使用训练好的 LSTM 模型实时识别手语
# 完全本地运行, 零网络依赖
# ============================================================
# 功能:
#   1. 实时摄像头 + MediaPipe 手部关键点检测
#   2. 滑动窗口缓冲区 (45 帧 = 1.5 秒)
#   3. LSTM 模型推理
#   4. 帧差检测自动触发
#   5. 结果平滑显示
# ============================================================

import cv2
import numpy as np
import os
import sys
import json
import time
import threading
from collections import deque
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Windows 控制台 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ============================================================
# 配置
# ============================================================
from hand_features import (
    SEQ_LEN, FEATURE_DIM,
    extract_all_hands as hf_extract_all_hands,
    normalize_sequence as hf_normalize_sequence,
)

MODEL_DIR = "lstm_models"
# SEQ_LEN / FEATURE_DIM 来自 hand_features (132 = 双手 × (63手型+3手腕绝对))
CONFIDENCE_THRESHOLD = 0.3   # 置信度阈值（量化模型概率分布被压扁，降低阈值）
SMOOTHING_WINDOW = 5         # 结果平滑窗口

# 帧差检测参数
MOTION_THRESHOLD = 30        # 帧差均值的阈值
MOTION_COOLDOWN = 1.5        # 触发后冷却时间 (秒)
MIN_MOTION_FRAMES = 5        # 最少连续运动帧数才触发

# ============================================================
# MediaPipe 初始化
# ============================================================
try:
    import mediapipe as mp
    from mediapipe import solutions
    mp_hands = solutions.hands
    hands_detector = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.6,
    )
    mp_draw = solutions.drawing_utils
    print("  ✅ MediaPipe 初始化完成")
except ImportError:
    print("  ❌ mediapipe 未安装! 请运行: pip install mediapipe")
    exit(1)


# ============================================================
# 模型加载
# ============================================================

class LSTMPredictor:
    """LSTM 模型推理器 (支持 TF / TFLite / 轻量 NumPy 回退)"""

    def __init__(self, model_dir=MODEL_DIR):
        self.model = None
        self.interpreter = None
        self.use_tflite = False
        self.label_map = {}
        self.label_list = []
        self.input_details = None
        self.output_details = None
        
        # 加载标签映射
        class_map_path = os.path.join(model_dir, "class_map.json")
        if os.path.exists(class_map_path):
            with open(class_map_path, "r", encoding="utf-8") as f:
                class_map = json.load(f)
            # 转换为 {id: name} 格式, 按 ID 排序
            id_to_name = class_map.get("id_to_name", {})
            sorted_ids = sorted(int(k) for k in id_to_name.keys())
            self.label_list = [id_to_name[str(i)] for i in sorted_ids]
            self.label_map = {i: name for i, name in enumerate(self.label_list)}
            print(f"  ✅ 已加载 {len(self.label_list)} 个类别: {self.label_list}")
        else:
            print(f"  ⚠️ 未找到类别映射, 使用默认标签")
            self.label_list = [f"手势 {i}" for i in range(10)]
            self.label_map = {i: f"手势 {i}" for i in range(10)}
        
        # --- 尝试加载 TFLite 模型 ---
        # 优先加载 FP32 model.tflite (更准确, 适合 PC 端)
        # model_quant.tflite 是 INT8 量化版, 精度略低, 用于 ESP32-S3
        tflite_paths = [
            os.path.join(model_dir, "model.tflite"),       # FP32, 优先
            os.path.join(model_dir, "model_quant.tflite"), # INT8, 量化版(备选)
        ]
        
        for tflite_path in tflite_paths:
            if os.path.exists(tflite_path):
                try:
                    import tensorflow as tf
                    self.interpreter = tf.lite.Interpreter(model_path=tflite_path)
                    self.interpreter.allocate_tensors()
                    self.input_details = self.interpreter.get_input_details()
                    self.output_details = self.interpreter.get_output_details()
                    self.use_tflite = True
                    size_kb = os.path.getsize(tflite_path) / 1024
                    print(f"  ✅ 已加载 TFLite 模型: {os.path.basename(tflite_path)} ({size_kb:.1f} KB)")
                    break
                except Exception as e:
                    print(f"  ⚠️ TFLite 加载失败: {e}")
        
        # 尝试加载 Keras 模型 (备选)
        if not self.use_tflite:
            keras_path = os.path.join(model_dir, "best_model.keras")
            if not os.path.exists(keras_path):
                keras_path = os.path.join(model_dir, "final_model.keras")
            
            if os.path.exists(keras_path):
                try:
                    import tensorflow as tf
                    self.model = tf.keras.models.load_model(keras_path)
                    print(f"  ✅ 已加载 Keras 模型: {os.path.basename(keras_path)}")
                except Exception as e:
                    print(f"  ⚠️ Keras 加载失败: {e}")
        
        if not self.use_tflite and self.model is None:
            print("  ❌ 未找到可用模型! 请先运行 train_lstm_model.py")
            print(f"  📁 请将模型文件放在 {model_dir}/ 目录下")
    
    def predict(self, sequence):
        """
        预测手势类别。
        sequence: (SEQ_LEN, FEATURE_DIM) numpy array
        返回: (class_id, class_name, confidence)
        """
        if self.use_tflite:
            return self._predict_tflite(sequence)
        elif self.model is not None:
            return self._predict_keras(sequence)
        else:
            return -1, "无模型", 0.0
    
    def _predict_tflite(self, sequence):
        """TFLite 推理"""
        import tensorflow as tf

        # 归一化 (与采集/训练一致: 不做 per-sequence z-score)
        seq = hf_normalize_sequence(sequence)

        # 调整输入格式
        input_data = seq.astype(np.float32).reshape(1, SEQ_LEN, FEATURE_DIM)
        
        # TFLite int8 量化处理
        input_dtype = self.input_details[0]["dtype"]
        if input_dtype == np.int8:
            # 量化为 int8
            input_scale, input_zero = self.input_details[0]["quantization"]
            input_data = (input_data / input_scale + input_zero).astype(np.int8)
        
        self.interpreter.set_tensor(self.input_details[0]["index"], input_data)
        self.interpreter.invoke()
        
        output_data = self.interpreter.get_tensor(self.output_details[0]["index"])
        
        # 反量化
        output_dtype = self.output_details[0]["dtype"]
        if output_dtype == np.int8:
            output_scale, output_zero = self.output_details[0]["quantization"]
            output_data = (output_data.astype(np.float32) - output_zero) * output_scale
        
        probs = output_data[0]
        class_id = int(np.argmax(probs))
        confidence = float(probs[class_id])
        class_name = self.label_map.get(class_id, f"未知({class_id})")
        
        self.last_probs = probs   # 供操作台 UI 取 top-k
        return class_id, class_name, confidence
    
    def _predict_keras(self, sequence):
        """Keras 推理"""
        # 归一化 (与采集/训练一致: 不做 per-sequence z-score)
        seq = hf_normalize_sequence(sequence)

        input_data = seq.reshape(1, SEQ_LEN, FEATURE_DIM)
        probs = self.model.predict(input_data, verbose=0)[0]
        
        class_id = int(np.argmax(probs))
        confidence = float(probs[class_id])
        class_name = self.label_map.get(class_id, f"未知({class_id})")
        
        self.last_probs = probs   # 供操作台 UI 取 top-k
        return class_id, class_name, confidence
    
    def predict_batch(self, sequences):
        """
        批量预测 (用于评估)
        """
        if self.model is not None:
            probs = self.model.predict(sequences, verbose=0)
            return np.argmax(probs, axis=1), np.max(probs, axis=1)
        return np.zeros(len(sequences)), np.zeros(len(sequences))


# ============================================================
# 帧差检测
# ============================================================

class MotionDetector:
    """基于帧差的运动检测器"""

    def __init__(self, threshold=MOTION_THRESHOLD, cooldown=MOTION_COOLDOWN):
        self.threshold = threshold
        self.cooldown = cooldown
        self.prev_gray = None
        self.last_trigger_time = 0
        self.motion_counter = 0
        self.is_motion = False

    def detect(self, frame):
        """
        检测是否有运动。
        返回: (has_motion, motion_score)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self.prev_gray is None:
            self.prev_gray = gray
            return False, 0.0

        # 帧差
        diff = cv2.absdiff(self.prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_score = np.mean(thresh)

        self.prev_gray = gray

        # 判断是否在运动
        current_time = time.time()
        in_cooldown = (current_time - self.last_trigger_time) < self.cooldown

        if motion_score > self.threshold and not in_cooldown:
            self.motion_counter += 1
            if self.motion_counter >= MIN_MOTION_FRAMES:
                self.is_motion = True
                self.last_trigger_time = current_time
                self.motion_counter = 0
                return True, motion_score
        else:
            self.motion_counter = max(0, self.motion_counter - 1)

        self.is_motion = motion_score > self.threshold * 0.5
        return False, motion_score


# ============================================================
# 结果平滑
# ============================================================

class PredictionSmoother:
    """预测结果平滑器"""

    def __init__(self, window_size=SMOOTHING_WINDOW):
        self.window = deque(maxlen=window_size)

    def add(self, class_id, class_name, confidence):
        self.window.append((class_id, class_name, confidence))

    def get_smoothed(self):
        """获取平滑后的结果"""
        if not self.window:
            return -1, "无数据", 0.0
        
        # 按类别投票
        votes = {}
        for cid, cname, conf in self.window:
            if cid not in votes:
                votes[cid] = {"name": cname, "count": 0, "total_conf": 0.0}
            votes[cid]["count"] += 1
            votes[cid]["total_conf"] += conf
        
        # 选择票数最多的类别
        best_id = max(votes.keys(), key=lambda k: (votes[k]["count"], votes[k]["total_conf"]))
        best = votes[best_id]
        avg_conf = best["total_conf"] / best["count"]
        
        return best_id, best["name"], avg_conf


# ============================================================
# 关键点提取
# ============================================================

def extract_all_hands(frame, max_hands=2):
    """
    从一帧中提取双手特征 (调用共享模块 hand_features)。
    返回: (132 维向量, 手数, results 对象) — results 供 draw_landmarks 复用
    """
    return hf_extract_all_hands(frame, hands_detector, max_hands)


def draw_landmarks(frame, results):
    """绘制手部关键点 (复用已有 results，不重复调用 MediaPipe)"""
    if results.multi_hand_landmarks:
        for hand in results.multi_hand_landmarks:
            mp_draw.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)
    return frame


# ============================================================
# 中文文本绘制 (PIL)
# ============================================================

def _get_font(size=32):
    """获取支持中文的字体"""
    font_paths = [
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def put_chinese_text(img, text, position, font_size=32, color=(0, 255, 0), thickness=3):
    """在 OpenCV 图像上绘制中文文本（使用 PIL）"""
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    font = _get_font(font_size)
    draw.text(position, text, font=font, fill=(color[2], color[1], color[0]))  # PIL 是 RGB
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 55)
    print("  🤟 实时 LSTM 手语识别")
    print("  完全本地运行, 零网络依赖")
    print("=" * 55)

    # ——— 加载模型 ———
    print("\n  📦 加载模型...")
    predictor = LSTMPredictor()
    if predictor.model is None and not predictor.use_tflite:
        print("  ❌ 未加载模型, 退出")
        return

    # ——— 初始化检测器 ———
    motion_detector = MotionDetector()
    smoother = PredictionSmoother()

    # ——— 打开摄像头 ———
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("  ❌ 无法打开摄像头")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    print("  ✅ 摄像头已打开 (640x480 @ 30fps)")
    print("\n  ⌨️  操作说明:")
    print("    ESC       - 退出")
    print("    Space     - 手动触发识别")
    print("    'm'       - 切换运动检测模式")
    print("    'd'       - 调试模式 (显示帧差)")
    print("    'r'       - 重置缓冲区")
    print()

    # ——— 初始化 ———
    frame_buffer = deque(maxlen=SEQ_LEN)  # 滑动窗口: 最多 45 帧
    all_hand_counts = deque(maxlen=SEQ_LEN)
    
    auto_mode = False       # 手动触发模式 (按空格触发)
    debug_mode = False      # 调试显示
    manual_trigger = False  # 手动触发标志
    collecting = False      # 是否正在采集
    waiting_for_stable = False  # 等待手势稳定
    stable_hand_frames = 0      # 连续检测到手的帧数
    collect_start_time = 0  # 开始采集的时间
    last_prediction = ""
    prediction_display_time = 0
    result_locked_until = 0  # 结果锁定显示到什么时候
    fps_counter = 0
    fps_time = time.time()
    current_fps = 0

    # 窗口
    cv2.namedWindow("LSTM 手语识别", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("LSTM 手语识别", 960, 720)

    print("  🟢 开始实时识别...")
    print(f"{'=' * 55}")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        display = frame.copy()

        # ——— 1. 提取关键点 ———
        feats, hand_count, mp_results = extract_all_hands(frame)
        frame_buffer.append(feats)
        all_hand_counts.append(hand_count)

        # ——— 2. 检测运动 ———
        has_motion, motion_score = motion_detector.detect(frame)

        # ——— 3. 判断是否触发识别 ———
        should_predict = False

        # 自动模式：帧差检测到运动时自动触发
        if auto_mode and has_motion and not collecting and not waiting_for_stable and time.time() >= result_locked_until:
            manual_trigger = True

        # 按空格 / 自动触发：开始等待手势稳定（非采集状态 + 结果锁定已过时才触发）
        if manual_trigger and not collecting and not waiting_for_stable and time.time() >= result_locked_until:
            waiting_for_stable = True
            stable_hand_frames = 0
            manual_trigger = False
            # 清空平滑器历史投票: 离散单次触发模式下, 防止上一次结果的票数
            # 压制本次新识别(否则会"坚持上一次结果")
            smoother.window.clear()
            print("  🟡 等待手势... 请举手保持不动!")

        # 等待手势稳定：等连续检测到手至少15帧(0.5s)后再开始正式采集
        if waiting_for_stable:
            if hand_count > 0:
                stable_hand_frames += 1
                if stable_hand_frames >= 15:  # ~0.5秒连续有手
                    # 手势稳定了！清空过渡帧，开始正式采集
                    frame_buffer.clear()
                    all_hand_counts.clear()
                    waiting_for_stable = False
                    collecting = True
                    collect_start_time = time.time()
                    print("  🟢 开始采集 (1.5s)... 保持手势!")
            else:
                stable_hand_frames = max(0, stable_hand_frames - 2)  # 手消失快速衰减

        # 正在采集中：持续采集1.5秒
        if collecting:
            elapsed = time.time() - collect_start_time
            if elapsed >= 1.5 and len(frame_buffer) >= SEQ_LEN:
                should_predict = True
                collecting = False

        # ——— 4. 推理 ———
        if should_predict and len(frame_buffer) == SEQ_LEN:
            sequence = np.array(frame_buffer, dtype=np.float32)
            
            # 检查是否有手
            valid_hands = sum(1 for c in all_hand_counts if c > 0)
            if valid_hands >= SEQ_LEN * 0.3:
                class_id, class_name, confidence = predictor.predict(sequence)
                
                if confidence >= CONFIDENCE_THRESHOLD:
                    smoother.add(class_id, class_name, confidence)
                    smooth_id, smooth_name, smooth_conf = smoother.get_smoothed()
                    
                    current_time = time.time()
                    if smooth_name != last_prediction or (current_time - prediction_display_time) > 2:
                        if smooth_conf >= CONFIDENCE_THRESHOLD:
                            last_prediction = smooth_name
                            prediction_display_time = current_time
                            print(f"  🤟 识别: 【{smooth_name}】 (置信度: {smooth_conf:.2%})")
                            # ✅ 锁定结果显示 2 秒
                            result_locked_until = time.time() + 2.0
                else:
                    print(f"  🤔 置信度不足: {class_name} ({confidence:.2%})")
            else:
                print(f"  ⚠️ 未检测到手势 (有效帧: {valid_hands}/{SEQ_LEN})")
            
            # ✅ 识别后清空缓冲区，下次从头采集
            frame_buffer.clear()
            all_hand_counts.clear()
        
        # ——— 5. 绘制界面 ———
        h, w = display.shape[:2]

        # 运动指示器
        color = (0, 255, 0) if motion_detector.is_motion else (0, 0, 255)
        cv2.circle(display, (30, 30), 10, color, -1)
        cv2.putText(display, f"运动: {motion_score:.1f}", (50, 35),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # 模式显示 + 采集状态
        mode_text = "AUTO" if auto_mode else "MANUAL"
        cv2.putText(display, f"[{mode_text}]", (w - 100, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        # 采集状态 / 锁定状态 / 等待手势 提示
        now = time.time()
        if collecting:
            remain = max(0, 1.5 - (now - collect_start_time))
            draw_color = (0, 255, 255)
            status_text = f"🟡 采集中... {remain:.1f}s"
            # 画面中心大字提示
            display = put_chinese_text(display, "🤚 请保持手势", (w//2 - 150, h//2),
                                       font_size=48, color=(0, 255, 255))
        elif waiting_for_stable:
            draw_color = (0, 255, 255)
            status_text = f"⏳ 等待举手... ({stable_hand_frames})"
            display = put_chinese_text(display, "✋ 请举手做手势", (w//2 - 170, h//2),
                                       font_size=48, color=(0, 255, 255))
        elif now < result_locked_until:
            # 结果显示锁定中
            lock_remain = result_locked_until - now
            draw_color = (100, 100, 100)  # 灰色
            status_text = f"🔒 锁定中 {lock_remain:.1f}s"
        else:
            draw_color = (255, 165, 0)
            status_text = f"⏎ 按空格开始"

        # 缓冲区进度条
        buffer_pct = len(frame_buffer) / SEQ_LEN
        bar_w = int(200 * buffer_pct)
        cv2.rectangle(display, (w - 220, 50), (w - 220 + bar_w, 65), draw_color, -1)
        cv2.rectangle(display, (w - 220, 50), (w - 20, 65), (255, 255, 255), 1)
        cv2.putText(display, f"Buffer: {len(frame_buffer)}/{SEQ_LEN}", (w - 220, 45),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

        # 手数
        if hand_count > 0:
            cv2.putText(display, f"手: {hand_count}", (w - 100, 80),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

        # 上一次识别结果
        if last_prediction:
            # 大号中文显示
            display = put_chinese_text(display, f"🤟 {last_prediction}", (30, h - 100),
                                       font_size=56, color=(0, 255, 0))
            
            # 平滑后的置信度
            _, _, smooth_conf = smoother.get_smoothed()
            display = put_chinese_text(display, f"置信度: {smooth_conf:.1%}", (30, h - 30),
                                       font_size=22, color=(255, 255, 255))

        # FPS
        fps_counter += 1
        if time.time() - fps_time >= 1.0:
            current_fps = fps_counter
            fps_counter = 0
            fps_time = time.time()
        cv2.putText(display, f"FPS: {current_fps}", (10, h - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # 手部关键点 (复用已提取的 results，不重复调用 MediaPipe)
        display = draw_landmarks(display, mp_results)

        # 调试模式：显示帧差
        if debug_mode and motion_detector.prev_gray is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(motion_detector.prev_gray, gray)
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            debug_img = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
            # 在右下角显示小图
            small_h, small_w = 120, 160
            resized = cv2.resize(debug_img, (small_w, small_h))
            display[h-small_h-10:h-10, w-small_w-10:w-10] = resized

        # ——— 显示 ———
        cv2.imshow("LSTM 手语识别", display)
        key = cv2.waitKey(1) & 0xFF

        if key == 27:  # ESC
            break
        elif key == 32:  # Space
            manual_trigger = True
            print("  👆 手动触发识别")
        elif key == ord("m"):
            auto_mode = not auto_mode
            print(f"  🔄 切换为 {'自动' if auto_mode else '手动'} 模式")
        elif key == ord("d"):
            debug_mode = not debug_mode
            print(f"  🔄 调试模式: {'开' if debug_mode else '关'}")
        elif key == ord("r"):
            frame_buffer.clear()
            all_hand_counts.clear()
            print("  🔄 缓冲区已重置")

    # ——— 清理 ———
    cap.release()
    cv2.destroyAllWindows()
    print(f"\n{'=' * 55}")
    print("  👋 识别结束")
    print(f"{'=' * 55}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    main()
