# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
import threading
import time
from typing import Callable, List, Tuple, Optional
from datetime import datetime

from config import Config

logger = logging.getLogger(__name__)

FlushFn = Callable[[List[Tuple], Optional[dict]], None]


class BatchBuffer:
    """按数量/时间批量攒消息再落库，flush_fn 由调用方传入（不同topic可以各自对应
    不同的数据库写入方法/表），一个topic一个 BatchBuffer 实例，互不影响。"""

    def __init__(
        self,
        flush_fn: FlushFn,
        batch_size: int = None,
        batch_timeout: int = None,
        name: str = "default",
    ):
        self.flush_fn = flush_fn
        self.batch_size = batch_size or Config.BATCH_SIZE
        self.batch_timeout = batch_timeout or Config.BATCH_TIMEOUT
        self.name = name
        self.buffer: List[Tuple] = []
        self.current_raw_json: Optional[dict] = None
        self.lock = threading.Lock()
        self.last_flush_time = time.time()
        self._running = False
        self._flush_thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_scheduler, daemon=True)
        self._flush_thread.start()
        logger.info(f"BatchBuffer[{self.name}] started")

    def stop(self):
        self._running = False
        if self._flush_thread:
            self._flush_thread.join(timeout=self.batch_timeout + 1)
        self.flush()
        logger.info(f"BatchBuffer[{self.name}] stopped")

    def append(self, records: List[Tuple], raw_json: Optional[dict] = None):
        with self.lock:
            self.buffer.extend(records)
            if raw_json:
                self.current_raw_json = raw_json

            if len(self.buffer) >= self.batch_size:
                self._flush_unlocked()

    def flush(self):
        with self.lock:
            self._flush_unlocked()

    def _flush_unlocked(self):
        if not self.buffer:
            return

        records = self.buffer.copy()
        raw_json = self.current_raw_json
        self.buffer = []
        self.current_raw_json = None
        self.last_flush_time = time.time()

        self.flush_fn(records, raw_json)

    def _flush_scheduler(self):
        check_interval = self.batch_timeout / 2
        while self._running:
            time.sleep(check_interval)
            with self.lock:
                if self.buffer and (time.time() - self.last_flush_time) >= self.batch_timeout:
                    logger.debug(f"BatchBuffer[{self.name}] timeout triggered flush")
                    self._flush_unlocked()
