# ============================================================
# 模型正确性测试: 验证 Keras / TFLite FP32 / TFLite INT8
# 三种模型在同一测试集上的准确率是否一致
# ============================================================
import os, sys, json
import numpy as np

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import tensorflow as tf
from sklearn.model_selection import train_test_split

DATA_DIR = "lstm_data"
MODEL_DIR = "lstm_models"
from hand_features import SEQ_LEN, FEATURE_DIM
TEST_SPLIT = 0.15

# ——— 复用训练脚本的数据加载/归一化 (保证划分一致) ———
from train_lstm_model import load_all_data, normalize_sequences

print("=" * 55)
print("  🧪 模型正确性测试")
print("=" * 55)

X, y, label_names = load_all_data(use_aug=True)
X = normalize_sequences(X)
# 与训练脚本完全相同的 random_state/stratify -> 同一份测试集
_, X_test, _, y_test = train_test_split(
    X, y, test_size=TEST_SPLIT, random_state=42, stratify=y
)
print(f"\n  测试集: {X_test.shape[0]} 组, {len(label_names)} 类\n")


def eval_keras(path):
    m = tf.keras.models.load_model(path)
    probs = m.predict(X_test, verbose=0)
    pred = np.argmax(probs, axis=1)
    return np.mean(pred == y_test), pred


def eval_tflite(path):
    interp = tf.lite.Interpreter(model_path=path)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    preds = []
    for i in range(X_test.shape[0]):
        x = X_test[i:i+1].astype(np.float32)
        if inp["dtype"] == np.int8:
            scale, zero = inp["quantization"]
            x = (x / scale + zero).astype(np.int8)
        interp.set_tensor(inp["index"], x)
        interp.invoke()
        o = interp.get_tensor(out["index"])
        if out["dtype"] == np.int8:
            scale, zero = out["quantization"]
            o = (o.astype(np.float32) - zero) * scale
        preds.append(int(np.argmax(o[0])))
    preds = np.array(preds)
    return np.mean(preds == y_test), preds


results = {}
# 1) Keras
kp = os.path.join(MODEL_DIR, "best_model.keras")
if os.path.exists(kp):
    acc, pk = eval_keras(kp)
    results["Keras(best)"] = acc
    print(f"  ✅ Keras  (best_model.keras)   准确率: {acc*100:.2f}%")

# 2) TFLite FP32
fp = os.path.join(MODEL_DIR, "model.tflite")
if os.path.exists(fp):
    acc, pf = eval_tflite(fp)
    results["TFLite-FP32"] = acc
    print(f"  ✅ TFLite FP32 (model.tflite)  准确率: {acc*100:.2f}%")

# 3) TFLite INT8
qp = os.path.join(MODEL_DIR, "model_quant.tflite")
if os.path.exists(qp):
    acc, pq = eval_tflite(qp)
    results["TFLite-INT8"] = acc
    print(f"  ✅ TFLite INT8 (model_quant)   准确率: {acc*100:.2f}%")

print("\n" + "=" * 55)
print("  📊 结论")
print("=" * 55)
for name, acc in results.items():
    flag = "✅" if acc >= 0.9 else ("⚠️" if acc >= 0.7 else "❌")
    print(f"    {flag} {name:20s}: {acc*100:.2f}%")

# 一致性检查 (单样本端到端推理 sanity check)
print("\n  🔍 单样本端到端验证 (取测试集第 0 组):")
true_name = label_names[int(y_test[0])]
print(f"    真实标签: 【{true_name}】(id={y_test[0]})")
if "TFLite-FP32" in results:
    print(f"    FP32 预测: 【{label_names[int(pf[0])]}】(id={pf[0]})")
if "TFLite-INT8" in results:
    print(f"    INT8 预测: 【{label_names[int(pq[0])]}】(id={pq[0]})")
print("=" * 55)
