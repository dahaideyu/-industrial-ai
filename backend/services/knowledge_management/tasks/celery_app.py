# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库管理模块 Celery 实例配置"""
from backend.core.knowledge_management.config import settings

from celery import Celery
from celery.schedules import crontab

import sys

kb_celery = Celery(
    "knowledge_management",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "backend.services.knowledge_management.tasks.convert_tasks",
        "backend.services.knowledge_management.tasks.extract_tasks",
        "backend.services.knowledge_management.tasks.review_tasks",
        "backend.services.knowledge_management.tasks.sync_tasks",
        "backend.services.knowledge_management.tasks.plc_tasks",
        "backend.services.knowledge_management.tasks.evaluation_tasks",
        "backend.services.knowledge_management.tasks.compliance_vision_tasks",
        "backend.services.knowledge_qa.tasks.cleanup_chat_assistants",
    ],
)

kb_celery.conf.task_routes = {
    "backend.services.knowledge_management.tasks.convert_tasks.*": {"queue": "kb_convert"},
    "backend.services.knowledge_management.tasks.extract_tasks.*": {"queue": "kb_extract"},
    "backend.services.knowledge_management.tasks.review_tasks.*": {"queue": "kb_review"},
    "backend.services.knowledge_management.tasks.sync_tasks.*": {"queue": "kb_sync"},
    "backend.services.knowledge_management.tasks.plc_tasks.*": {"queue": "kb_plc"},
    "backend.services.knowledge_management.tasks.evaluation_tasks.*": {"queue": "kb_eval"},
    "backend.services.knowledge_management.tasks.compliance_vision_tasks.*": {"queue": "kb_review"},
}

kb_celery.conf.task_default_retry_delay = 60
kb_celery.conf.task_max_retries = 3
kb_celery.conf.task_ack_late = True
# Windows 兼容：用 threads 池替代 prefork
if sys.platform == "win32":
    kb_celery.conf.worker_pool = "threads"

kb_celery.conf.beat_schedule = {
    'sync-device-types': {
        'task': 'sync_device_types_task',
        'schedule': crontab(hour=3, minute=0),
        'options': {'queue': 'kb_sync'},
    },
    'kbqa-cleanup-idle-chat-assistants': {
        'task': 'cleanup_idle_chat_assistants_task',
        'schedule': crontab(hour=0, minute=0),
        'options': {'queue': 'kb_sync'},
    },
}

@kb_celery.task(name='sync_device_types_task')
def sync_device_types_task():
    from backend.core.knowledge_management.database import SessionLocal
    from backend.services.knowledge_management.device_sync_svc import device_sync_svc
    db = SessionLocal()
    try:
        result = device_sync_svc.sync_device_types(db)
        return result
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()

@kb_celery.task(name='cleanup_idle_chat_assistants_task')
def cleanup_idle_chat_assistants_task():
    from backend.services.knowledge_qa.tasks.cleanup_chat_assistants import (
        cleanup_idle_chat_assistants,
    )
    return cleanup_idle_chat_assistants()
