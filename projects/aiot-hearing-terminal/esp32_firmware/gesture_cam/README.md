# gesture_cam — 端侧手势识别（灰度采集 + 后续端侧推理）

ESP32-S3-CAM 灰度 96×96 摄像头管线。**阶段一**：连续输出灰度帧给 PC 采集训练数据。
**阶段二**（后续）：在此固件加 esp-tflite-micro，本地实时推理手势（唤醒 / 选模式）。

> 与云端「手语识别」(capture_for_lstm) 区分：
> - 手语：连续动作 → 云端 LSTM（已完成）
> - 手势：静态简单手势 → **ESP32 本地 CNN** 实时跑，体现边端 AI

---

## 阶段一：采集数据

### 1. 烧固件
VSCode 打开 `esp32_firmware/gesture_cam` → Target=esp32s3 → Flash Method=UART → Port=COM7 → Build → Flash。
（烧完别开 Monitor，会占 COM7）

### 2. 每个手势采一批
```powershell
D:\anaconda3\envs\split\python.exe E:\ESP-S3\tools\collect_gesture.py --label fist
D:\anaconda3\envs\split\python.exe E:\ESP-S3\tools\collect_gesture.py --label palm
D:\anaconda3\envs\split\python.exe E:\ESP-S3\tools\collect_gesture.py --label thumbup
...
D:\anaconda3\envs\split\python.exe E:\ESP-S3\tools\collect_gesture.py --label background   # 无手/杂乱背景，必采！
```
- 弹预览窗：手放画面里做该手势，**移动 / 转动 / 远近 / 换光照**采多样本
- **空格** 暂停/继续保存（重新摆位时先暂停）；**q** 结束
- 每类建议 **300-500 张**，存到 `gesture_data/<label>/`

### 3. 选手势的建议
96×96 灰度下，**形状区分明显**的最稳（别用细手指数量区分）：
- ✊ 握拳（紧凑团块）/ 🖐 张掌（散开）/ 👍 竖拇指（竖直突起）/ 🤙 等
- **必须有 `background` 类**（无手 / 杂乱背景），否则没手时会乱触发

---

## 协议

```
GFRAME <len> <base64>     每帧一行，len=9216（96×96 灰度原始字节）
```
其余行是 ESP_LOG，PC 端按 [esp] 显示。波特率运行时强制 921600（同 capture_for_lstm）。

---

## 文件
| 文件 | 作用 |
|---|---|
| `main/main.c` | 灰度 96×96 连续串口流（阶段二在此加 TFLite Micro 推理）|
| `../../tools/collect_gesture.py` | PC 采集脚本（预览 + 存 PNG）|
| `../../gesture_data/<label>/` | 采集输出（训练用）|

下一步（采够数据后）：`train_gesture_cnn.py` 训 CNN → INT8 TFLite → 回烧本固件做端侧推理。
