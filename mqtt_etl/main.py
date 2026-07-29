# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
import signal
import sys
import threading

from config import Config
from database import DatabaseWriter
from parser import AlarmMessageParser, EnergyMessageParser
from buffer import BatchBuffer
from mqtt_client import MQTTClient

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Application:
    def __init__(self):
        self.db_writer = DatabaseWriter()

        self.alarm_parser = AlarmMessageParser()
        self.alarm_buffer = BatchBuffer(self.db_writer.write_alarm_batch, name="alarm")

        self.energy_parser = EnergyMessageParser()
        self.energy_buffer = BatchBuffer(self.db_writer.write_energy_batch, name="energy")

        self.buffers = []
        routes = {}
        if Config.MQTT_TOPIC:
            routes[Config.MQTT_TOPIC] = [(self.alarm_parser, self.alarm_buffer)]
            self.buffers.append(self.alarm_buffer)
        else:
            logger.warning("MQTT_TOPIC 未配置，报警点位topic不会被订阅")
        if Config.MQTT_TOPIC_NH:
            routes[Config.MQTT_TOPIC_NH] = [(self.energy_parser, self.energy_buffer)]
            self.buffers.append(self.energy_buffer)
        else:
            logger.warning("MQTT_TOPIC_NH 未配置，NH topic不会被订阅")

        self.mqtt_client = MQTTClient(routes)
        self._shutdown_event = threading.Event()

    def run(self):
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            for buffer in self.buffers:
                buffer.start()
            self.mqtt_client.start()
        except Exception as e:
            logger.error(f"Application error: {e}", exc_info=True)
        finally:
            self._shutdown()

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self._shutdown_event.set()
        self.mqtt_client.stop()

    def _shutdown(self):
        logger.info("Shutting down application...")
        for buffer in self.buffers:
            try:
                buffer.stop()
            except Exception as e:
                logger.error(f"Error during shutdown of buffer[{buffer.name}]: {e}", exc_info=True)
        logger.info("Application shutdown complete")


def main():
    app = Application()
    app.run()


if __name__ == "__main__":
    main()
