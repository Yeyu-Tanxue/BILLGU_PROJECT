# ============================================================
# LSTM 手语识别模型训练器
# 输入: MediaPipe 手部关键点时序数据 (T x 132)  双手 ×(63手型+3手腕绝对)
# 输出: 手势分类 (10~50 个手势)
# ============================================================
# 功能:
#   1. 从 lstm_data/ 加载采集的 .npy 数据
#   2. 构建双向 LSTM 模型
#   3. 训练 + 评估 + 保存模型
#   4. 转换为 TFLite (供 ESP32-S3 部署)
#   5. 导出 C 头文件 (供 ESP-IDF 使用)
# ============================================================

import numpy as np
import os
import sys
import json
import time
from pathlib import Path

# Windows 控制台 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ============================================================
# 配置
# ============================================================
DATA_DIR = "lstm_data"
MODEL_DIR = "lstm_models"
LABEL_MAP_FILE = "label_map.json"

# 模型参数 (特征维度来自共享模块 hand_features, 保证三方一致)
from hand_features import SEQ_LEN, FEATURE_DIM, normalize_sequence as hf_normalize_sequence
# SEQ_LEN = 45         # 时序长度 (1.5 秒 @ 30fps)
# FEATURE_DIM = 132    # 双手 × (63 手型 + 3 手腕绝对坐标)
HIDDEN_UNITS = 64      # LSTM 隐藏单元数
NUM_EPOCHS = 200       # 最大训练轮数
EARLY_STOP_PATIENCE = 30  # 早停耐心值
BATCH_SIZE = 16        # 批大小
LEARNING_RATE = 0.001  # 学习率
VAL_SPLIT = 0.15       # 验证集比例
TEST_SPLIT = 0.15      # 测试集比例

# 数据增广参数
USE_AUGMENTATION = True

# ============================================================
# 数据加载
# ============================================================

def load_label_map():
    path = os.path.join(DATA_DIR, LABEL_MAP_FILE)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_all_data(data_dir=DATA_DIR, use_aug=USE_AUGMENTATION):
    """
    加载所有手势数据。
    返回:
        X: N x T x 84 numpy array
        y: N numpy array (标签 ID)
        label_names: dict {id: name}
    """
    label_map = load_label_map()
    if not label_map:
        print("  ❌ 未找到标签映射文件! 请先运行 collect_lstm_data.py 采集数据")
        return None, None, None

    X_list = []
    y_list = []
    label_names = {}

    for lid_str, lname in sorted(label_map.items(), key=lambda x: int(x[0])):
        lid = int(lid_str)
        label_names[lid] = lname
        
        # 加载原始数据
        data_file = os.path.join(data_dir, f"gesture_{lid:03d}.npy")
        if os.path.exists(data_file):
            data = np.load(data_file, allow_pickle=True)
            if data.ndim == 3:  # N x T x 132
                X_list.append(data)
                y_list.append(np.full(data.shape[0], lid))
                print(f"    【{lname}】(ID={lid}): {data.shape[0]} 组原始样本")
        
        # 加载增广数据
        if use_aug:
            aug_file = os.path.join(data_dir, f"gesture_{lid:03d}_aug.npy")
            if os.path.exists(aug_file):
                aug_data = np.load(aug_file, allow_pickle=True)
                if aug_data.ndim == 3:
                    X_list.append(aug_data)
                    y_list.append(np.full(aug_data.shape[0], lid))
                    print(f"       + {aug_data.shape[0]} 组增广样本")

    if not X_list:
        print("  ❌ 未找到数据文件! 请先运行 collect_lstm_data.py")
        return None, None, None

    X = np.vstack(X_list).astype(np.float32)
    y = np.concatenate(y_list).astype(np.int32)

    print(f"\n  📊 数据汇总:")
    print(f"    样本总数: {X.shape[0]}")
    print(f"    特征维度: {X.shape[1]} 帧 × {X.shape[2]} 维")
    print(f"    手势类别: {len(label_names)} 个")

    return X, y, label_names


def normalize_sequences(X):
    """
    对时序数据进行归一化 (调用共享模块, 与采集/预测一致)。
    新方案不做 per-sequence z-score: 静态手势时间轴方差≈0, z-score
    会放大噪声并抹掉手腕绝对位置(指向信息)。详见 hand_features.py。
    """
    return hf_normalize_sequence(X)


