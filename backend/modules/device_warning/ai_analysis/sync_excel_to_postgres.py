# cython: annotation_typing=False, infer_types=False, language_level=3
#!/usr/bin/env python3
"""
同步 Excel 点位信息到 PostgreSQL point_info 表

Excel 中包含了工艺参数（Tec_xxx）的完整定义，但 point_info 表中目前只有报警参数。
本脚本将缺失的工艺参数插入 point_info 表，使数据库拥有完整的点位定义。

Usage:
    python sync_excel_to_postgres.py          # 同步所有设备
    python sync_excel_to_postgres.py --dry-run # 仅预览，不执行写入
"""
import argparse
import sys
from pathlib import Path

from .point_config import (
    DEVICES,
    PROCESS_POINT_DISPLAY_NAMES,
    ALARM_POINT_NAMES,
)
from .postgres_loader import PostgresDB


def sync_device_points(db: PostgresDB, device_id: str, dry_run: bool = False):
    """同步单个设备的点位信息到 point_info"""
    device_name = DEVICES.get(device_id, {}).get("name", device_id)
    print(f"\n=== 设备: {device_name} ({device_id}) ===")

    # 获取现有 point_info 中的点位
    existing = db.query(
        "SELECT point_id, point_name, remark FROM point_info WHERE belong_devide = %s",
        (device_id,),
    )
    existing_ids = set(existing["point_id"].tolist()) if not existing.empty else set()
    print(f"  数据库已有点位: {len(existing_ids)} 个")

    # 准备要插入的工艺参数
    process_points = PROCESS_POINT_DISPLAY_NAMES.get(device_id, {})
    alarm_points = ALARM_POINT_NAMES.get(device_id, {})

    to_insert = []

    # 工艺参数
    for point_id, point_name in process_points.items():
        if point_id not in existing_ids:
            to_insert.append({
                "point_id": point_id,
                "point_name": point_name,
                "belong_devide": device_id,
                "remark": "工艺参数",
            })

    # 报警参数（如果缺失也补充，但通常已存在）
    for point_id, point_name in alarm_points.items():
        if point_id not in existing_ids:
            to_insert.append({
                "point_id": point_id,
                "point_name": point_name,
                "belong_devide": device_id,
                "remark": f"{point_id}=1为报警 =0正常",
            })

    if not to_insert:
        print(f"  无需同步，所有点位已存在")
        return 0

    print(f"  待插入点位: {len(to_insert)} 个")
    for item in to_insert[:5]:
        print(f"    - {item['point_id']}: {item['point_name']}")
    if len(to_insert) > 5:
        print(f"    ... 还有 {len(to_insert) - 5} 个")

    if dry_run:
        print("  [Dry-run] 跳过写入")
        return len(to_insert)

    # 执行插入
    inserted = 0
    for item in to_insert:
        sql = """
            INSERT INTO point_info (point_id, point_name, belong_devide, remark)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (point_id, belong_devide) DO UPDATE SET
                point_name = EXCLUDED.point_name,
                remark = EXCLUDED.remark;
        """
        # 注意: 如果 point_id 不是唯一键/主键，ON CONFLICT 会失败
        # 先检查表结构是否有唯一约束
        if db.execute(sql, (item["point_id"], item["point_name"], item["belong_devide"], item["remark"])):
            inserted += 1

    print(f"  成功同步: {inserted} 个点位")
    return inserted


def main():
    parser = argparse.ArgumentParser(description="同步Excel点位信息到PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    args = parser.parse_args()

    db = PostgresDB()
    if not db.connect_with_fallback():
        print("[错误] 无法连接到 PostgreSQL 数据库")
        sys.exit(1)

    print("=" * 60)
    print("  Excel 点位信息同步工具")
    print("=" * 60)

    total = 0
    for device_id in DEVICES.keys():
        total += sync_device_points(db, device_id, dry_run=args.dry_run)

    db.close()

    print("\n" + "=" * 60)
    if args.dry_run:
        print(f"  [Dry-run] 共需同步 {total} 个点位")
    else:
        print(f"  同步完成，共插入/更新 {total} 个点位")
    print("=" * 60)


if __name__ == "__main__":
    main()
