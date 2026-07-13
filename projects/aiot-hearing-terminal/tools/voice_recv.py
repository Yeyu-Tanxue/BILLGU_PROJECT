"""
voice_recv.py — 收 mic_test 固件的 PCM 流 → 存 WAV → 火山 ASR → 打印文字。
用来验证板载 I2S 麦克风 + 配置。

用法（split 环境）：
  python tools/voice_recv.py                 # 收音 → 存 WAV → ASR
  python tools/voice_recv.py --no-asr        # 只存 WAV（先听音质，不调 ASR）
  python tools/voice_recv.py --port COM7

每段录音存到 voice_caps/<时间戳>.wav（可拿播放器听）。
固件每 ~7s 自动录一段 4s，对着麦说话即可。
"""
from __future__ import annotations

import argparse, base64, io, math, re, struct, sys, time, wave
from pathlib import Path

import serial

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ANSI_RE  = re.compile(r"\x1b\[[0-9;]*m")
START_RE = re.compile(r"^AUDIO_START\s+(\d+)")
PCM_RE   = re.compile(r"^PCM\s+(.+)$")
END_RE   = re.compile(r"^AUDIO_END\s+(\d+)")


def _make_high_shelf(fc: float, gain_db: float, fs: int, q: float = 0.707):
    """RBJ biquad high-shelf 系数，返回 (b0,b1,b2,a1,a2) 已归一化"""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * fc / fs
    alpha = math.sin(w0) / (2.0 * q) * math.sqrt((A + 1.0 / A) * (1.0 / 1.0 - 1.0) + 2.0)
    cos_w0 = math.cos(w0)
    sqrt_A = math.sqrt(A)

    b0 = A * ((A + 1.0) - (A - 1.0) * cos_w0 + 2.0 * sqrt_A * alpha)
    b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w0)
    b2 = A * ((A + 1.0) - (A - 1.0) * cos_w0 - 2.0 * sqrt_A * alpha)
    a0 = (A + 1.0) + (A - 1.0) * cos_w0 + 2.0 * sqrt_A * alpha
    a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w0)
    a2 = (A + 1.0) + (A - 1.0) * cos_w0 - 2.0 * sqrt_A * alpha

    b0 /= a0
    b1 /= a0
    b2 /= a0
    a1 /= a0
    a2 /= a0
    # 返回时 a1 取负，方便差分方程 y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
    return (b0, b1, b2, -a1, -a2)


def apply_high_shelf(samples: list[int], fc: float, gain_db: float, fs: int) -> list[int]:
    """对 int16 样本列表施加高频搁架提升，返回新的 int16 列表"""
    if gain_db == 0.0:
        return samples
    b0, b1, b2, a1_p, a2_p = _make_high_shelf(fc, gain_db, fs)
    x1 = x2 = 0.0
    y1 = y2 = 0.0
    out = []
    for s in samples:
        x0 = float(s)
        y0 = b0 * x0 + b1 * x1 + b2 * x2 + a1_p * y1 + a2_p * y2
        # 软削波防爆音
        if y0 > 32760.0:
            y0 = 32760.0
        elif y0 < -32760.0:
            y0 = -32760.0
        out.append(int(y0))
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)       # mono
    w.setsampwidth(2)       # 16-bit
    w.setframerate(rate)
    w.writeframes(pcm)
    w.close()
    return buf.getvalue()


def handle_clip(pcm: bytes, rate: int, out_dir: Path, do_asr: bool,
                shelf_gain: float = 0.0, shelf_fc: float = 2000.0):
    n = len(pcm) // 2
    if n:
        samples = list(struct.unpack(f"<{n}h", pcm))
        if shelf_gain != 0.0:
            samples = apply_high_shelf(samples, shelf_fc, shelf_gain, rate)
        peak = max(abs(s) for s in samples)
        rms = (sum(s * s for s in samples) / n) ** 0.5
        pcm_out = struct.pack(f"<{n}h", *samples)
    else:
        peak = rms = 0
        pcm_out = pcm

    secs = n / rate
    wav = pcm_to_wav(pcm_out, rate)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"{time.strftime('%Y%m%d_%H%M%S')}.wav"
    wav_path.write_bytes(wav)

    tag = "  ⚠ 几乎静音（检查接线/声道/GAIN_SHIFT）" if peak < 200 else ""
    shelf_info = f"  shelf +{shelf_gain:.0f}dB @{shelf_fc:.0f}Hz" if shelf_gain != 0.0 else ""
    print(f"  💾 {wav_path.name}  {secs:.1f}s  peak={peak} rms={rms:.0f}{tag}{shelf_info}")

    if do_asr:
        try:
            from cloud.asr import transcribe
            print("  🤖 ASR 识别中 ...")
            text = transcribe(wav, sample_rate=rate, fmt="wav")
            print(f"  ✅ 识别: {text or '（空/静音）'}")
        except Exception as e:
            print(f"  ⚠ ASR 失败: {e}")



def main():
    ap = argparse.ArgumentParser(description="收 mic_test 音频 → WAV → ASR")
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--no-asr", action="store_true", help="只存 WAV，不调 ASR")
    ap.add_argument("--shelf-gain", type=float, default=9.0,
                    help="高频搁架增益 dB（默认 +9，0 关掉，6~12 范围）")
    ap.add_argument("--shelf-fc", type=float, default=2200.0,
                    help="搁架起始频率 Hz（默认 2200）")
    args = ap.parse_args()


    print(f"打开 {args.port} @ {args.baud}")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        sys.exit(f"打开串口失败：{e}（检查 COM 号 / Monitor 没占用）")

    out_dir = PROJECT_ROOT / "voice_caps"
    print("等录音段（固件每 ~7s 录 4s，对着麦说话）... Ctrl+C 退出\n")

    rate = 16000
    pcm = bytearray()
    receiving = False
    try:
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = ANSI_RE.sub("", raw.decode("utf-8", errors="ignore")).strip()
            if not line:
                continue
            m = START_RE.match(line)
            if m:
                rate = int(m.group(1)); pcm = bytearray(); receiving = True
                print(f"  🎙 录音中 @{rate}Hz ...")
                continue
            m = PCM_RE.match(line)
            if m and receiving:
                try:
                    pcm += base64.b64decode(m.group(1))
                except Exception:
                    pass
                continue
            m = END_RE.match(line)
            if m:
                receiving = False
                handle_clip(bytes(pcm), rate, out_dir, not args.no_asr,
                            shelf_gain=getattr(args, 'shelf_gain', 0.0),
                            shelf_fc=getattr(args, 'shelf_fc', 2000.0))
                print()
                continue
            # 其余固件输出全部显示（崩溃/重启原因不能被过滤掉）
            print(f"  [esp] {line[:160]}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n退出")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
