# 听障双向沟通终端（基于云边协同的 AIoT 视觉康复交互终端）

ESP32-S3-CAM 边端采集 + PC/云端识别润色，帮听障人士「比手语 → 出通顺中文」。

> **当前进度：双向沟通终端全部跑通 ✅** — 手语(👍唤醒→比L采词→✊fist润色→LCD) + 语音(✌️V→录音→ASR→字幕LCD) + TTS(edge_tts→喇叭念出) + 紧急(🖐palm)
> 底层链路：比手语 → ESP32 拍 45 帧 → 串口传 PC → MediaPipe+LSTM 识别词 → 累积 → 火山大模型润色 → 自然句子。
> 实测「我 想 喝水」→「我想喝水」、「谢谢 你 帮助 我」→「谢谢你帮助我」，识别率 97-99%。

---

## 1. 工程结构：两半，靠 COM7 串口连起来

```
E:\ESP-S3\                          ← 项目根（打包/备份整个这个目录）
│
├─ esp32_firmware\        ESP32 固件（C / ESP-IDF v5.5.3）
│   ├─ terminal\          ★ 统一终端固件(手语+语音+TTS+紧急，演示烧这个)
│   │   └─ main\ main.cpp(手势CNN+唤醒状态机+切摄像头) · lcd.c(显示) · mic.c(录音) · spk.c(TTS播放)
│   ├─ gesture_cam\       端侧手势 CNN（也用于 collect_gesture 采集手势数据）
│   ├─ capture_for_lstm\  手语采集(纯拍45帧传PC，验证方案1)
│   └─ lcd_test\ mic_test\ spk_test\   单功能验证固件(LCD/麦克风/喇叭)
│
│        ↓↑  COM7 (CH340, 921600, base64 行协议；TX发帧 / RX收文字+音频 共用)
│
├─ tools\                 PC 端（conda split 环境）
│   ├─ terminal.py        ★ 终端总控(收帧→识别→润色→ASR→TTS→发LCD/SPK，两线程)
│   ├─ serial_recv_recognize.py  纯手语识别(早期，单跑方案1)
│   ├─ lcd_send.py(发中文上LCD) · voice_recv.py(收音验麦) · collect_gesture.py/gesture_monitor.py(手势)
│   └─ serial_diag.py/preview_clip.py/audio_recorder.py/terminal_debug.py  调试
│
├─ hand_features.py real_time_lstm.py        手语 LSTM 特征/推理（根目录，被 import）
├─ train_lstm_model.py train_gesture_cnn.py collect_lstm_data.py batch_collect.py  训练管线
├─ cloud\                云API：polish(润色) · asr(语音) · emergency(紧急) · config
├─ lstm_data\ gesture_data\     训练样本（irreplaceable，勿删）
├─ lstm_models\ gesture_models\ 训练好的模型
├─ .env                  密钥 ARK/ASR/SERVER_CHAN（TTS 用 edge_tts 免key）
└─ 项目现状与待办.md       ★ 完整决策记录 + 进度 + 待办
```

**关键**：`tools\terminal.py`（及 serial_recv_recognize.py）import 了根目录的 `hand_features`/`real_time_lstm`/`cloud`，
所以**必须在 `E:\ESP-S3\` 根目录下、用 split 环境跑**，不能单独搬走 tools\。

---

## 2. 从零跑起来（手语识别演示）

### 前置
- ESP-IDF v5.5.x（VSCode ESP-IDF 插件）
- Python 环境：`D:\anaconda3\envs\split\python.exe`（TF2.17 / mediapipe / opencv / pyserial / openai / python-dotenv）
- `.env` 里有 `ARK_API_KEY`（火山方舟密钥）
- ESP32-S3-CAM 通过 CH340 接 COM7

### 步骤
```
① 烧固件（VSCode 打开 esp32_firmware\capture_for_lstm）
   Set Target=esp32s3 → Flash Method=UART → Port=COM7 → Build → Flash
   （烧完别开 Monitor，会占用 COM7）

② 跑 PC 端识别+润色
   D:\anaconda3\envs\split\python.exe tools\serial_recv_recognize.py --save

