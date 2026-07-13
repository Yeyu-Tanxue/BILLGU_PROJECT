# ============================================================
# 手部特征提取 (单一真相源 / single source of truth)
# 采集(collect_lstm_data) / 训练(train_lstm_model) / 预测(real_time_lstm)
# 三个脚本统一调用本模块, 保证特征定义完全一致。
# ============================================================
# 特征布局 (每只手 66 维, 双手 132 维):
#   [ 0:63]  21 个关键点相对手腕的 (x,y,z)  -> 手型, 平移不变
#   [63:66]  手腕(0号点)的绝对 (x,y,z)      -> 位置/指向信息
# 第二只手占 [66:132], 同样布局。检测不到的手填 0。
#
# 为什么保留手腕绝对坐标:
#   「我(指自己)/你(指对方)/他」这类手势手型几乎相同,
#   仅靠整只手在空间中的位置/朝向区分。纯手腕归一化会把
#   这部分信息消除掉, 导致它们无法区分。
#
# 为什么不做 per-sequence z-score 归一化:
#   静态手势在时间轴上方差≈0, z-score 会除以接近零的 std,
#   把抖动噪声放大成主导特征, 反而破坏静态手势。
#   手腕相对化后数值已在合理范围, 直接使用即可。
# ============================================================

import cv2
import numpy as np

SEQ_LEN      = 45    # 时序长度 (1.5 秒 @ 30fps)
PER_HAND_DIM = 66    # 每只手: 63 手型 + 3 手腕绝对
FEATURE_DIM  = 132   # 双手 2 × 66


def extract_hand_points(hand_landmarks):
    """从 MediaPipe 手部关键点提取 63 维原始 (x,y,z) 坐标。"""
    pts = np.zeros(63, dtype=np.float32)
    for i, lm in enumerate(hand_landmarks.landmark):
        pts[i * 3]     = lm.x
        pts[i * 3 + 1] = lm.y
        pts[i * 3 + 2] = lm.z
    return pts


def relative_to_wrist(pts):
    """减去手腕(0号点)坐标 -> 平移不变的手型特征 (63 维)。"""
    out = pts.copy()
    wx, wy, wz = pts[0], pts[1], pts[2]
    for i in range(21):
        out[i * 3]     -= wx
        out[i * 3 + 1] -= wy
        out[i * 3 + 2] -= wz
    return out


def extract_all_hands(frame, detector, max_hands=2):
    """
    从一帧图像提取双手特征。
    参数:
        frame:    BGR 图像 (OpenCV)
        detector: 已初始化的 mediapipe Hands 实例
    返回:
        (combined[FEATURE_DIM], hand_count, results)
        results 供调用方复用绘制骨架, 避免重复推理。
    """
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = detector.process(rgb)

    combined = np.zeros(FEATURE_DIM, dtype=np.float32)
    hand_count = 0

    if results.multi_hand_landmarks:
        hand_count = min(len(results.multi_hand_landmarks), max_hands)
        for h in range(hand_count):
            hand = results.multi_hand_landmarks[h]
            off = h * PER_HAND_DIM
            pts = extract_hand_points(hand)
            combined[off:off + 63]      = relative_to_wrist(pts)  # 手型(平移不变)
            combined[off + 63:off + 66] = pts[0:3]                # 手腕绝对(指向/位置)

    return combined, hand_count, results


def normalize_sequence(seq):
    """
    序列归一化。
    新方案不做 per-sequence z-score (见文件头说明),
    特征已在合理范围, 直接返回。保留此函数作为统一入口,
    便于将来需要时集中调整归一化策略。
    """
    return np.asarray(seq, dtype=np.float32)
