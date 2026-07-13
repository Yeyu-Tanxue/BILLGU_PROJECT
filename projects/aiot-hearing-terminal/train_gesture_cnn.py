"""
端侧手势 CNN 训练 —— 读 gesture_data/ → 训小 CNN → 评估 → INT8 量化导出。

输入：gesture_data/<label>/*.png   (96x96 灰度)
输出（gesture_models/）：
    gesture_cnn.keras            Keras 模型
    gesture_int8.tflite          INT8 量化（端侧部署用，esp-tflite-micro）
    gesture_float.tflite         FP32（PC 验证用）
    gesture_labels.json          类别映射 {id: name}
    gesture_confusion.png        混淆矩阵（重点看 one/two）
    gesture_model.h              C 头文件（TFLite 模型字节数组，烧进固件）

运行：
    D:\anaconda3\envs\split\python.exe train_gesture_cnn.py
    可选: --epochs 40 --batch 32
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "gesture_data"
OUT_DIR = PROJECT_ROOT / "gesture_models"
IMG = 96


def load_data():
    import cv2

    classes = sorted([d.name for d in DATA_DIR.iterdir() if d.is_dir()
                      and not d.name.startswith("_")])
    if not classes:
        raise SystemExit(f"{DATA_DIR} 下没有类别文件夹")
    X, y = [], []
    for cid, name in enumerate(classes):
        files = sorted((DATA_DIR / name).glob("*.png"))
        for f in files:
            im = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if im is None:
                continue
            if im.shape != (IMG, IMG):
                im = cv2.resize(im, (IMG, IMG))
            X.append(im)
            y.append(cid)
        print(f"  [{cid}] {name:12} {len(files)} 张")
    X = np.array(X, dtype=np.float32)[..., None] / 255.0   # (N,96,96,1) 归一化
    y = np.array(y, dtype=np.int64)
    return X, y, classes


def build_model(n_classes: int, augment: bool = True):
    """augment=True 训练用（含增强层）；augment=False 导出用（纯 CNN，可转 TFLite）。
    增强层带 RNG 状态变量，concrete function 转 TFLite 会崩，故导出时去掉。"""
    from tensorflow import keras
    from tensorflow.keras import layers

    seq = [layers.Input((IMG, IMG, 1))]
    if augment:
        # 数据增强（只训练期生效）：逼模型学手型而非死记单次采集
        seq += [
            layers.RandomTranslation(0.15, 0.15),
            layers.RandomRotation(0.12),
            layers.RandomZoom(0.18),
            layers.RandomBrightness(0.3, value_range=(0.0, 1.0)),  # 模拟光照亮暗变化（数据已归一化到[0,1]）
            layers.RandomContrast(0.4),                            # 对比度变化（0.3→0.4）
        ]
    seq += [
        layers.Conv2D(8, 3, padding="same", activation="relu"),
        layers.MaxPooling2D(),                # 48
        layers.Conv2D(16, 3, padding="same", activation="relu"),
        layers.MaxPooling2D(),                # 24
        layers.Conv2D(32, 3, padding="same", activation="relu"),
        layers.MaxPooling2D(),                # 12
        layers.Conv2D(32, 3, padding="same", activation="relu"),
        layers.MaxPooling2D(),                # 6
        # 固定 Reshape 代替 Flatten（避免动态形状算子）。6*6*32=1152
        layers.Reshape((6 * 6 * 32,)),
        layers.Dropout(0.3),
        layers.Dense(64, activation="relu"),
        layers.Dense(n_classes, activation="softmax"),
    ]
    return keras.Sequential(seq)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()

    import tensorflow as tf
    from tensorflow import keras

    OUT_DIR.mkdir(exist_ok=True)
    print("加载数据 ...")
    X, y, classes = load_data()
    n = len(classes)
    print(f"  共 {len(X)} 张, {n} 类: {classes}")

    # 分层划分 train/val
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X))
    X, y = X[idx], y[idx]
    split = int(len(X) * 0.85)
    Xtr, Xva, ytr, yva = X[:split], X[split:], y[:split], y[split:]
    print(f"  train {len(Xtr)} / val {len(Xva)}")

    model = build_model(n)
    model.compile(optimizer="adam",
                  loss="sparse_categorical_crossentropy",
                  metrics=["accuracy"])
    model.summary()

    cbs = [
        keras.callbacks.EarlyStopping(patience=10, restore_best_weights=True,
                                      monitor="val_accuracy", mode="max"),
    ]
    model.fit(Xtr, ytr, validation_data=(Xva, yva),
              epochs=args.epochs, batch_size=args.batch, callbacks=cbs)

    # ---- 评估 + 混淆矩阵 ----
    proba = model.predict(Xva, verbose=0)
    pred = proba.argmax(1)
    acc = (pred == yva).mean()
    print(f"\n  验证集准确率: {acc*100:.1f}%")
    cm = np.zeros((n, n), int)
    for t, p in zip(yva, pred):
        cm[t, p] += 1
    print("  混淆矩阵 (行=真值, 列=预测):")
    print("     " + " ".join(f"{c[:5]:>6}" for c in classes))
    for i, c in enumerate(classes):
        print(f"  {c[:5]:>5} " + " ".join(f"{cm[i,j]:>6}" for j in range(n)))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(n)); ax.set_xticklabels(classes, rotation=45, ha="right")
        ax.set_yticks(range(n)); ax.set_yticklabels(classes)
        for i in range(n):
            for j in range(n):
                ax.text(j, i, cm[i, j], ha="center", va="center")
        ax.set_xlabel("pred"); ax.set_ylabel("true"); ax.set_title(f"acc {acc*100:.1f}%")
        fig.tight_layout(); fig.savefig(OUT_DIR / "gesture_confusion.png", dpi=120)
        print(f"  混淆矩阵图 → {OUT_DIR/'gesture_confusion.png'}")
    except Exception as e:
        print(f"  (画混淆矩阵跳过: {e})")

    # ---- 构建无增强的导出模型 + 迁移权重 ----
    # 增强层(RandomContrast 等)带 RNG 状态变量，转 TFLite 会崩；导出用纯 CNN。
    export_model = build_model(n, augment=False)
    export_model.build((None, IMG, IMG, 1))
    src = [l for l in model.layers if isinstance(l, (keras.layers.Conv2D, keras.layers.Dense))]
    dst = [l for l in export_model.layers if isinstance(l, (keras.layers.Conv2D, keras.layers.Dense))]
    for s, d in zip(src, dst):
        d.set_weights(s.get_weights())

    # ---- 保存 Keras + 标签 ----
    export_model.save(OUT_DIR / "gesture_cnn.keras")
    (OUT_DIR / "gesture_labels.json").write_text(
        json.dumps({"id_to_name": {str(i): c for i, c in enumerate(classes)}},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 导出 TFLite FP32 ----
    conv = tf.lite.TFLiteConverter.from_keras_model(export_model)
    (OUT_DIR / "gesture_float.tflite").write_bytes(conv.convert())

    # ---- 导出 TFLite INT8（全整数量化，端侧用）----
    def rep_data():
        for i in range(min(200, len(Xtr))):
            yield [Xtr[i:i+1]]
    conv = tf.lite.TFLiteConverter.from_keras_model(export_model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep_data
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    int8 = conv.convert()
    (OUT_DIR / "gesture_int8.tflite").write_bytes(int8)
    print(f"  INT8 模型: {len(int8)/1024:.1f} KB")

    # ---- 验证 INT8 准确率（端侧实际跑的就是它）----
    interp = tf.lite.Interpreter(model_content=int8)
    interp.allocate_tensors()
    inp, out = interp.get_input_details()[0], interp.get_output_details()[0]
    s, zp = inp["quantization"]
    correct = 0
    for i in range(len(Xva)):
        q = (Xva[i:i+1] / s + zp).astype(np.int8)
        interp.set_tensor(inp["index"], q)
        interp.invoke()
        if interp.get_tensor(out["index"])[0].argmax() == yva[i]:
            correct += 1
    print(f"  INT8 验证集准确率: {correct/len(Xva)*100:.1f}%  (同分布，偏乐观)")

    # ---- 诚实评估：若有独立测试集 gesture_data_test/（另一次采集）则评估 ----
    import cv2 as _cv2
    test_root = PROJECT_ROOT / "gesture_data_test"
    if test_root.exists():
        Xt, yt = [], []
        for cid, name in enumerate(classes):
            for f in sorted((test_root / name).glob("*.png")):
                im = _cv2.imread(str(f), _cv2.IMREAD_GRAYSCALE)
                if im is None:
                    continue
                if im.shape != (IMG, IMG):
                    im = _cv2.resize(im, (IMG, IMG))
                Xt.append(im); yt.append(cid)
        if Xt:
            Xt = np.array(Xt, np.float32)[..., None] / 255.0
            yt = np.array(yt)
            cmt = np.zeros((n, n), int); ct = 0
            for i in range(len(Xt)):
                q = (Xt[i:i+1] / s + zp).astype(np.int8)
                interp.set_tensor(inp["index"], q); interp.invoke()
                p = int(interp.get_tensor(out["index"])[0].argmax())
                cmt[yt[i], p] += 1
                if p == yt[i]:
                    ct += 1
            print(f"\n  ★ 独立测试集准确率: {ct/len(Xt)*100:.1f}%  ← 真实泛化率（看这个）")
            print("     " + " ".join(f"{c[:5]:>6}" for c in classes))
            for i, c in enumerate(classes):
                print(f"  {c[:5]:>5} " + " ".join(f"{cmt[i,j]:>6}" for j in range(n)))
    else:
        print(f"  (无独立测试集；想看真实泛化率，另开一次采集存到 gesture_data_test/)")

    # ---- 导出 C 头文件 ----
    arr = ", ".join(str(b) for b in int8)
    header = (
        "// 自动生成：手势 CNN INT8 TFLite 模型\n"
        f"// 输入 {IMG}x{IMG}x1 int8, 输出 {n} 类\n"
        "#pragma once\n#include <stdint.h>\n"
        f"const int gesture_n_classes = {n};\n"
        f"const int gesture_img_size = {IMG};\n"
        f"const unsigned int gesture_model_len = {len(int8)};\n"
        f"const unsigned char gesture_model[] = {{{arr}}};\n"
    )
    (OUT_DIR / "gesture_model.h").write_text(header, encoding="utf-8")
    print(f"  C 头文件 → {OUT_DIR/'gesture_model.h'}")
    # 同步到固件 main/（端侧推理直接 #include）—— gesture_cam 和 terminal 都用
    for fw in ("gesture_cam", "terminal"):
        fw_main = PROJECT_ROOT / "esp32_firmware" / fw / "main"
        if fw_main.exists():
            (fw_main / "gesture_model.h").write_text(header, encoding="utf-8")
            print(f"  已同步 → {fw_main/'gesture_model.h'}")
    print("\n  完成。重点看上面 INT8 准确率 + 混淆矩阵 one/two 是否互混。")


if __name__ == "__main__":
    main()
