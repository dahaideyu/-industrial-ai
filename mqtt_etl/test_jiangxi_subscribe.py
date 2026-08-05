# cython: annotation_typing=False, infer_types=False, language_level=3
"""
临时工具：验证江西 MQTT 订阅是否有效（读取 mqtt_etl/.env copy 配置）

用法:
    cd mqtt_etl
    python test_jiangxi_subscribe.py [--wait 90]
"""
import argparse
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

# Windows 控制台默认 GBK，强制 UTF-8 输出避免特殊符号报错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ENV_FILE = Path(__file__).parent / ".env copy"


def load_mqtt_conf(path: Path) -> dict:
    conf = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        conf[k.strip()] = v.strip()
    return conf


def main() -> int:
    parser = argparse.ArgumentParser(description="验证江西 MQTT 订阅")
    parser.add_argument("--wait", type=int, default=90, help="监听窗口秒数（默认90）")
    args = parser.parse_args()

    conf = load_mqtt_conf(ENV_FILE)
    broker = conf.get("MQTT_BROKER", "")
    port = int(conf.get("MQTT_PORT", "1883"))
    topic = conf.get("MQTT_TOPIC", "")
    topic_nh = conf.get("MQTT_TOPIC_NH", "")
    user = conf.get("MQTT_USER", "")
    password = conf.get("MQTT_PASS", "")
    qos = int(conf.get("MQTT_QOS", "1"))

    print(f"配置来源: {ENV_FILE}")
    print(f"Broker : {broker}:{port}  user={user or '(无)'}")
    print(f"TOPIC  : {topic}")
    print(f"TOPIC_NH: {topic_nh}")
    print()

    received: list = []
    state = {"connected": False, "conn_rc": None}

    def on_connect(client, userdata, flags, rc, properties):
        if rc == 0:
            state["connected"] = True
            print("[连接] ✓ 连接成功")
            for t in (topic, topic_nh):
                if t:
                    client.subscribe(t, qos=qos)
                    print(f"[订阅] ✓ {t} (QoS={qos})")
        else:
            state["conn_rc"] = rc
            print(f"[连接] ✗ 失败 rc={rc} ({mqtt.connack_string(rc)})")

    def on_message(client, userdata, msg):
        received.append(msg)
        sample = msg.payload[:160]
        try:
            sample = sample.decode("utf-8", errors="replace")
        except Exception:
            sample = repr(sample)
        print(f"[消息] #{len(received)} topic={msg.topic} payload={sample}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if user:
        client.username_pw_set(user, password)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"正在连接 {broker}:{port} ...")
    try:
        client.connect(broker, port, keepalive=30)
    except Exception as e:
        print(f"[连接] ✗ 无法连接: {type(e).__name__}: {e}")
        return 1
    client.loop_start()

    # 等待连接结果（最多 20 秒）
    deadline = time.time() + 20
    while not state["connected"] and state["conn_rc"] is None and time.time() < deadline:
        time.sleep(0.5)
    if state["conn_rc"] is not None:
        print(f"[结果] 连接被拒 rc={state['conn_rc']}（认证失败或 broker 不允许）")
        client.loop_stop()
        return 1
    if not state["connected"]:
        print("[结果] 20 秒内未连接成功")
        client.loop_stop()
        return 1

    # 监听窗口
    end = time.time() + args.wait
    last = time.time()
    while time.time() < end:
        time.sleep(1)
        # 已收到消息且 5 秒无新增，提前结束
        if received and time.time() - last > 5:
            break

    client.loop_stop()
    client.disconnect()

    print("\n===== 结果 =====")
    print(f"连接成功 : ✓")
    print(f"收到消息 : {len(received)} 条")
    if received:
        topics_seen = sorted({m.topic for m in received})
        print(f"命中的topic: {topics_seen}")
        print("结论: ✓ 订阅有效，江西 topic 有数据上报")
        return 0
    print(f"⚠ 连接成功但 {args.wait} 秒内未收到消息。可能原因：")
    print("   1. 设备端当前时段无上报（需现场确认上报频率/时段）")
    print("   2. topic 名需与 broker 实际发布一致")
    print("   3. 数据量低，窗口拉长再试（--wait 300）")
    return 2


if __name__ == "__main__":
    sys.exit(main())
