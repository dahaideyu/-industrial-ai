# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
import time
import paho.mqtt.client as mqtt
from typing import Dict, List, Tuple

from config import Config
from buffer import BatchBuffer

logger = logging.getLogger(__name__)

# topic -> [(parser, buffer), ...]；parser 需要实现 parse(payload: bytes, topic: str=None)
# -> (records, raw_json)，buffer 是该 handler 自己的 BatchBuffer 实例。
# 一个 topic 可以挂多个 handler，互不影响；一个 handler 抛异常不影响其他 handler。
TopicRoutes = Dict[str, List[Tuple[object, BatchBuffer]]]


class MQTTClient:
    def __init__(self, routes: TopicRoutes):
        if not routes:
            raise ValueError("MQTTClient 至少需要一个topic路由")
        self.routes = routes
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._setup_callbacks()
        self._connected = False

    def _setup_callbacks(self):
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties):
        if rc == 0:
            logger.info("MQTT connected successfully")
            self._connected = True
            for topic in self.routes:
                client.subscribe(topic, qos=Config.MQTT_QOS)
                logger.info(f"Subscribed to topic: {topic}")
        else:
            logger.error(f"MQTT connection failed with code: {rc}")
            self._connected = False

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties):
        self._connected = False
        if rc != 0:
            logger.warning(f"MQTT disconnected with code: {rc}")

    def _on_message(self, client, userdata, msg):
        handlers = self.routes.get(msg.topic)
        if not handlers:
            logger.warning(f"Received message on unrouted topic: {msg.topic}, ignoring")
            return

        for parser, buffer in handlers:
            try:
                records, raw_json = parser.parse(msg.payload, msg.topic)
                if records:
                    buffer.append(records, raw_json)
            except Exception as e:
                logger.error(
                    f"Error processing message on topic {msg.topic} with {parser.__class__.__name__}: {e}",
                    exc_info=True,
                )

    def start(self):
        if Config.MQTT_USER:
            self.client.username_pw_set(Config.MQTT_USER, Config.MQTT_PASS)

        reconnect_delay = 1
        max_delay = 60

        while True:
            try:
                logger.info(f"Connecting to MQTT broker {Config.MQTT_BROKER}:{Config.MQTT_PORT}")
                self.client.connect(Config.MQTT_BROKER, Config.MQTT_PORT, keepalive=60)
                self.client.loop_forever()
            except Exception as e:
                logger.error(f"MQTT connection error: {e}")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

    def stop(self):
        self.client.disconnect()
        logger.info("MQTT client stopped")
