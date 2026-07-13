#!/usr/bin/env python3
"""
lcd_send.py — 把任意中文渲染成 1-bit 横屏位图，经 COM7 串口发给 ESP32 LCD 显示。
配合固件 esp32_firmware/lcd_test（原生横屏 320×240，黑底白字）。

职责划分：PC 负责排版（按 320 宽折行/居中），ESP32 收到后内部转 90° 贴到物理竖屏，
屏横着摆即为正。任意中文/标点/换行都不会出豆腐块。

用法（用 split 环境的 python）：
  单句：  python tools/lcd_send.py "我想喝水"
  交互：  python tools/lcd_send.py                （回车一句显示一句；clr 清屏；q 退出）
  调参：  python tools/lcd_send.py "你好" --port COM7 --baud 115200 --size 28

协议（与 lcd_test 固件配对，w/h 为"上正横屏"尺寸 w≤320 h≤240）：
  TXT <w> <h> <row_bytes> <base64-1bit>\\n   横屏黑底白字居中
  CLR\\n                                       清屏
"""
import argparse, base64, os, sys, time
from PIL import Image, ImageDraw, ImageFont
import serial

SCREEN_W, SCREEN_H = 320, 240   # 横屏逻辑帧（固件内部转 90° 贴到物理 240×320 竖屏）
MARGIN = 4                      # 左右各留边（像素）
LINE_GAP = 4                    # 行间距（像素）


def find_cjk_font():
    for p in ("C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
              "C:/Windows/Fonts/simhei.ttf",    # 黑体
              "C:/Windows/Fonts/simsun.ttc",    # 宋体
              "C:/Windows/Fonts/Deng.ttf"):     # 等线
        if os.path.exists(p):
            return p
    sys.exit("找不到中文字体（C:/Windows/Fonts 下的 msyh/simhei/simsun）")


def _text_w(draw, s, font):
    if not s:
        return 0
    b = draw.textbbox((0, 0), s, font=font)
    return b[2] - b[0]


def wrap_lines(text, font, max_w):
    """中文按像素宽度逐字折行；保留显式 \\n。"""
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    lines = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if cur and _text_w(draw, cur + ch, font) > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)            # 段末（含空段，作空行）
    return lines


def render_1bit(text, font_size):
    """返回 (w, h, row_bytes, packed_bytes)：上正横屏、黑底(0) 白字(1) 的 1-bit 位图。"""
    font = ImageFont.truetype(find_cjk_font(), font_size)
    lines = wrap_lines(text, font, SCREEN_W - 2 * MARGIN)

    asc, desc = font.getmetrics()
    line_h = asc + desc + LINE_GAP

    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    widths = [_text_w(probe, ln, font) for ln in lines]
    blk_w = min(max(widths) if widths else 1, SCREEN_W)
    blk_h = min(line_h * len(lines), SCREEN_H)

    img = Image.new("L", (blk_w, blk_h), 0)          # 黑底
    d = ImageDraw.Draw(img)
    y = 0
    for ln in lines:
        w = _text_w(d, ln, font)
        d.text(((blk_w - w) // 2, y), ln, font=font, fill=255)   # 白字、行内居中
        y += line_h

    px = img.load()
    w, h = img.size
    rb = (w + 7) // 8
    packed = bytearray()
    for yy in range(h):
        for xb in range(rb):
            byte = 0
            for b in range(8):
                xx = xb * 8 + b
                if xx < w and px[xx, yy] > 128:
                    byte |= 1 << (7 - b)
            packed.append(byte)
    return w, h, rb, bytes(packed)


def send_text(ser, text, font_size):
    w, h, rb, packed = render_1bit(text, font_size)
    b64 = base64.b64encode(packed).decode("ascii")
    ser.write(f"TXT {w} {h} {rb} {b64}\n".encode("ascii"))
    ser.flush()
    print(f"已发送 {w}x{h}(横屏) ({len(packed)}B → base64 {len(b64)}B): {text}")


def main():
    ap = argparse.ArgumentParser(description="把中文发到 ESP32 LCD 横屏显示")
    ap.add_argument("text", nargs="?", help="要显示的中文；省略则进入交互模式")
    ap.add_argument("--port", default="COM7", help="串口号（默认 COM7）")
    ap.add_argument("--baud", type=int, default=115200, help="波特率（默认 115200，与 lcd_test 一致）")
    ap.add_argument("--size", type=int, default=28, help="字号 px（默认 28）")
    ap.add_argument("--settle", type=float, default=1.5,
                    help="开口后等待秒数，让开口可能触发的板子复位完成（默认 1.5）")
    args = ap.parse_args()

    print(f"打开 {args.port} @ {args.baud}")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        sys.exit(f"打开串口失败：{e}\n  检查：1) 串口号；2) VSCode Monitor/别的脚本没占用 {args.port}")

    time.sleep(args.settle)        # 开口可能触发 CH340 自动复位，等固件起来

    try:
        if args.text is not None:
            send_text(ser, args.text, args.size)
        else:
            print("交互模式（横屏）：输入中文回车显示；clr=清屏；q=退出")
            while True:
                try:
                    s = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if s in ("q", "quit", "exit"):
                    break
                if not s:
                    continue
                if s.lower() == "clr":
                    ser.write(b"CLR\n"); ser.flush(); print("已清屏")
                    continue
                send_text(ser, s, args.size)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
