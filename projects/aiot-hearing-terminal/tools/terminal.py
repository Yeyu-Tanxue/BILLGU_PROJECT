"""
terminal —— 听障终端 PC 端接收程序（3.1 手语识别流程）
================================================================
配合 esp32_firmware/terminal 固件，COM7 @921600。

【为什么之前窗口卡死】单线程里同时读串口 + 跑 OpenCV 窗口 + 做重活
（润色是几秒的网络请求、MediaPipe/LSTM 是 1-2s 计算），重活一跑 cv2.waitKey
就不被调用 → 窗口"未响应"。本版改成**两线程**：
  · 主线程：只跑 OpenCV 窗口（waitKey + imshow），永不阻塞 → 不再卡。
  · worker 线程：串口收发 + MediaPipe/LSTM + 润色 + LCD 发送（随便阻塞都不影响窗口）。
所有 cv2 GUI 调用只在主线程；worker 只更新共享缓冲（加锁）。

【3.1 流程（每次比 L 采一个词 + 唤醒）】
  待机 → 👍thumbup 唤醒 → 比 L(=one) → 倒数3-2-1 → 采45帧 → PC识别累计一个词
       → 再比 L 采下一个 …… → 比 ✊fist → 润色成句 → 发 LCD + 清空 → 回待机
  任意态：✌️V(=two)→语音(占位)  🖐palm→紧急求助

【手势映射 ↔ 固件 CNN 类别（6 类）】
  唤醒     = thumbup👍 → EVT wake（待机→已唤醒）
  L(手语)  = one    → 唤醒后比 L 开始自动循环（CNN 暂用 one 代表 L）
  V(语音)  = two ✌️ → 唤醒后 EVT voice
  结束润色  = fist✊ → 循环内检测到即结束 → EVT finalize
           （fist 不与手语竖拇指撞；thumbup 留作一类还能吸收「好/谢谢」）
  求助     = palm🖐 → EVT emergency（任意态）

【固件待办（本文件做不到的部分）】
  1) 把 lcd_test 的 LCD 收+显代码并进 terminal 固件，--lcd 才会真亮
  2) 手语态自动循环采集 + 3-2-1 倒计时（现在是比一次 one 采一个词）
  3) 真 L 手势（重训 CNN）

用法：
  D:\anaconda3\envs\split\python.exe tools\terminal.py [--port COM7] [--save] [--no-polish] [--lcd]
"""
from __future__ import annotations

import argparse, base64, datetime as dt, os, re, sys, threading, time, traceback
from collections import deque
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import serial
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from hand_features import FEATURE_DIM, SEQ_LEN, extract_all_hands, normalize_sequence

FRAME_RE  = re.compile(r"^FRAME\s+(\d+)/(\d+)\s+(\d+)\s+(.+)$")
GFRAME_RE = re.compile(r"^GFRAME\s+(\d+)\s+(.+)$")
ANSI_RE   = re.compile(r"\x1b\[[0-9;]*m")
DET_RE    = re.compile(r"^det:\s+(\S+)\s+([\d.]+)")
AUDIO_START_RE  = re.compile(r"^AUDIO_START\s+(\d+)")
AUDIO_CHUNK_RE = re.compile(r"^AUDIO_CHUNK\s+(\d+)/(\d+)\s+(\d+)\s+(.+)$")
AUDIO_END_RE    = re.compile(r"^AUDIO_END\s+(\d+)")

# 固件手势类别 → 窗口显示用 ASCII 标签（cv2.putText 不支持中文）
GESTURE_CN = {
    "background": "STANDBY",
    "fist":       "FIST/END",   # 握拳：结束循环 → 润色
    "one":        "L/SIGN",     # 手语：唤醒后开始自动循环（暂用 one 代表 L）
    "palm":       "SOS",        # 求助
    "thumbup":    "WAKE",       # 竖拇指：待机唤醒
    "two":        "V/VOICE",    # 语音
}


# ================================================================
#  中文叠字（OpenCV 不支持中文，借 PIL 一次性画上去）
# ================================================================
def _find_font():
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
              "C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/Deng.ttf"):
        if os.path.exists(p):
            return p
    return None

