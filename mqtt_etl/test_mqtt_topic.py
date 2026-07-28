"""
MQTT 能耗点位主题监听测试脚本
实时打印能耗点位 (MQTT_TOPIC_NH) 的消息
用法:
    cd mqtt_etl
    python test_mqtt_topic.py              # 默认10秒不活跃自动退出
    python test_mqtt_topic.py --timeout 30 # 30秒后自动退出
    python test_mqtt_topic.py --no-exit    # 一直监听，手动 Ctrl+C 退出
"""
import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

from config import Config

# ── 命令行参数 ──────────────────────────────────────────
parser = argparse.ArgumentParser(description="MQTT 能耗点位主题监听测试")
parser.add_argument("--timeout", type=int, default=300, help="无消息自动退出秒数（默认10）")
parser.add_argument("--no-exit", action="store_true", help="一直监听，不自动退出")
args = parser.parse_args()

# ── 日志 ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mqtt-test")

# ── 统计 ────────────────────────────────────────────────
message_count = 0
start_time = time.time()
last_message_time = time.time()


def print_separator(char="─", width=80):
    print(char * width)


def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        logger.info("✓ MQTT 连接成功")
        if Config.MQTT_TOPIC_NH:
            client.subscribe(Config.MQTT_TOPIC_NH, qos=Config.MQTT_QOS)
            logger.info(f"  已订阅能耗点位主题: {Config.MQTT_TOPIC_NH}")
        else:
            logger.error("  MQTT_TOPIC_NH 未配置，无法订阅！")
        print_separator()
    else:
        logger.error(f"✗ MQTT 连接失败，错误码: {rc}")


def on_disconnect(client, userdata, flags, rc, properties):
    if rc != 0:
        logger.warning(f"MQTT 断开连接，错误码: {rc}")


def on_message(client, userdata, msg):
    global last_message_time, message_count
    last_message_time = time.time()
    message_count += 1

    # 解码
    try:
        payload_str = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning(f"[能耗] 无法解码的二进制数据: {len(msg.payload)} bytes")
        return

    try:
        data = json.loads(payload_str)
    except json.JSONDecodeError:
        logger.warning(f"[能耗] 非 JSON 数据 (前200字符): {payload_str[:200]}")
        return

    # 打印消息摘要
    msg_time = data.get("time", "?")
    devices = data.get("devices", [])
    total_points = sum(len(d.get("points", [])) for d in devices)
    device_ids = [d.get("device_id", "?") for d in devices[:3]]
    if len(devices) > 3:
        device_ids.append(f"...共{len(devices)}台设备")

    print(f"\n{'='*80}")
    print(f"📨 [能耗] #{message_count} | 消息时间: {msg_time} | 到达: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    print(f"   设备: {', '.join(device_ids)} | 总点位: {total_points} 个")

    # 打印前 5 个点位详情
    shown = 0
    for device in data.get("devices", []):
        for point in device.get("points", []):
            if shown >= 5:
                break
            pid = point.get("point_id", "?")
            pval = point.get("point_value", "?")
            ptime = point.get("point_time", "?")
            print(f"   ├─ {pid} = {pval}  ({ptime})")
            shown += 1
        if shown >= 5:
            break
    if total_points > 5:
        print(f"   └─ ... 还有 {total_points - 5} 个点位（省略）")


def signal_handler(sig, frame):
    print("\n")
    logger.info("收到中断信号，正在退出…")
    print_summary()
    sys.exit(0)


def print_summary():
    print_separator("=", 80)
    elapsed = time.time() - start_time
    print(f"📊 监听时长: {elapsed:.0f} 秒")
    print(f"   能耗点位 ({Config.MQTT_TOPIC_NH or '未配置'}): {message_count} 条")
    if message_count == 0:
        print(f"\n⚠️  未收到任何消息，请检查：")
        print(f"   1. MQTT broker 是否可达？({Config.MQTT_BROKER}:{Config.MQTT_PORT})")
        print(f"   2. 主题名是否正确？MQTT_TOPIC_NH={Config.MQTT_TOPIC_NH}")
        print(f"   3. 设备端是否在正常上报数据？")
    print_separator("=", 80)


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not Config.MQTT_TOPIC_NH:
        logger.error("MQTT_TOPIC_NH 未配置，请检查 .env 文件")
        sys.exit(1)

    logger.info(f"MQTT Broker: {Config.MQTT_BROKER}:{Config.MQTT_PORT}")
    if args.no_exit:
        logger.info("模式: 持续监听 (Ctrl+C 退出)")
    else:
        logger.info(f"模式: {args.timeout}秒内无新消息自动退出")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    if Config.MQTT_USER:
        client.username_pw_set(Config.MQTT_USER, Config.MQTT_PASS)

    try:
        client.connect(Config.MQTT_BROKER, Config.MQTT_PORT, keepalive=60)
        client.loop_start()

        # 主循环：检查超时
        while True:
            time.sleep(1)
            if not args.no_exit and (time.time() - last_message_time) > args.timeout:
                logger.info(f"{args.timeout}秒内未收到新消息，自动退出")
                break

    except Exception as e:
        logger.error(f"运行出错: {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        print_summary()


if __name__ == "__main__":
    main()