def compute_class_weights(y):
    """
    计算类别权重 (处理样本不平衡)
    """
    classes = np.unique(y)
    n_samples = len(y)
    n_classes = len(classes)
    
    weights = {}
    for c in classes:
        n_c = np.sum(y == c)
        weights[c] = n_samples / (n_classes * n_c)
    
    return weights


# ============================================================
# 模型构建
# ============================================================

def build_lstm_model(num_classes, input_shape=(SEQ_LEN, FEATURE_DIM)):
    """
    构建双向 LSTM 分类模型。
    
    架构:
        - 双向 LSTM(64) → Dropout(0.3)
        - 双向 LSTM(32) → Dropout(0.3)
        - 全连接(64) → ReLU → Dropout(0.5)
        - 全连接(num_classes) → Softmax
    """
    import tensorflow as tf
    from tensorflow import keras
    from keras import layers, models, regularizers

    inputs = layers.Input(shape=input_shape, name="landmark_sequence")

    # 第一层双向 LSTM
    x = layers.Bidirectional(
        layers.LSTM(HIDDEN_UNITS, return_sequences=True,
                    kernel_regularizer=regularizers.l2(1e-4)),
        name="bilstm_1"
    )(inputs)
    x = layers.BatchNormalization(name="bn_1")(x)
    x = layers.Dropout(0.3, name="dropout_1")(x)

    # 第二层双向 LSTM
    x = layers.Bidirectional(
        layers.LSTM(HIDDEN_UNITS // 2, return_sequences=False,
                    kernel_regularizer=regularizers.l2(1e-4)),
        name="bilstm_2"
    )(x)
    x = layers.BatchNormalization(name="bn_2")(x)
    x = layers.Dropout(0.3, name="dropout_2")(x)

    # 全连接层
    x = layers.Dense(64, activation="relu",
                     kernel_regularizer=regularizers.l2(1e-4),
                     name="dense_1")(x)
    x = layers.BatchNormalization(name="bn_3")(x)
    x = layers.Dropout(0.5, name="dropout_3")(x)

    # 输出层
    outputs = layers.Dense(num_classes, activation="softmax",
                           name="output")(x)

    model = models.Model(inputs=inputs, outputs=outputs, name="sign_lstm")

    return model


def build_conv_lstm_model(num_classes, input_shape=(SEQ_LEN, FEATURE_DIM)):
    """
    构建 Conv1D + LSTM 混合模型。
    先用 1D 卷积提取局部空间特征, 再用 LSTM 建模时序。
    """
    import tensorflow as tf
    from tensorflow import keras
    from keras import layers, models, regularizers

    inputs = layers.Input(shape=input_shape, name="landmark_sequence")

    # Conv1D 块 1
    x = layers.Conv1D(32, kernel_size=3, padding="same", 
                      kernel_regularizer=regularizers.l2(1e-4),
                      name="conv_1")(inputs)
    x = layers.BatchNormalization(name="conv_bn_1")(x)
    x = layers.Activation("relu")(x)
    x = layers.MaxPooling1D(pool_size=2, name="pool_1")(x)
    x = layers.Dropout(0.2, name="conv_drop_1")(x)

    # Conv1D 块 2
    x = layers.Conv1D(64, kernel_size=3, padding="same",
                      kernel_regularizer=regularizers.l2(1e-4),
                      name="conv_2")(x)
    x = layers.BatchNormalization(name="conv_bn_2")(x)
    x = layers.Activation("relu")(x)
    x = layers.MaxPooling1D(pool_size=2, name="pool_2")(x)
    x = layers.Dropout(0.2, name="conv_drop_2")(x)

    # 单向 LSTM (更轻量)
    x = layers.LSTM(64, return_sequences=False,
                    kernel_regularizer=regularizers.l2(1e-4),
                    name="lstm")(x)
    x = layers.BatchNormalization(name="lstm_bn")(x)
    x = layers.Dropout(0.4, name="lstm_drop")(x)

    # 输出
    x = layers.Dense(32, activation="relu",
                     kernel_regularizer=regularizers.l2(1e-4),
                     name="dense")(x)
    x = layers.Dropout(0.3, name="dense_drop")(x)
    outputs = layers.Dense(num_classes, activation="softmax", name="output")(x)

    model = models.Model(inputs=inputs, outputs=outputs, name="sign_conv_lstm")
    return model


