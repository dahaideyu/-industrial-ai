# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
import json
import time
import paho.mqtt.client as mqtt
from datetime import datetime
from pathlib import Path

from config import Config

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MQTTMonitor:
    def __init__(self, output_dir: str = "./mqtt_messages"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._setup_callbacks()
        self._message_count = 0

    def _setup_callbacks(self):
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties):
        if rc == 0:
            logger.info("MQTT connected successfully")
            topics = [t for t in (Config.MQTT_TOPIC, Config.MQTT_TOPIC_NH) if t]
            for topic in topics:
                client.subscribe(topic, qos=Config.MQTT_QOS)
                logger.info(f"Subscribed to topic: {topic}")
        else:
            logger.error(f"MQTT connection failed with code: {rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties):
        if rc != 0:
            logger.warning(f"MQTT disconnected with code: {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            self._message_count += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            topic_safe = msg.topic.replace("/", "_")
            filename = self.output_dir / f"{topic_safe}_{timestamp}.json"

            msg_data = {
                "topic": msg.topic,
                "qos": msg.qos,
                "retain": msg.retain,
                "timestamp": datetime.now().isoformat(),
                "message_count": self._message_count,
                "payload": None
            }

            try:
                payload_str = msg.payload.decode("utf-8")
                msg_data["payload"] = json.loads(payload_str)
            except UnicodeDecodeError:
                msg_data["payload"] = msg.payload.hex()
                logger.warning(f"Message {self._message_count}: payload is not UTF-8, saved as hex")
            except json.JSONDecodeError:
                msg_data["payload"] = payload_str
                logger.warning(f"Message {self._message_count}: payload is not valid JSON, saved as string")

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(msg_data, f, ensure_ascii=False, indent=2)

            logger.info(f"Message {self._message_count} saved to {filename}")

        except Exception as e:
            logger.error(f"Error saving message: {e}", exc_info=True)

    def start(self):
        if Config.MQTT_USER:
            self.client.username_pw_set(Config.MQTT_USER, Config.MQTT_PASS)

        reconnect_delay = 1
        max_delay = 60

        logger.info(f"Starting MQTT monitor, output directory: {self.output_dir.absolute()}")

        while True:
            try:
                logger.info(f"Connecting to MQTT broker {Config.MQTT_BROKER}:{Config.MQTT_PORT}")
                self.client.connect(Config.MQTT_BROKER, Config.MQTT_PORT, keepalive=60)
                self.client.loop_forever()
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, stopping...")
                break
            except Exception as e:
                logger.error(f"MQTT connection error: {e}")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

        self.client.disconnect()
        logger.info(f"Monitor stopped. Total messages received: {self._message_count}")


def main():
    monitor = MQTTMonitor()
    monitor.start()


if __name__ == "__main__":
    main()
