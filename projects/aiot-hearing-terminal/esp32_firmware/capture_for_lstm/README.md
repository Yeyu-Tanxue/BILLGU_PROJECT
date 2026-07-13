# capture_for_lstm — ESP32 实拍 → PC 手语识别（端到端）

ESP32-S3-CAM 自动循环采集 45 帧手语动作，经 **COM7 串口** 传到 PC，
PC 端 MediaPipe 抽手部关键点 → LSTM 推理 → 打印 top-3 识别结果。

> **状态：✅ 实测可用。** OV3660 实拍「我」MediaPipe 35/45 帧检测到手、识别 99%。
> 这是验证「方案1（ESP32 当采集器，识别在 PC/云端跑）」的端到端管线。

---

## 1. 硬件 / 环境

| 项 | 值 |
|---|---|
| 开发板 | 安信可 ESP32-S3-CAM（ESP32-S3-WROOM-1-N16R8，8MB PSRAM / 16MB Flash） |
| 摄像头 | OV3660（板载，DVP 排线；OV2640 同 PIN 也可） |
| 连接 | CH340 USB-UART → **COM7**，**921600**（烧录 + 日志 + 数据，同一条线） |
| 分辨率 | QVGA 320×240，JPEG quality 20（约 5-7KB/帧） |
| ESP-IDF | v5.5.3（VSCode ESP-IDF 插件） |
| PC Python | `D:\anaconda3\envs\split\python.exe`（TF 2.17 / mediapipe / opencv / pyserial） |

---

## 2. 编译 + 烧录（VSCode）

打开**本工程目录**（`File → Open Folder → capture_for_lstm`，不是上级目录）：

1. 底部状态栏 **Set Device Target** → `esp32s3`
2. **Select Flash Method** → **UART**（不要选 JTAG，会要 OpenOCD）
3. **Select Port** → `COM7`
4. **Build** 🔨 → **Flash** ⚡

烧录后**不要点 Monitor**（会占用 COM7，PC 脚本要用）。

---

## 3. 运行识别

PC 端（确保 COM7 没被 Monitor/别的程序占用）：

```powershell
D:\anaconda3\envs\split\python.exe E:\ESP-S3\tools\serial_recv_recognize.py --save
```

- 默认读 `COM7 @ 115200`，无需额外参数
- `--save`：把每组 45 帧原始 JPG 存到 `E:\ESP-S3\captures\<时间戳>\`（调试/复现用）

### 操作流程
1. 手心正对摄像头，距离 30–50cm，背景简单、光线均匀
2. 看 PC 端 `[esp] POSE 3 → 2 → 1` 倒计时摆好手势
3. 看到 `CLIP #N 采集中!` → **保持手势 1.5 秒**
4. 等传输（115200 下约 30 秒）+ 推理，看 top-3 结果
5. 自动进入下一组

### 预期输出
```
  [esp] ... POSE 3 ...
  [esp] ... POSE 1 ...
  [esp] ==== CLIP #1 采集中! 保持动作 1.5s ====
┌─ CLIP_START 45 ─────────
│  ... 45/45 frames
└─ CLIP_END 45 (实收 45/45)
  ━━━ 收齐 45/45 帧, 开始推理 ━━━
  📊 MediaPipe: 35/45 帧检测到手
  🎯 Top-3 识别结果：
     #1  [ 5] 我        99.0%  █████████████████████████████
     #2  [ 6] 你         0.5%
     #3  [ 8] 他         0.2%
```

---

## 4. 串口协议（全 ASCII 行）

```
CLIP_START <total>
FRAME <idx>/<total> <jpeg_len> <base64...>     ← 每帧一行
...
CLIP_END <got>
```

其余行是 ESP_LOG（含倒计时），PC 端剥掉 ANSI 颜色码后以 `[esp]` 显示。
PC 端解析见 `tools/serial_recv_recognize.py`。

---

## 5. 关键设计决策（踩坑记录，别走回头路）

| 决策 | 为什么 |
|---|---|
| **base64 + UART，不用二进制** | 纯 ASCII，无 CRLF 翻译 / 字节错位问题，稳定压倒一切 |
| **走 COM7，不用原生 USB(OTG)** | USB-Serial-JTAG 在本机 Windows 反复 PermissionError / halted 端点，调了很久放弃；COM7 实测稳定 99% |
| **自动倒计时，不用按键/PC 命令触发** | 在 console UART0 上装 driver 读 RX 会和控制台冲突，收不到命令 |
| **send_clip 每帧 `vTaskDelay(5ms)`** | 115200 下 printf busy-wait 慢，不让出 CPU 会饿死 IDLE → Task Watchdog 复位 |

---

## 6. 速度 / 已知限制

- **传输 ~4.5s/组**（921600 + base64 + q20，一组约 300KB）。已从最初 115200/q12 的 ~30s 提速 ~7x。
  - 波特率 921600 是**运行时 `uart_set_baudrate` 强制设置**（见 main.c app_main 开头），
    不靠 sdkconfig——因为 VSCode build 反复把 sdkconfig 的 baud 还原成 115200。
  - 还想更快（边际收益递减，非必要不做）：去 base64 改二进制(-25%) / 简单背景(帧更小) /
    2M baud(CH340 不一定稳) / 原生 USB-CDC(本机 Windows 上不稳，已放弃)。
  - 注意：单组延迟 = 采集1.5s + 传输4.5s + PC推理~2s，传输已非唯一大头。
- **取景敏感**：手必须在画面中央、完整。对准时识别 97-99%；没对准直接识错。
- **JPEG quality 20 不掉识别率**：实测「我」「对不起」均 97%+。MediaPipe 认手部轮廓，不需画质细节。

---

## 7. 配套文件

| 文件 | 作用 |
|---|---|
| `main/main.c` | 固件：采集 45 帧 + base64 串口发送 |
| `sdkconfig.defaults` | PSRAM Octal 8MB / 16MB Flash / UART 115200 |
| `tools/serial_recv_recognize.py` | **PC 端主程序**：串口收帧 → MediaPipe → LSTM → top-3 |
| `tools/preview_clip.py` | 把一组帧拼九宫格 + 叠加手部关键点，肉眼查画质 |
| `tools/serial_diag.py` | 串口诊断：抓原始字节 + 行分类统计 |