# ============================================================
# 训练
# ============================================================

def train_model(model_name="bilstm"):
    """训练主流程"""
    import tensorflow as tf
    from tensorflow import keras
    from keras import callbacks as cb

    os.makedirs(MODEL_DIR, exist_ok=True)

    # ——— 加载数据 ———
    print("\n  📂 加载数据...")
    X, y, label_names = load_all_data()
    if X is None:
        return

    num_classes = len(label_names)
    print(f"    类别数: {num_classes}")

    # ——— 归一化 ———
    print("  📐 归一化...")
    X = normalize_sequences(X)

    # ——— 数据集划分 ———
    print("  ✂️ 划分数据集...")
    from sklearn.model_selection import train_test_split
    
    # 先分出测试集
    X_train_val, X_test, y_train_val, y_test = train_test_split(
        X, y, test_size=TEST_SPLIT, random_state=42, stratify=y
    )
    
    # 再分出验证集
    val_ratio_adjusted = VAL_SPLIT / (1 - TEST_SPLIT)
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_val, y_train_val, test_size=val_ratio_adjusted,
        random_state=42, stratify=y_train_val
    )

    print(f"    训练集: {X_train.shape[0]} 组")
    print(f"    验证集: {X_val.shape[0]} 组")
    print(f"    测试集: {X_test.shape[0]} 组")

    # ——— 类别权重 ———
    class_weights = compute_class_weights(y_train)
    
    # ——— 构建模型 ———
    print(f"\n  🏗️ 构建模型 ({model_name})...")
    
    if model_name == "conv_lstm":
        model = build_conv_lstm_model(num_classes)
    else:
        model = build_lstm_model(num_classes)

    # 打印模型结构
    model.summary()

    # ——— 编译 ———
    optimizer = keras.optimizers.Adam(learning_rate=LEARNING_RATE)
    model.compile(
        optimizer=optimizer,
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy", 
                 tf.keras.metrics.SparseTopKCategoricalAccuracy(k=3, name="top3_accuracy")],
    )

    # ——— 回调 ———
    callbacks = [
        cb.EarlyStopping(
            monitor="val_loss",
            patience=EARLY_STOP_PATIENCE,
            restore_best_weights=True,
            verbose=1,
        ),
        cb.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=10,
            min_lr=1e-6,
            verbose=1,
        ),
        cb.ModelCheckpoint(
            filepath=os.path.join(MODEL_DIR, "best_model.keras"),
            monitor="val_accuracy",
            save_best_only=True,
            verbose=1,
        ),
        cb.CSVLogger(os.path.join(MODEL_DIR, "training_log.csv")),
    ]

    # ——— 训练 ———
    print(f"\n  🚀 开始训练 ({NUM_EPOCHS} epochs)...")
    start_time = time.time()
    
    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=NUM_EPOCHS,
        batch_size=BATCH_SIZE,
        class_weight=class_weights,
        callbacks=callbacks,
        verbose=2,
    )
    
    training_time = time.time() - start_time
    print(f"\n  ✅ 训练完成! 耗时: {training_time:.1f} 秒 ({training_time/60:.1f} 分钟)")

    # ——— 测试集评估 ———
    print(f"\n  🧪 测试集评估...")
    test_loss, test_acc, test_top3 = model.evaluate(X_test, y_test, verbose=0)
    print(f"    测试集 Top-1 准确率: {test_acc*100:.2f}%")
    print(f"    测试集 Top-3 准确率: {test_top3*100:.2f}%")
    print(f"    测试集 Loss: {test_loss:.4f}")

    # ——— 保存模型 ———
    model_path = os.path.join(MODEL_DIR, "final_model.keras")
    model.save(model_path)
    print(f"\n  💾 模型已保存:")
    print(f"    Keras 模型: {model_path}")

    # ——— 导出类别映射 ———
    id_to_name = {str(k): v for k, v in label_names.items()}
    class_map_path = os.path.join(MODEL_DIR, "class_map.json")
    with open(class_map_path, "w", encoding="utf-8") as f:
        json.dump({"id_to_name": id_to_name, "name_to_id": {v: k for k, v in label_names.items()}},
                  f, ensure_ascii=False, indent=2)
    print(f"    类别映射: {class_map_path}")

    # ——— 转换为 TFLite (传入训练数据做 int8 量化校准) ———
    convert_to_tflite(model, label_names, calibration_data=X_train)

    # ——— 转换为 TFLite Micro C 头文件 ———
    convert_to_c_array(model, label_names)

    return model, history