_FONT_PATH = _find_font()
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}

def _font(size: int):
    if _FONT_PATH is None:
        return None
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(_FONT_PATH, size)
    return _font_cache[size]

def put_cjk_lines(img_bgr, items):
    """items: [(text, (x,y), size, (r,g,b)), ...]；一次 PIL 往返画完所有中文行。"""
    if _FONT_PATH is None:
        for text, org, size, color in items:
            cv2.putText(img_bgr, text.encode("ascii", "replace").decode(), org,
                        cv2.FONT_HERSHEY_SIMPLEX, size / 32, color[::-1], 1)
        return img_bgr
    try:
        pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        for text, org, size, color in items:
            if text:
                draw.text(org, text, font=_font(size), fill=color)
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    except Exception:
        return img_bgr


# ================================================================
#  线程间共享显示状态（worker 写、主线程读，全程加锁）
# ================================================================
class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.preview = np.zeros((96, 96), np.uint8)   # 菜单态灰度预览（GFRAME）
        self.cap_preview: Optional[np.ndarray] = None  # 手语采集态彩色帧（BGR），None=用菜单预览
        self.gesture = ""        # 当前手势 ASCII 标签
        self.mode = "待机"        # 待机 / 手语识别 / 语音
        self.words: list[str] = []
        self.status = ""         # 临时状态行（中文）
        self.progress = ""       # 采集进度（ASCII）
        self.running = True
        self.req_clear = False   # 主线程→worker：清空请求（保证串口 I/O 都在 worker）
        self.req_finalize = False
        self.req_wake = False    # 键盘 w：手动唤醒（排查/兜底）
        self.countdown = 0       # 采集前 3-2-1 倒计时（0=不显示）
        # ---- 信息操作版 UI ----
        self.gname = ""          # 当前手势(中文)
        self.gconf = 0.0         # 当前手势置信度
        self.recv = 0            # 当前 clip 已收/已识别帧数
        self.recv_phase = ""     # "收帧" / "识别" / ""
        self.top3: list = []     # [(词, 概率)] 最近一次识别
        self.last_word = ""
        self.last_conf = 0.0
        self.result = ""         # 最近成句结果(润色/字幕)
        self.fps = 0.0           # 预览帧率


# ================================================================
#  识别管线
# ================================================================
def load_predictor(model_dir: Path):
    from real_time_lstm import LSTMPredictor
    return LSTMPredictor(str(model_dir))

def init_mediapipe():
    import mediapipe as mp
    return mp.solutions.hands.Hands(
        static_image_mode=False, max_num_hands=2,
        min_detection_confidence=0.7, min_tracking_confidence=0.6,
    )

def jpegs_to_features(jpegs, hands_detector, shared: Shared):
    """解码 45 帧 → MediaPipe 抽特征。更新 shared.cap_preview（不调 cv2，主线程负责显示）。"""
    feats = np.zeros((SEQ_LEN, FEATURE_DIM), dtype=np.float32)
    hands_per_frame = []
    for i in range(SEQ_LEN):
        if jpegs[i] is None:
            hands_per_frame.append(0)
            continue
        npy = np.frombuffer(jpegs[i], np.uint8)
        img = cv2.imdecode(npy, cv2.IMREAD_COLOR)
        if img is None:
            hands_per_frame.append(0)
            continue
        combined, hand_count, _ = extract_all_hands(img, hands_detector)
        feats[i] = combined
        hands_per_frame.append(hand_count)
        with shared.lock:
            shared.progress = f"recog {i+1}/{SEQ_LEN}"   # 帧已在收帧时显示，这里只更新进度
            shared.recv = i + 1
            shared.recv_phase = "识别"
    return normalize_sequence(feats), hands_per_frame