③ 比手语
   看 [esp] POSE 3→2→1 倒计时摆好手势 → "采集中!" 保持 1.5 秒
   → 自动识别累计 → 比完一句【按回车】→ 大模型润色出句子
   （输入 c 回车=清空重来；Ctrl+C=退出）
```

详细参数 / 协议 / 排错见 `esp32_firmware\capture_for_lstm\README.md`。

---

## 3. 已完成 vs 待办（摘要，全文见 项目现状与待办.md）

**已完成 ✅**
- 摄像头 + 8MB PSRAM 硬件验证
- **手语识别端到端**：ESP32 拍 → COM7@921600 → MediaPipe+LSTM(28词,97-99%) → 累积 → Doubao 润色成句「我想喝水」。固件 capture_for_lstm，PC tools/serial_recv_recognize.py
- **端侧手势识别（边端AI）**：5手势(fist/one/thumbup/palm/background) 本地 CNN(INT8 100%) 实时识别。固件 gesture_cam，PC tools/gesture_monitor.py
- **语音识别 + TTS 上设备**：比 V → 板载麦(I2S, I2S_NUM_1)录5s → 豆包 ASR → 字幕上 LCD；TTS 用 edge_tts 生成 → SPK 命令 → 喇叭(I2S, I2S_NUM_0)念出来。模块 terminal/main/mic.c·spk.c，单测 mic_test/spk_test，PC tools/voice_recv.py
- **紧急求助**：Server酱→微信推送实测通 + 手势 palm 联动。cloud/emergency.py
- **功能整合 = 双向终端(全部实测通过)**：terminal 统一固件 —— 👍唤醒 → {L采词(倒数321,可重复)→✊fist润色→LCD ∣ V→录音→ASR→字幕} ∣ 🖐palm紧急；句子可 edge_tts 念出。模块 main.cpp+lcd.c+mic.c+spk.c，PC tools/terminal.py(两线程)
- **LCD 显示(L1+L2+整合)**：自写 ST7789 横屏驱动；PC→ESP32 串口通道(`uart_vfs_dev_use_driver` 解决控制台抢RX) + 中文 **PC渲染1-bit位图**(ESP32只贴图、不嵌字库、任意中文无豆腐块) + **固件原生横屏**。已并入 terminal，**润色句实时上屏**。固件 lcd_test/terminal，PC tools/lcd_send.py

**手势映射（6 类 CNN）**：👍thumbup→唤醒 / one→L采一个手语词 / ✊fist→结束润色 / ✌️two→V语音 / 🖐palm→紧急求助 / background→待机

**待办（功能已全通，剩收尾）**
- 手势 CNN 换 demo 环境前重采(train_gesture_cnn.py 已加亮度/对比度增广)；真 L 手势可选重训(现用 one 代)
- 外壳（猫型桌宠·LCD当脸横屏）、答辩材料（演示视频/PPT/剧本，主线讲双向闭环）

---

## 4. 重要提示

- **套件**：GOOUUU ESP32-S3-CAM + 扩展板(已含 2.0" LCD/数字麦克风/3W喇叭/电池/2按键)。引脚定义在 memory/board-pinmap.md
- **手势 6 类**：👍唤醒 / one=L采词 / ✊fist结束润色 / ✌️two=V语音 / 🖐palm求助。fist 换掉 thumbup 当"结束"(避免和手语「好/谢谢」竖拇指撞)，thumbup 改作唤醒
- **润色模型**用 `Doubao-Seed-1.6`（`doubao-1.6` 在本网关 403 无权限）；ASR 用独立 `ASR_API_KEY`(UUID)；**TTS 用 edge_tts**(免费免key，pip 装 edge_tts + miniaudio)
- **mic/spk 各占一个 I2S 实例**(NUM_1/NUM_0 不冲突)；I2S 缓冲须文件作用域 static(否则栈溢出反复重启)
- **波特率 921600** 是固件运行时 `uart_set_baudrate` 强制的，不靠 sdkconfig（VSCode build 会还原成 115200）
- **esp_lcd 组件被排除**（GCC ICE），LCD 用自写 SPI ST7789 驱动
- **lstm_data\ / gesture_data\ 是采集的训练样本，勿删**
- 项目定位/答辩要点/技术决策全在 `项目现状与待办.md`