# ============================================================
# TFLite 转换
# ============================================================

def convert_to_tflite(model, label_names, calibration_data=None):
    """将 Keras 模型转换为 TFLite"""
    import tensorflow as tf

    print(f"\n  🔄 转换为 TFLite...")
    
    # 标准转换 (FP32)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS,
        tf.lite.OpsSet.SELECT_TF_OPS,  # 支持 LSTM ops
    ]
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    
    tflite_model = converter.convert()
    
    tflite_path = os.path.join(MODEL_DIR, "model.tflite")
    with open(tflite_path, "wb") as f:
        f.write(tflite_model)
    
    size_kb = len(tflite_model) / 1024
    print(f"    TFLite FP32: {tflite_path} ({size_kb:.1f} KB)")
    
    # 量化版本 (int8 量化, 使用真实数据进行校准)
    print("  🔄 转换量化版本 (int8)...")
    
    # 准备校准数据
    calib_data = calibration_data
    if calib_data is None:
        # 如果没有传入校准数据，从数据目录加载
        try:
            X_cal, _, _ = load_all_data()
            if X_cal is not None:
                X_cal = normalize_sequences(X_cal)
                calib_data = X_cal
                print(f"    校准数据: {calib_data.shape[0]} 组 (从文件加载)")
        except Exception as e:
            print(f"    ⚠️ 加载校准数据失败: {e}")
    
    # 准备量化转换器
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS_INT8,
        tf.lite.OpsSet.SELECT_TF_OPS,
    ]
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    
    # 使用真实数据校准 (关键修复!)
    if calib_data is not None and calib_data.shape[0] > 0:
        n_calib = min(200, calib_data.shape[0])
        print(f"    ✅ 使用 {n_calib} 组真实数据进行 int8 校准")
        
        # 注意: 这里用 closure 捕获 calib_data 的切片，避免外部变量引用
        calib_samples = calib_data[:n_calib].copy()
        def representative_dataset():
            for i in range(n_calib):
                yield [calib_samples[i:i+1].astype(np.float32)]
    else:
        # 兜底: 用均值数据
        print("    ⚠️ 无校准数据，使用零值兜底")
        def representative_dataset():
            for _ in range(100):
                yield [np.zeros((1, SEQ_LEN, FEATURE_DIM), dtype=np.float32)]
    
    converter.representative_dataset = representative_dataset
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS_INT8,
        tf.lite.OpsSet.SELECT_TF_OPS,
    ]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    
    try:
        tflite_quant_model = converter.convert()
        tflite_quant_path = os.path.join(MODEL_DIR, "model_quant.tflite")
        with open(tflite_quant_path, "wb") as f:
            f.write(tflite_quant_model)
        size_kb_q = len(tflite_quant_model) / 1024
        print(f"    TFLite INT8: {tflite_quant_path} ({size_kb_q:.1f} KB)")
    except Exception as e:
        print(f"    ⚠️ 量化转换失败: {e}")
        print("    (量化版本非必需, 继续使用 FP32 版本)")


# ============================================================
# 导出 C 头文件 (TFLite Micro)
# ============================================================