def process_clip(jpegs, hands_detector, predictor, shared: Shared, save_dir=None):
    feats, hpf = jpegs_to_features(jpegs, hands_detector, shared)
    frames_with_hands = sum(1 for h in hpf if h > 0)
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        np.save(Path(save_dir) / "features.npy", feats)
        for i, j in enumerate(jpegs):
            if j:
                (Path(save_dir) / f"frame_{i:02d}.jpg").write_bytes(j)
    class_id, word, conf = predictor.predict(feats)   # 返回 (id, 词, 置信度)
    # top-3（供操作台显示）
    probs = getattr(predictor, "last_probs", None)
    top3 = []
    if probs is not None:
        order = np.argsort(probs)[::-1][:3]
        top3 = [(predictor.label_map.get(int(k), str(k)), float(probs[k])) for k in order]
    with shared.lock:
        shared.top3 = top3
        shared.last_word = word
        shared.last_conf = conf
    print(f"  🎯 {word} {conf*100:.0f}%  (含手帧 {frames_with_hands}/{SEQ_LEN})")
    return word, conf


def send_lcd(ser: serial.Serial, text: str, size: int, quiet: bool = False):
    """把中文渲染成横屏 1-bit 位图，发 TXT 给固件 LCD（需 terminal 固件已集成 LCD 收显）。"""
    from lcd_send import render_1bit
    w, h, rb, packed = render_1bit(text, size)
    b64 = base64.b64encode(packed).decode("ascii")
    ser.write(f"TXT {w} {h} {rb} {b64}\n".encode("ascii"))
    ser.flush()
    if not quiet:
        print(f"  📺 LCD TXT 已发送 {w}x{h}: {text}")


def send_spk(ser: serial.Serial, text: str, quiet: bool = False):
    """用 edge_tts 生成语音 → miniaudio 解码 → 16kHz int16 PCM → base64 → 发 SPK 给固件播放。

    行协议：SPK <num_samples> <base64_int16_pcm>\\n  （与 lcd_task 共用 UART0 RX 解析）
    固件端 spk_handle_line() 解码 base64 → int16 → 缩放音量（VOLUME_SCALE=2000/32768）→ I2S 播放。

    注意：使用 subprocess 生成 MP3 避免 event loop 冲突。
    """
    import subprocess, tempfile, sys as _sys, os as _os
    import miniaudio, numpy as np

    # 1. subprocess edge_tts → MP3 临时文件
    #    使用脚本文件而非 -c，避免 Windows 路径转义问题
    import tempfile
    tmp_name = tempfile.mktemp(suffix=".mp3")

    # 写一个简单脚本来生成 MP3
    tts_script = f"""
import asyncio, edge_tts
async def _r():
    c = edge_tts.Communicate({text!r}, 'zh-CN-XiaoxiaoNeural')
    await c.save({tmp_name!r})
asyncio.run(_r())
"""
    script_path = tmp_name + ".py"
    with open(script_path, "w", encoding="utf-8") as sf:
        sf.write(tts_script)

    result = subprocess.run(
        [_sys.executable, script_path],
        capture_output=True, text=True, timeout=15,
    )
    _os.unlink(script_path)
    if result.returncode != 0:
        print(f"  ⚠ TTS 生成失败: {result.stderr.strip().split(chr(10))[-1]}")
        if _os.path.exists(tmp_name):
            _os.unlink(tmp_name)
        return

    with open(tmp_name, "rb") as f:
        mp3_data = f.read()
    _os.unlink(tmp_name)
    if not mp3_data:
        print("  ⚠ TTS 生成失败（空文件）")
        return

    # 2. miniaudio 解码 → float32 numpy
    audio = miniaudio.decode(mp3_data, output_format=miniaudio.SampleFormat.FLOAT32)
    sr = audio.sample_rate
    nch = audio.nchannels
    raw = np.array(audio.samples, dtype=np.float32)
    if nch > 1:
        nframes = len(raw) // nch
        raw = raw.reshape(nframes, nch).T.mean(axis=0)

    # 3. 重采样到 16kHz（线性插值）
    TARGET_SR = 16000
    if sr != TARGET_SR:
        old_len = len(raw)
        new_len = int(old_len * TARGET_SR / sr)
        old_indices = np.linspace(0, old_len - 1, new_len)
        lo = np.floor(old_indices).astype(int)
        hi = np.clip(lo + 1, 0, old_len - 1)
        frac = old_indices - lo
        raw = (1 - frac) * raw[lo] + frac * raw[hi]
        raw = raw.astype(np.float32)

    # 4. 转 int16（满幅 → 固件端缩到最小音量 VOLUME_SCALE=2000/32768）
    maxv = np.abs(raw).max()
    if maxv > 0:
        raw = raw / maxv * 32767
    pcm = raw.astype(np.int16)

    # 5. 整句累积播放：先 SPKBEGIN 声明总样本，再分块传，固件 PSRAM 攒齐后一次性连续播放。
    #    根治断续/回音：播放是固件单次 i2s_channel_write 整句，DMA 连续供数、无块间空档；
    #    传输阶段慢/被抢占都不影响最终播放连续性（代价：出声前要等整句传完几秒）。
    #    CHUNK=4096 → 一行 base64 ≈10.9KB < 固件 UART RX ring 16KB，不溢出丢行。
    import time as _time
    CHUNK = 4096
    total_samples = len(pcm)
    ser.write(f"SPKBEGIN {total_samples}\n".encode("ascii"))
    ser.flush()
    sent = 0
    while sent < total_samples:
        end = min(sent + CHUNK, total_samples)
        chunk = pcm[sent:end]
        b64 = base64.b64encode(chunk.tobytes()).decode("ascii")
        ser.write(f"SPK {len(chunk)} {b64}\n".encode("ascii"))
        ser.flush()
        sent = end
        _time.sleep(0.01)   # 给固件批量读+解码喘息，防 RX ring 溢出
    if not quiet:
        print(f"  🔊 SPK: {text} ({len(pcm) / TARGET_SR:.1f}s)")


