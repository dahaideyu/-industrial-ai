# cython: annotation_typing=False, infer_types=False, language_level=3
"""
MySQL Schema 探查脚本
连接: 127.0.0.1:13306 (cntlm 隧道)
"""
import sys
import os

# 加入 venv site-packages (pymysql 在里面)
VENV_SITE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "venv", "Lib", "site-packages")
if VENV_SITE not in sys.path:
    sys.path.insert(0, VENV_SITE)

import pymysql

MYSQL = dict(
    host="127.0.0.1",
    port=13306,
    user="zxzz",
    password="Focus&2025!",
    database="jxcw",
    charset="utf8mb4",
    connect_timeout=10,
)


def run(sql, conn, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall(), [d[0] for d in cur.description]


def main():
    print("连接 MySQL 127.0.0.1:13306 ...")
    conn = pymysql.connect(**MYSQL)
    print("连接成功!\n")

    # 1. 所有表
    rows, _ = run("SHOW TABLES", conn)
    tables = [r[0] for r in rows]
    print(f"数据库 '{MYSQL['database']}' 共 {len(tables)} 张表:")
    for t in tables:
        cnt_rows, _ = run(f"SELECT COUNT(*) FROM `{t}`", conn)
        print(f"  {t:<50} {cnt_rows[0][0]:>12,} 行")

    print()

    # 2. 重点表详情
    key_tables = [
        "dev_device_param_detail_record",
        "dev_device_status_record",
        "dev_device_status",
    ]
    for t in key_tables:
        if t not in tables:
            print(f"[SKIP] {t} 不存在")
            continue
        rows, _ = run(f"DESCRIBE `{t}`", conn)
        print(f"\n== {t} ==")
        for r in rows:
            print(f"  {r[0]:<30} {r[1]:<20} NULL={r[2]:<5} Key={r[3]}")

    # 3. 参数表: 设备列表 + 参数名
    if "dev_device_param_detail_record" in tables:
        print("\n== 参数表: 设备分布 ==")
        rows, _ = run("""
            SELECT device_code, device_name, COUNT(*) as cnt,
                   MIN(gather_time), MAX(gather_time)
            FROM dev_device_param_detail_record
            GROUP BY device_code, device_name
            ORDER BY cnt DESC
            LIMIT 20
        """, conn)
        for r in rows:
            print(f"  {r[0]:<20} {r[1]:<30} {r[2]:>10,}行  "
                  f"{str(r[3])[:16]} ~ {str(r[4])[:16]}")

        print("\n== 参数表: 参数名列表 (前50个设备的前50种参数) ==")
        rows, _ = run("""
            SELECT DISTINCT device_code, p_name
            FROM dev_device_param_detail_record
            LIMIT 200
        """, conn)
        from collections import defaultdict
        dev_params = defaultdict(list)
        for device_code, p_name in rows:
            dev_params[device_code].append(p_name)
        for dev, params in list(dev_params.items())[:5]:
            print(f"  设备 {dev}: {len(params)} 种参数")
            print(f"    {params[:10]}")

    # 4. 状态记录表
    if "dev_device_status_record" in tables:
        print("\n== 状态记录表: 状态分布 ==")
        rows, _ = run("""
            SELECT status, COUNT(*) as cnt,
                   AVG(duration)/60 as avg_min,
                   MIN(start_time), MAX(start_time)
            FROM dev_device_status_record
            GROUP BY status
            ORDER BY cnt DESC
        """, conn)
        for r in rows:
            print(f"  status={r[0]}  {r[1]:>8,}条  avg={r[2]:.1f}min  "
                  f"{str(r[3])[:16]} ~ {str(r[4])[:16]}")

    conn.close()
    print("\n探查完成.")


if __name__ == "__main__":
    main()