def convert_to_c_array(model, label_names, filename="gesture_model.h"):
    """将 TFLite 模型转换为 C 字节数组头文件"""
    import tensorflow as tf
    
    tflite_path = os.path.join(MODEL_DIR, "model.tflite")
    if not os.path.exists(tflite_path):
        print(f"\n  ⚠️ TFLite 模型不存在, 跳过 C 头文件导出")
        return
    
    print(f"\n  🔄 导出 C 头文件...")
    
    with open(tflite_path, "rb") as f:
        tflite_bytes = f.read()
    
    # 生成 C 数组
    c_array = ",\n  ".join(
        ", ".join(f"0x{b:02x}" for b in tflite_bytes[i:i+12])
        for i in range(0, len(tflite_bytes), 12)
    )
    
    # 生成标签枚举
    sorted_labels = sorted(label_names.items(), key=lambda x: int(x[0]))
    label_enum = ",\n  ".join(
        f"GESTURE_{v.upper()} = {k}" for k, v in sorted_labels
    )
    
    # 生成标签名称数组
    label_names_array = ",\n  ".join(
        f'    "{v}"' for _, v in sorted_labels
    )
    
    header_content = f"""// ============================================================
// 自动生成的 LSTM 手语识别模型 (TFLite Micro)
// 模型大小: {len(tflite_bytes)} 字节 ({len(tflite_bytes)/1024:.1f} KB)
// 输入: {SEQ_LEN} 帧 × {FEATURE_DIM} 维 (双手 MediaPipe 关键点)
// 输出: {len(label_names)} 个手势类别
// 生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}
// ============================================================

#ifndef GESTURE_MODEL_H
#define GESTURE_MODEL_H

#include <stdint.h>

// ============================================================
// 模型参数
// ============================================================
#define GESTURE_SEQ_LEN      {SEQ_LEN}
#define GESTURE_FEATURE_DIM  {FEATURE_DIM}
#define GESTURE_NUM_CLASSES  {len(label_names)}

// ============================================================
// 手势标签枚举
// ============================================================
typedef enum {{
  {label_enum}
}} gesture_class_t;

// ============================================================
// 手势标签名称
// ============================================================
static const char* gesture_labels[] = {{
  {label_names_array}
}};

// ============================================================
// TFLite 模型数据
// ============================================================
static const unsigned char gesture_model_tflite[] = {{
  {c_array}
}};

static const unsigned int gesture_model_tflite_len = {len(tflite_bytes)};

#endif  // GESTURE_MODEL_H
"""
    
    header_path = os.path.join(MODEL_DIR, filename)
    with open(header_path, "w", encoding="utf-8") as f:
        f.write(header_content)
    
    print(f"    C 头文件: {header_path}")
    print(f"    模型大小: {len(tflite_bytes)} 字节 ({len(tflite_bytes)/1024:.1f} KB)")

    # 同时复制到 esp32_firmware 目录
    esp32_header_path = os.path.join("esp32_firmware", filename)
    os.makedirs("esp32_firmware", exist_ok=True)
    with open(esp32_header_path, "w", encoding="utf-8") as f:
        f.write(header_content)
    print(f"    已复制到: {esp32_header_path}")


# ============================================================
# 混淆矩阵 & 分类报告
# ============================================================

def evaluate_detailed(model, X_test, y_test, label_names):
    """生成详细的评估报告"""
    from sklearn.metrics import classification_report, confusion_matrix
    import matplotlib.pyplot as plt
    
    # 预测
    y_pred_probs = model.predict(X_test, verbose=0)
    y_pred = np.argmax(y_pred_probs, axis=1)
    
    # 分类报告
    target_names = [label_names[i] for i in sorted(label_names.keys())]
    print(f"\n  📋 分类报告:")
    print(classification_report(
        y_test, y_pred,
        target_names=target_names,
        labels=sorted(label_names.keys()),
        zero_division=0
    ))
    
    # 混淆矩阵
    cm = confusion_matrix(y_test, y_pred)
    
    # 可视化
    try:
        plt.figure(figsize=(10, 8))
        plt.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
        plt.title("混淆矩阵")
        plt.colorbar()
        
        tick_marks = np.arange(len(target_names))
        plt.xticks(tick_marks, target_names, rotation=45, ha="right")
        plt.yticks(tick_marks, target_names)
        
        # 标注数值
        thresh = cm.max() / 2.
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                plt.text(j, i, format(cm[i, j], "d"),
                         ha="center", va="center",
                         color="white" if cm[i, j] > thresh else "black")
        
        plt.ylabel("真实标签")
        plt.xlabel("预测标签")
        plt.tight_layout()
        
        cm_path = os.path.join(MODEL_DIR, "confusion_matrix.png")
        plt.savefig(cm_path, dpi=150)
        print(f"    混淆矩阵已保存: {cm_path}")
        plt.close()
    except Exception as e:
        print(f"    ⚠️ 混淆矩阵绘图失败: {e}")
    
    return y_pred