# ---------- 彩色 LCD UI（lcd_ui.py 组屏；仅 --lcd 时启用）----------
def lcd_show(ser, args, state, body=None):
    if not args.lcd:
        return
    try:
        import lcd_ui
        lcd_ui.show(ser, state, body)
    except Exception as e:
        print(f"  ⚠ LCD UI: {e}")

def lcd_cd(ser, args, n):
    if not args.lcd:
        return
    try:
        import lcd_ui
        lcd_ui.show_countdown(ser, n)
    except Exception as e:
        print(f"  ⚠ LCD UI: {e}")

def lcd_body(ser, args, state, text):
    if not args.lcd:
        return
    try:
        import lcd_ui
        lcd_ui.update_body(ser, state, text)
    except Exception as e:
        print(f"  ⚠ LCD UI: {e}")


# ================================================================
#  worker：串口收发 + 识别 + 润色 + LCD（所有阻塞操作都在这）
# ================================================================
def serial_worker(ser, shared: Shared, predictor, hands_detector, polish_fn, args):
    rstate = "MENU"          # MENU | RECV（正在收 clip）| AUDIO（正在收麦克风PCM）
    jpegs: list[Optional[bytes]] = []
    last_det = ""
    gf_ts = deque(maxlen=30)  # GFRAME 时间戳，算预览帧率
    audio_pcm = bytearray()  # 语音模式累加 PCM 字节
    audio_rate = 16000

    def set_status(s: str):
        with shared.lock:
            shared.status = s

    def set_mode(m: str):
        with shared.lock:
            shared.mode = m

    def finalize():
        with shared.lock:
            words = list(shared.words)
        if not words:
            set_status("还没有词，继续比 L 采词")
            return                      # 不退回待机，避免双击大拇指来回切

        raw = " ".join(words)
        set_status(f"润色中: {raw} …")
        print(f"  🤖 润色: [{raw}] …")
        polished = raw
        if polish_fn:
            try:
                polished = polish_fn(raw)
            except Exception as e:
                print(f"  ⚠ 润色失败: {e}（用原始词序）")
        print(f"  ✅ 结果: {polished}")
        lcd_show(ser, args, "sign", polished)       # 绿屏「我想说」+ 润色句
        if args.spk:
            try:
                send_spk(ser, polished)
            except Exception as e:
                print(f"  ⚠ 语音输出失败: {e}")
        with shared.lock:
            shared.words.clear()
            shared.status = f"结果: {polished}"
            shared.mode = "待机"
            shared.result = polished
        ser.reset_input_buffer()   # 丢弃润色/发送期间堆积的旧预览帧，否则下一轮卡在补帧

    def do_emergency():
        ok = True
        try:
            from cloud.emergency import notify
            notify("🆘 听障用户紧急求助！")
            set_status("已发送紧急求助")
            print("  🚨 微信推送已发送")
        except Exception as e:
            ok = False
            set_status("求助推送失败")
            print(f"  ⚠ 推送失败: {e}")
        # 成功/失败都给屏反馈，并回未唤醒待机态（固件侧 palm 已置 awake=false）
        lcd_show(ser, args, "sos", "家人已收到通知" if ok else "发送失败，请重试")
        with shared.lock:
            shared.mode = "待机"
        ser.reset_input_buffer()   # 丢弃推送期间堆积的旧帧

    lcd_show(ser, args, "idle")    # 上电待机屏（青色「请比手势」）
    while shared.running:
        # 主线程请求（串口 I/O 全保留在本线程）
        if shared.req_clear:
            shared.req_clear = False
            with shared.lock:
                shared.words.clear()
                shared.status = "已清空词序列"
            print("  🧹 已清空词序列")

        try:
            raw = ser.readline()
        except Exception as e:
            print(f"  ⚠ 串口读异常: {e}", file=sys.stderr)
            time.sleep(0.1)
            continue
        if not raw:
            continue
        line = ANSI_RE.sub("", raw.decode("utf-8", errors="ignore")).strip()
        if not line:
            continue

        # ---- 菜单态灰度预览 ----
        mg = GFRAME_RE.match(line)
        if mg:
            try:
                b = base64.b64decode(mg.group(2))
                if len(b) == 9216:
                    with shared.lock:
                        shared.preview = np.frombuffer(b, np.uint8).reshape(96, 96).copy()
                        shared.cap_preview = None
            except Exception:
                pass
            gf_ts.append(time.time())
            if len(gf_ts) >= 2:
                with shared.lock:
                    shared.fps = (len(gf_ts) - 1) / (gf_ts[-1] - gf_ts[0] + 1e-6)
            continue

        # ---- 稳定手势 ----
        m_det = DET_RE.match(line)
        if m_det:
            g = m_det.group(1)
            conf = float(m_det.group(2))
            with shared.lock:
                shared.gesture = f"{GESTURE_CN.get(g, g)} {conf:.0%}"
                shared.gname = GESTURE_CN.get(g, g)
                shared.gconf = conf
            if g != last_det:
                last_det = g
                if g != "background":
                    print(f"  ✋ {GESTURE_CN.get(g, g)} ({conf:.2f})")
            continue

        # ---- 采集前 3-2-1 倒计时 ----
        if line.startswith("POSE"):
            parts = line.split()
            n = 0
            if len(parts) > 1:
                try:
                    n = int(parts[1])
                except ValueError:
                    n = 0
            with shared.lock:
                shared.countdown = n
            if n > 0:
                set_status(f"准备摆好手势 … {n}")
                lcd_cd(ser, args, n)                # 橙屏大倒计时数字
            else:
                set_status("采集中 …")
                lcd_body(ser, args, "recog", "采集中…")
            continue

        # ---- 事件 ----
        if line.startswith("EVT wake"):             # 👍 thumbup 待机唤醒
            set_mode("已唤醒")
            set_status("已唤醒：比 L 开始手语循环 / V 语音")
            print("  👍 唤醒")
            lcd_show(ser, args, "idle")             # 回待机屏（请比手势）
            continue

        if line.startswith("EVT finalize"):        # ✊ fist 结束自动循环
            print("  ✊ 结束 → 润色")
            finalize()
            continue

        if line.startswith("EVT voice"):           # ✌️ two = V
            set_mode("语音")
            set_status("语音模式：准备录音 …")
            print("  ✌️ V → 语音模式")
            rstate = "AUDIO"
            audio_pcm = bytearray()
            continue

        if rstate == "AUDIO":
            ma = AUDIO_START_RE.match(line)
            if ma:
                audio_rate = int(ma.group(1))
                audio_pcm = bytearray()
                set_status(f"录音中 @{audio_rate}Hz …")
                continue
            mc = AUDIO_CHUNK_RE.match(line)
            if mc:
                seq, total, nsamp = int(mc.group(1)), int(mc.group(2)), int(mc.group(3))
                try:
                    audio_pcm += base64.b64decode(mc.group(4))
                except Exception:
                    pass
                set_status(f"录音中 … {len(audio_pcm) // 2} 样本 (chunk {seq+1}/{total})")
                continue
            ma = AUDIO_END_RE.match(line)
            if ma:
                set_status("识别中 …")
                rstate = "MENU"
                if len(audio_pcm) > 0:
                    print(f"  🎙 收到 {len(audio_pcm) // 2} 样本 ({len(audio_pcm) / 2 / audio_rate:.1f}s)")
                    try:
                        # 转 WAV → 火山 ASR
                        import io, wave, struct
                        buf = io.BytesIO()
                        w = wave.open(buf, "wb")
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(audio_rate)
                        w.writeframes(audio_pcm); w.close()
                        wav = buf.getvalue()

                        from cloud.asr import transcribe
                        print("  🤖 ASR 识别中 …")
                        text = transcribe(wav, sample_rate=audio_rate, fmt="wav")
                        text = text or "（未识别到语音）"
                        print(f"  ✅ 识别: {text}")

                        lcd_show(ser, args, "speech", text)   # 蓝屏「对方说」+ 字幕
                        with shared.lock:
                            shared.status = f"语音: {text}"
                            shared.mode = "待机"
                            shared.result = f"[语音] {text}"
                    except Exception as e:
                        print(f"  ⚠ ASR 失败: {e}")
                        set_status(f"ASR 失败: {e}")
                        set_mode("待机")
                ser.reset_input_buffer()
                continue

        if line.startswith("EVT emergency"):        # 🖐 palm
            print("  🖐 五指 → 紧急求助")
            do_emergency()
            continue

        # ---- 手语采集流 ----
        if line.startswith("SIGN_BEGIN"):
            set_mode("手语识别")
            set_status("手语自动循环中…（比 👍 结束）")
            lcd_show(ser, args, "recog")           # 橙屏识别中（倒计时后只更新正文）
            rstate = "WAIT_CLIP"
            continue
        if line.startswith("SIGN_END"):
            with shared.lock:
                shared.cap_preview = None
                shared.progress = ""
                shared.countdown = 0
                shared.recv = 0
                shared.recv_phase = ""
            rstate = "MENU"
            last_det = ""
            continue
        if line.startswith("CLIP_START"):
            jpegs = [None] * SEQ_LEN
            rstate = "RECV"
            print(f"  ┌─ {line}")
            continue
        if line.startswith("CLIP_END"):
            if rstate == "RECV":
                got = sum(1 for j in jpegs if j is not None)
                print(f"  └─ {line} (实收 {got}/{SEQ_LEN})")
                if got >= SEQ_LEN * 0.6:
                    set_status("识别中…")
                    save_dir = None
                    if args.save:
                        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                        save_dir = PROJECT_ROOT / "captures" / ts
                    try:
                        word, conf = process_clip(jpegs, hands_detector, predictor, shared, save_dir)
                    except Exception as e:
                        traceback.print_exc()
                        set_status(f"识别异常（已跳过）: {e}")
                        word, conf = None, 0.0
                    if word is not None:
                        if conf >= args.conf:
                            with shared.lock:
                                shared.words.append(word)
                                acc = " ".join(shared.words)
                            set_status(f"识别: {word} {conf:.0%}  累计: {acc}")
                            print(f"  ➕ 累计: {acc}")
                        else:
                            set_status(f"{word} {conf:.0%} 置信低，跳过")
                else:
                    set_status(f"帧太少 {got}/{SEQ_LEN}，跳过")
            rstate = "MENU"
            continue
        if rstate == "RECV":
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
                    # 边收边显：解码这帧给窗口（彩色逐帧出现，不再卡灰图最后一闪）
                    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                    with shared.lock:
                        if img is not None:
                            shared.cap_preview = cv2.resize(img, (480, 360))
                        shared.progress = f"recv {got}/{SEQ_LEN}"
                        shared.recv = got
                        shared.recv_phase = "收帧"
                continue

        # 其他固件日志
        if line.startswith("debug:") or "term" in line.lower():
            print(f"  [esp] {line}", file=sys.stderr)


