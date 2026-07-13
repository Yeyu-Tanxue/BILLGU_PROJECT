"""
terminal 调试接收 —— 极小化，只打印 debug: 和 det: 行，921600 串口。
用法：D:\anaconda3\envs\split\python.exe tools\terminal_debug.py
"""
import serial, sys

ser = serial.Serial("COM7", 921600, timeout=0.5)
print("已连接 COM7 @921600，等待 debug: / det: 行...\n", flush=True)

try:
    while True:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        # 只显示 debug 和 det 行
        if line.startswith("debug:") or line.startswith("det:"):
            print(line, flush=True)
except KeyboardInterrupt:
    print("\n退出")
    ser.close()