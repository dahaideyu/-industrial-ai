#!/usr/bin/env python3
"""知识库管理模块诊断脚本 — 检查数据库状态、连接、数据完整性"""
import os
import sys

# 自动定位项目根目录
_script_dir = os.path.dirname(os.path.abspath(__file__))
# 尝试多个可能的项目根路径
for _candidate in [_script_dir,
                   os.path.join(_script_dir, ".."),
                   os.path.join(_script_dir, "..", ".."),
                   "/app"]:
    _abs = os.path.abspath(_candidate)
    if os.path.isdir(os.path.join(_abs, "backend")):
        sys.path.insert(0, _abs)
        break

from dotenv import load_dotenv
import time

# 加载环境变量（Docker Compose 已注入，此处仅兜底）
for _env_path in [os.path.join(_script_dir, ".env.test"),
                  os.path.join(_script_dir, "..", ".env.test"),
                  "/app/.env.test"]:
    if os.path.isfile(_env_path):
        load_dotenv(_env_path)
        break
else:
    load_dotenv()

print("=" * 60)
print("知识库管理模块诊断")
print("=" * 60)

# 1. 环境变量检查
print("\n[1] 环境变量检查")
for var in ["KNB_PG_HOST", "KNB_PG_PORT", "KNB_PG_DB", "KNB_PG_USER",
            "KNB_LOCATION", "KNB_BASE_NAME", "ENABLE_KNOWLEDGE_BASE",
            "AQA_MYSQL_HOST", "AQA_MYSQL_PORT", "AQA_MYSQL_DATABASE",
            "RAGFLOW_BASE_URL", "KNB_REDIS_URL", "KNB_MINIO_ENDPOINT"]:
    val = os.getenv(var, "")
    status = "✓" if val else "✗ (未设置)"
    print(f"  {var} = {val[:50] if val else '(空)'} {status}")

# 2. KNB PostgreSQL 连接检查
print("\n[2] KNB PostgreSQL 连接检查")
try:
    from backend.core.knowledge_management.database import engine, get_db, Base
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("  ✓ 连接成功")
        # 检查表
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"  已有表 ({len(tables)}): {tables}")
except Exception as e:
    print(f"  ✗ 连接失败: {e}")

# 3. 数据完整性检查
print("\n[3] 数据完整性检查")
try:
    db = next(get_db())
    try:
        from backend.core.knowledge_management.models import (
            KnowledgeBase, PresetCategory, DocumentCategory,
            CollectionPlan, CollectionTarget, PlanItem,
        )

        # 预设类别
        preset_count = db.query(PresetCategory).count()
        preset_active = db.query(PresetCategory).filter(PresetCategory.is_active == True).count()
        print(f"  预设类别: 总计={preset_count}, 活跃={preset_active}")
        if preset_count > 0:
            for ct in ['device_doc', 'sop_doc', 'compliance']:
                cnt = db.query(PresetCategory).filter(
                    PresetCategory.category_type == ct,
                    PresetCategory.is_active == True,
                ).count()
                print(f"    - {ct}: {cnt}")

        # 知识库
        kbs = db.query(KnowledgeBase).all()
        print(f"  知识库总数: {len(kbs)}")
        for kb in kbs:
            print(f"    [{kb.kb_type}] {kb.name} (device_type={kb.device_type}, status={kb.status})")
            cat_count = db.query(DocumentCategory).filter(
                DocumentCategory.knowledge_base_id == kb.id
            ).count()
            target_count = db.query(CollectionTarget).filter(
                CollectionTarget.knowledge_base_id == kb.id
            ).count()
            plan_count = db.query(CollectionPlan).filter(
                CollectionPlan.knowledge_base_id == kb.id
            ).count()
            item_count = db.query(PlanItem).filter(
                PlanItem.plan_id.in_(
                    db.query(CollectionPlan.id).filter(
                        CollectionPlan.knowledge_base_id == kb.id
                    )
                )
            ).count()
            print(f"      类别={cat_count}, 对象={target_count}, 计划={plan_count}, 收集项={item_count}, rag_id={kb.rag_dataset_id}")

        # 如果没有 KB，检查合规性 KB 是否应该被创建
        from backend.core.knowledge_management.config import settings
        base_name = settings.knb_base_name
        print(f"  当前基地名称: '{base_name}'")

    finally:
        db.close()
except Exception as e:
    print(f"  ✗ 数据检查失败: {e}")
    import traceback
    traceback.print_exc()

# 4. AQA MySQL 连接检查
print("\n[4] AQA MySQL 连接检查")
try:
    import pymysql
    conn = pymysql.connect(
        host=os.getenv("AQA_MYSQL_HOST", ""),
        port=int(os.getenv("AQA_MYSQL_PORT", "3306")),
        user=os.getenv("AQA_MYSQL_USER", ""),
        password=os.getenv("AQA_MYSQL_PASSWORD", ""),
        database=os.getenv("AQA_MYSQL_DATABASE", ""),
        charset='utf8mb4',
        connect_timeout=5,
    )
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM dev_device_type WHERE del_flag=0")
        device_types_count = cur.fetchone()[0]
        print(f"  ✓ 连接成功, dev_device_type 设备类型数: {device_types_count}")
        cur.execute("""
            SELECT DISTINCT t.name AS device_type, sw.name AS workshop
            FROM dev_device_type t
            LEFT JOIN dev_device d ON t.id = d.type_id
            LEFT JOIN sys_line l ON d.line_id = l.id
            LEFT JOIN sys_workshop sw ON l.dept_id = sw.id
            WHERE t.del_flag=0 AND d.del_flag=0 AND l.del_flag=0 AND sw.del_flag=0
            AND t.name != '其他'
        """)
        rows = cur.fetchall()
        print(f"  符合条件的设备类型-车间配对: {len(rows)}")
        for row in rows[:5]:
            print(f"    - 类型={row[0]}, 车间={row[1]}")
    conn.close()
except Exception as e:
    print(f"  ✗ 连接失败: {e}")

# 5. RAGFlow 连接检查
print("\n[5] RAGFlow 连接检查")
try:
    ragflow_url = os.getenv("RAGFLOW_BASE_URL", "")
    if ragflow_url:
        import urllib.request
        req = urllib.request.Request(f"{ragflow_url}/api/v1/version", method="GET")
        req.add_header("Authorization", f"Bearer {os.getenv('RAGFLOW_API_KEY', '')}")
        resp = urllib.request.urlopen(req, timeout=10)
        print(f"  ✓ 连接成功 (status={resp.status})")
    else:
        print("  ✗ RAGFLOW_BASE_URL 未设置")
except Exception as e:
    print(f"  ✗ 连接失败: {e}")

print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)