# ============================================================
# 训练曲线
# ============================================================

def plot_training_history(history):
    """绘制训练曲线"""
    try:
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        
        # Loss
        axes[0].plot(history.history["loss"], label="训练 Loss")
        axes[0].plot(history.history["val_loss"], label="验证 Loss")
        axes[0].set_title("损失曲线")
        axes[0].set_xlabel("Epoch")
        axes[0].set_ylabel("Loss")
        axes[0].legend()
        axes[0].grid(True)
        
        # Accuracy
        axes[1].plot(history.history["accuracy"], label="训练 Accuracy")
        axes[1].plot(history.history["val_accuracy"], label="验证 Accuracy")
        if "top3_accuracy" in history.history:
            axes[1].plot(history.history["top3_accuracy"], label="训练 Top-3")
            axes[1].plot(history.history["val_top3_accuracy"], label="验证 Top-3")
        axes[1].set_title("准确率曲线")
        axes[1].set_xlabel("Epoch")
        axes[1].set_ylabel("Accuracy")
        axes[1].legend()
        axes[1].grid(True)
        
        plt.tight_layout()
        plot_path = os.path.join(MODEL_DIR, "training_history.png")
        plt.savefig(plot_path, dpi=150)
        print(f"    训练曲线已保存: {plot_path}")
        plt.close()
    except Exception as e:
        print(f"    ⚠️ 绘图失败: {e}")


# ============================================================
# 入口
# ============================================================

def main():
    print("=" * 55)
    print("  🏋️  LSTM 手语识别模型训练器")
    print("  基于 MediaPipe 关键点时序数据")
    print("=" * 55)
    
    import argparse
    parser = argparse.ArgumentParser(description="LSTM 手语识别模型训练")
    parser.add_argument("--model", choices=["bilstm", "conv_lstm"], default="bilstm",
                       help="模型架构 (默认: bilstm)")
    parser.add_argument("--epochs", type=int, default=100,
                       help="训练轮数 (默认: 100)")
    parser.add_argument("--batch-size", type=int, default=8,
                       help="批大小 (默认: 8)")
    parser.add_argument("--no-aug", action="store_true",
                       help="不使用数据增广")
    args = parser.parse_args()
    
    global NUM_EPOCHS, BATCH_SIZE, USE_AUGMENTATION
    NUM_EPOCHS = args.epochs
    BATCH_SIZE = args.batch_size
    USE_AUGMENTATION = not args.no_aug
    
    # 训练
    model, history = train_model(model_name=args.model)
    
    if model is None:
        print("\n  ❌ 训练失败!")
        return
    
    # 详细评估
    print(f"\n{'=' * 55}")
    print(f"  📊 详细评估")
    print(f"{'=' * 55}")
    
    # 重新加载数据以拿到测试集
    X, y, label_names = load_all_data(use_aug=USE_AUGMENTATION)
    if X is not None:
        X = normalize_sequences(X)
        from sklearn.model_selection import train_test_split
        _, X_test, _, y_test = train_test_split(
            X, y, test_size=TEST_SPLIT, random_state=42, stratify=y
        )
        evaluate_detailed(model, X_test, y_test, label_names)
    
    # 训练曲线
    if history:
        plot_training_history(history)
    
    # 汇总
    print(f"\n{'=' * 55}")
    print(f"  🎯 训练完成!")
    print(f"  模型文件: {MODEL_DIR}/")
    print(f"    - final_model.keras     (Keras 完整模型)")
    print(f"    - best_model.keras      (验证集最优模型)")
    print(f"    - model.tflite          (TFLite FP32)")
    print(f"    - model_quant.tflite    (TFLite INT8 量化)")
    print(f"    - gesture_model.h       (C 头文件, ESP32-S3)")
    print(f"    - class_map.json        (类别映射)")
    print(f"    - training_log.csv      (训练日志)")
    print(f"    - training_history.png  (训练曲线)")
    print(f"    - confusion_matrix.png  (混淆矩阵)")
    print(f"{'=' * 55}")
    print()
    print(f"  下一步: python real_time_lstm.py   (PC 实时识别)")
    print(f"  部署到 ESP32-S3: 使用 gesture_model.h")
    print()


if __name__ == "__main__":
    main()