# ================================================================
#  主线程：OpenCV 窗口（永不阻塞）
# ================================================================
# ---- 信息操作版 调色板（BGR）----
_BG = (32, 28, 24); _CARD = (48, 42, 36); _CYAN = (216, 166, 6); _WHITE = (245, 245, 245)
_MUTE = (168, 158, 148); _GREEN = (122, 169, 31); _YELLOW = (40, 200, 240)
_NAVY = (150, 96, 28); _ORANGE = (60, 138, 240); _GRID = (92, 82, 72)
_MODE_COLOR = {"待机": (78, 70, 60), "已唤醒": (70, 120, 60),
               "手语识别": (150, 96, 28), "语音": (40, 96, 158)}

def _bar(canvas, x, y, w, h, frac, color, bg=(66, 60, 54)):
    frac = 0.0 if frac is None else max(0.0, min(1.0, frac))
    cv2.rectangle(canvas, (x, y), (x + w, y + h), bg, -1)
    if frac > 0:
        cv2.rectangle(canvas, (x, y), (x + int(w * frac), y + h), color, -1)

def _trunc(s, n):
    s = s or ""
    return s if len(s) <= n else s[:n - 1] + "…"

def build_canvas(shared: Shared):
    with shared.lock:
        if shared.cap_preview is not None:
            cam = shared.cap_preview.copy()
        else:
            cam = cv2.cvtColor(cv2.resize(shared.preview, (480, 360),
                               interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
        gname = shared.gname; gconf = shared.gconf
        mode = shared.mode; words = list(shared.words)
        status = shared.status; result = shared.result
        cd = shared.countdown; recv = shared.recv; phase = shared.recv_phase
        top3 = list(shared.top3); fps = shared.fps

    W, H = 960, 600
    canvas = np.full((H, W, 3), _BG, np.uint8)

    # ---- 摄像头 ----
    if cam.shape[:2] != (360, 480):
        cam = cv2.resize(cam, (480, 360))
    canvas[60:420, 16:496] = cam
    cv2.rectangle(canvas, (16, 60), (496, 420), _GRID, 1)
    if cd > 0:
        cv2.putText(canvas, str(cd), (205, 285), cv2.FONT_HERSHEY_SIMPLEX, 6.5, _YELLOW, 13)

    # ---- 头部 ----
    cv2.rectangle(canvas, (328, 12), (560, 44), _MODE_COLOR.get(mode, _CARD), -1)
    cv2.circle(canvas, (752, 30), 7, _GREEN, -1)

    # ---- 卡片底 ----
    for (x0, y0, x1, y1) in [(512, 60, 944, 168), (512, 180, 944, 260),
                             (512, 272, 944, 430), (512, 442, 944, 560),
                             (16, 432, 496, 556)]:
        cv2.rectangle(canvas, (x0, y0), (x1, y1), _CARD, -1)

    # ---- 实时手势置信度条 ----
    _bar(canvas, 524, 134, 404, 16, gconf, _GREEN if gconf >= 0.7 else _YELLOW)
    # ---- 采集进度条 ----
    _bar(canvas, 524, 226, 404, 18, (recv / SEQ_LEN) if SEQ_LEN else 0, _CYAN)
    # ---- top3 条 ----
    for i, (wd, pr) in enumerate(top3[:3]):
        ry = 316 + i * 36
        _bar(canvas, 600, ry, 230, 16, pr, _GREEN if i == 0 else _NAVY)

    # ---- 文本（CJK 一次画完）----
    items = [
        ("聆语 · 操作台", (16, 12), 26, _CYAN),
        (f"模式  {mode}", (340, 16), 21, _WHITE),
        (f"COM7 在线    {fps:.0f} fps", (768, 16), 17, _MUTE),
        ("实时手势", (524, 68), 17, _CYAN),
        (_trunc(gname, 8) or "—", (524, 92), 30, _WHITE),
        (f"{gconf:.0%}", (858, 96), 22, _GREEN if gconf >= 0.7 else _YELLOW),
        ("采集进度", (524, 188), 17, _CYAN),
        (f"{phase or '空闲'}   {recv}/{SEQ_LEN}", (740, 190), 17, _MUTE),
        ("识别 Top-3", (524, 280), 17, _CYAN),
        ("累计词", (28, 440), 17, _CYAN),
        (_trunc(' '.join(words), 16) if words else "—", (28, 466), 26, _YELLOW),
        ("最近结果", (28, 502), 17, _CYAN),
        (_trunc(result, 22) or "—", (28, 526), 20, _WHITE),
        ("手势速查", (524, 450), 17, _CYAN),
        (_trunc(status, 30), (16, 566), 15, _MUTE),
        ("[q]退出   [c]清空   [w]唤醒   [Enter]润色", (512, 570), 15, (150, 140, 130)),
    ]
    if not top3:
        items.append(("（尚无识别结果）", (600, 318), 17, _MUTE))
    else:
        for i, (wd, pr) in enumerate(top3[:3]):
            ry = 316 + i * 36
            items.append((_trunc(wd, 6), (524, ry - 4), 20, _WHITE if i == 0 else _MUTE))
            items.append((f"{pr:.0%}", (846, ry - 4), 15, _MUTE))
    for i, lg in enumerate(["thumbup(竖拇指)  →  唤醒", "one(比 L)  →  采一个词",
                            "fist(握拳)  →  结束润色", "two(V)  →  语音输入",
                            "palm(张掌)  →  紧急求助"]):
        items.append((lg, (524, 478 + i * 16), 14, _MUTE))

    return put_cjk_lines(canvas, items)


def main():
    ap = argparse.ArgumentParser(description="terminal 终端 PC 接收（3.1 手语识别）")
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--save", action="store_true", help="保存每帧 JPEG + 特征到 captures/")
    ap.add_argument("--no-polish", action="store_true", help="禁用大模型润色")
    ap.add_argument("--conf", type=float, default=0.6, help="累积词置信度门槛（默认 0.6）")
    ap.add_argument("--lcd", action="store_true",
                    help="把润色结果发到 LCD（需 terminal 固件已集成 LCD 收显，否则固件会忽略）")
    ap.add_argument("--lcd-size", type=int, default=28, help="LCD 字号（默认 28）")
    ap.add_argument("--spk", action="store_true",
                    help="润色句同步语音输出（edge_tts → 扬声器）")
    args = ap.parse_args()

    print("加载 LSTM 模型 …")
    predictor = load_predictor(PROJECT_ROOT / "lstm_models")
    print("加载 MediaPipe …")
    hands_detector = init_mediapipe()

    polish_fn = None
    if not args.no_polish:
        try:
            from cloud.polish import polish
            polish_fn = polish
            print("润色已启用")
        except Exception as e:
            print(f"⚠ 润色未启用: {e}")

    print(f"连接 {args.port} @ {args.baud} …")
    ser = serial.Serial(args.port, args.baud, timeout=0.1)
    time.sleep(0.5)
    ser.reset_input_buffer()
    print("✅ 已连接。流程：👍唤醒 → 比L 采一个词(倒数321) → 再比L 下一个 … → ✊fist 润色上LCD")
    print("   手势：👍thumbup=唤醒  L(one)=采一个词  V(two✌️)=语音  ✊fist=结束润色  🖐palm=求助")
    print("   窗口按键：q/ESC 退出 · c 清空\n")

    shared = Shared()
    worker = threading.Thread(
        target=serial_worker,
        args=(ser, shared, predictor, hands_detector, polish_fn, args),
        daemon=True,
    )
    worker.start()

    WIN = "Terminal"          # cv2 标题栏用 ASCII，避免乱码
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    try:
        while shared.running:
            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord("q")):
                break
            elif key == ord("c"):
                shared.req_clear = True
            try:
                cv2.imshow(WIN, build_canvas(shared))
            except Exception as e:
                print(f"⚠ 渲染异常: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，退出")
    finally:
        shared.running = False
        worker.join(timeout=1.0)
        ser.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
