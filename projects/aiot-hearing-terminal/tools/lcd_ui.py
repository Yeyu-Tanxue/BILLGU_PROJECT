# -*- coding: utf-8 -*-
"""
LCD 竖屏彩色 UI（240×320）—— PC 端组屏。

固件只认 3 个通用原语（见 esp32_firmware/terminal/main/lcd.c）：
  FILL <565>                          整屏填色
  RECT <x> <y> <w> <h> <565>          填矩形
  BMP  <x> <y> <w> <h> <rb> <fg565> <bg565> <b64-1bit>   贴 1-bit 位图（着色）
所有配色 / 布局 / 措辞都在本文件，改设计**不用重烧固件**。

状态：idle 待机 / recog 识别中 / sign 我想说 / speech 对方说 / sos 求助。
颜色编码即语义：青=就绪 橙=处理中 绿=你的表达 蓝=对方的话 红=警报。
"""
import base64
import os

from PIL import Image, ImageDraw, ImageFont

LCD_W, LCD_H, HEAD = 240, 320, 58
HINT_Y = LCD_H - 28


def _font_path():
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
              "C:/Windows/Fonts/simhei.ttf"):
        if os.path.exists(p):
            return p
    raise SystemExit("找不到中文字体（msyhbd/msyh/simhei）")


_FP = _font_path()
_FCACHE = {}


def font(sz):
    if sz not in _FCACHE:
        _FCACHE[sz] = ImageFont.truetype(_FP, sz)
    return _FCACHE[sz]


def to565(rgb):
    r, g, b = rgb
    return f"{(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)):04x}"


# 状态定义：bg 背景 / hd 顶栏 / tx 正文色（RGB888）/ icon / label / body(固定正文,None=动态) / hint
STATES = {
    "idle":   dict(bg=(14, 40, 54),  hd=(18, 120, 140), tx=(235, 245, 248), icon="hand",
                   label="待命中",   body="请比手势",     hint="拇指唤醒·V语音·张掌求助"),
    "recog":  dict(bg=(44, 32, 10),  hd=(224, 140, 30), tx=(255, 232, 190), icon="dots",
                   label="正在识别…", body=None,          hint="保持手势，正在采集"),
    "sign":   dict(bg=(10, 46, 30),  hd=(31, 168, 110), tx=(255, 255, 255), icon="check",
                   label="我想说",   body=None,           hint="已识别，正展示给对方"),
    "speech": dict(bg=(10, 30, 58),  hd=(46, 116, 192), tx=(255, 255, 255), icon="speech",
                   label="对方说",   body=None,           hint="对方语音已转文字"),
    "sos":    dict(bg=(52, 14, 18),  hd=(216, 58, 58),  tx=(255, 238, 238), icon="warn",
                   label="已发送求助", body="家人已收到通知", hint="微信通知已送达"),
}
HINT_COL = (170, 182, 192)


def _icon(d, kind, cx, cy, col=255):
    if kind == "dots":
        for i in (-1, 0, 1):
            d.ellipse([cx + i*13 - 4, cy - 4, cx + i*13 + 4, cy + 4], fill=col)
    elif kind == "check":
        d.line([(cx-11, cy), (cx-3, cy+9), (cx+12, cy-11)], fill=col, width=5)
    elif kind == "warn":
        d.polygon([(cx, cy-12), (cx+14, cy+11), (cx-14, cy+11)], outline=col, width=3)
        d.line([(cx, cy-3), (cx, cy+4)], fill=col, width=3)
        d.ellipse([cx-2, cy+7, cx+2, cy+11], fill=col)
    elif kind == "speech":
        d.rounded_rectangle([cx-14, cy-10, cx+14, cy+6], radius=6, outline=col, width=3)
        d.polygon([(cx-5, cy+5), (cx-11, cy+13), (cx-1, cy+6)], fill=col)
    elif kind == "hand":
        d.rounded_rectangle([cx-8, cy-5, cx+9, cy+12], radius=5, fill=col)
        for i in range(4):
            d.rounded_rectangle([cx-8+i*5, cy-15, cx-5+i*5, cy-3], radius=2, fill=col)


def _pack(img):
    """L 图 → (w, h, row_bytes, packed) 1-bit（>128 视为 1，高位在前）。"""
    px = img.load()
    w, h = img.size
    rb = (w + 7) // 8
    out = bytearray()
    for y in range(h):
        for xb in range(rb):
            byte = 0
            for b in range(8):
                x = xb * 8 + b
                if x < w and px[x, y] > 128:
                    byte |= 1 << (7 - b)
            out.append(byte)
    return w, h, rb, bytes(out)


_PROBE = ImageDraw.Draw(Image.new("L", (1, 1)))


def _wrap(text, fnt, maxw):
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for ch in para:
            if cur and _PROBE.textbbox((0, 0), cur + ch, font=fnt)[2] > maxw:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def _measure(text, sz, maxw, gap):
    f = font(sz)
    lines = _wrap(text, f, maxw)
    asc, desc = f.getmetrics()
    lh = asc + desc + gap
    bw = max((_PROBE.textbbox((0, 0), ln, font=f)[2] for ln in lines), default=1)
    return f, lines, lh, bw, lh * len(lines)


def _render_block(text, maxw, maxh, sizes, gap=8):
    """自动适配字号 + 折行，返回紧致 1-bit (w,h,rb,packed)。
    策略：**优先最少折行数**（短句压一行），再在该行数下取最大字号。"""
    min_lines = len(_wrap(text, font(sizes[-1]), maxw))   # 最小号 → 行数下限
    chosen = None
    for sz in sizes:                                       # 大 → 小
        f, lines, lh, bw, bh = _measure(text, sz, maxw, gap)
        if len(lines) <= min_lines and bh <= maxh and bw <= maxw:
            chosen = (f, lines, lh, bw, bh); break         # 行数最少且放得下的最大号
    if chosen is None:                                     # 放不下 → 退到能容下的最大号
        for sz in sizes:
            f, lines, lh, bw, bh = _measure(text, sz, maxw, gap)
            if bh <= maxh and bw <= maxw:
                chosen = (f, lines, lh, bw, bh); break
    if chosen is None:                                     # 仍放不下 → 最小号截断
        f, lines, lh, bw, bh = _measure(text, sizes[-1], maxw, gap)
        bw = min(bw, maxw); bh = min(bh, maxh)
        chosen = (f, lines, lh, bw, bh)
    f, lines, lh, bw, bh = chosen
    img = Image.new("L", (max(bw, 1), max(bh, 1)), 0)
    d = ImageDraw.Draw(img)
    y = 0
    for ln in lines:
        w = d.textbbox((0, 0), ln, font=f)[2]
        d.text(((bw - w) // 2, y), ln, font=f, fill=255)
        y += lh
    return _pack(img)


def _render_header(s):
    img = Image.new("L", (LCD_W, HEAD), 0)
    d = ImageDraw.Draw(img)
    _icon(d, s["icon"], 30, HEAD // 2, 255)
    f = font(27)
    d.text((54, HEAD / 2 - 17), s["label"], font=f, fill=255)
    lw = 54 + d.textbbox((0, 0), s["label"], font=f)[2] + 6
    return _pack(img.crop((0, 0, min(lw, LCD_W), HEAD)))


# ---------- 串口发送 ----------
def _send(ser, cmd):
    ser.write((cmd + "\n").encode("ascii"))
    ser.flush()


def _bmp(x, y, w, h, rb, fg, bg, packed):
    b64 = base64.b64encode(packed).decode("ascii")
    return f"BMP {int(x)} {int(y)} {w} {h} {rb} {fg} {bg} {b64}"


def show(ser, state, body=None):
    """整屏切到某状态。body 覆盖固定正文（如手语句 / 语音字幕）。"""
    s = STATES[state]
    bg, hd, tx = to565(s["bg"]), to565(s["hd"]), to565(s["tx"])
    _send(ser, f"FILL {bg}")
    _send(ser, f"RECT 0 0 {LCD_W} {HEAD} {hd}")
    hw, hh, hrb, hp = _render_header(s)
    _send(ser, _bmp(12, (HEAD - hh) // 2, hw, hh, hrb, "ffff", hd, hp))
    txt = body if body is not None else s["body"]
    body_bot = HINT_Y if s["hint"] else LCD_H
    if txt:
        bw, bh, brb, bp = _render_block(txt, LCD_W - 20, body_bot - HEAD - 8,
                                        [66, 58, 50, 42, 34, 28])
        bx = (LCD_W - bw) // 2
        by = HEAD + (body_bot - HEAD - bh) // 2
        _send(ser, _bmp(bx, by, bw, bh, brb, tx, bg, bp))
    if s["hint"]:
        hw2, hh2, hrb2, hp2 = _render_block(s["hint"], LCD_W - 10, 30, [18, 16, 14], gap=2)
        _send(ser, _bmp((LCD_W - hw2) // 2, HINT_Y, hw2, hh2, hrb2, to565(HINT_COL), bg, hp2))


def update_body(ser, state, text, big=False):
    """只重画正文区（不重填整屏，避免倒计时闪烁）。需先 show(state) 建好顶栏。"""
    s = STATES[state]
    bg, tx = to565(s["bg"]), to565(s["tx"])
    body_bot = HINT_Y if s["hint"] else LCD_H
    _send(ser, f"RECT 0 {HEAD} {LCD_W} {body_bot - HEAD} {bg}")
    sizes = [150, 120, 96] if big else [54, 46, 40, 34, 28]
    maxw = 130 if big else LCD_W - 20
    bw, bh, brb, bp = _render_block(text, maxw, body_bot - HEAD - 8, sizes)
    bx = (LCD_W - bw) // 2
    by = HEAD + (body_bot - HEAD - bh) // 2
    _send(ser, _bmp(bx, by, bw, bh, brb, tx, bg, bp))


def show_countdown(ser, n):
    update_body(ser, "recog", str(n), big=True)


# ---------- 离线预览（QA 用，不需串口）：把状态合成成彩色 PNG ----------
def _preview(state, body=None):
    s = STATES[state]
    img = Image.new("RGB", (LCD_W, LCD_H), s["bg"])
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, LCD_W, HEAD], fill=s["hd"])
    _icon(d, s["icon"], 30, HEAD // 2, (255, 255, 255))
    d.text((54, HEAD / 2 - 17), s["label"], font=font(27), fill=(255, 255, 255))
    txt = body if body is not None else s["body"]
    body_bot = HINT_Y if s["hint"] else LCD_H
    if txt:
        big = state == "recog" and txt.isdigit()
        sizes = [150, 120, 96] if big else [66, 58, 50, 42, 34, 28]
        maxw = 130 if big else LCD_W - 20
        bw, bh, brb, bp = _render_block(txt, maxw, body_bot - HEAD - 8, sizes)
        tmp = Image.frombytes("1", (brb * 8, bh), bp).convert("L").crop((0, 0, bw, bh))
        col = Image.new("RGB", (bw, bh), s["tx"])
        img.paste(col, ((LCD_W - bw) // 2, HEAD + (body_bot - HEAD - bh) // 2), tmp)
    if s["hint"]:
        hw, hh, hrb, hp = _render_block(s["hint"], LCD_W - 10, 30, [18, 16, 14], gap=2)
        tmp = Image.frombytes("1", (hrb * 8, hh), hp).convert("L").crop((0, 0, hw, hh))
        col = Image.new("RGB", (hw, hh), HINT_COL)
        img.paste(col, ((LCD_W - hw) // 2, HINT_Y), tmp)
    return img


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--preview":
        os.makedirs("_report_assets", exist_ok=True)
        demos = [("idle", None), ("recog", "3"), ("sign", "我想喝水"),
                 ("speech", "你好，请问需要什么帮助？"), ("sos", None)]
        pad = 16
        big = Image.new("RGB", (5 * LCD_W + 6 * pad, LCD_H + 2 * pad + 24), (245, 248, 251))
        bd = ImageDraw.Draw(big)
        bd.text((pad, 6), "lcd_ui.py 实际渲染（固件将这样上色显示）", font=font(20), fill=(20, 70, 110))
        for i, (st, bo) in enumerate(demos):
            big.paste(_preview(st, bo), (pad + i * (LCD_W + pad), 30 + pad))
        big.save("_report_assets/lcd_ui_render.png")
        print("saved _report_assets/lcd_ui_render.png")
    else:
        # 连板子循环演示：python tools/lcd_ui.py [COM7]
        import time
        import serial
        port = sys.argv[1] if len(sys.argv) > 1 else "COM7"
        ser = serial.Serial(port, 921600, timeout=1)
        time.sleep(1.5)
        show(ser, "idle"); time.sleep(2)
        show(ser, "recog")
        for n in (3, 2, 1):
            show_countdown(ser, n); time.sleep(0.7)
        update_body(ser, "recog", "采集中…"); time.sleep(1)
        show(ser, "sign", "我想喝水"); time.sleep(2.5)
        show(ser, "speech", "你好，请问需要什么帮助？"); time.sleep(2.5)
        show(ser, "sos"); time.sleep(2)
        show(ser, "idle")
        ser.close()
