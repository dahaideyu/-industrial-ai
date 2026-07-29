#!/usr/bin/env python3
"""
设备和工艺参数点位信息导入脚本
使用方法: python import_device_params.py

注意: 此脚本为临时脚本，数据库地址已写死在代码中，用完可删除
"""
import sys
import psycopg2


# ==================== 数据库配置（写死）====================
PG_CONFIG = {
    "host": "192.168.50.227",
    "port": 15432,
    "user": "postgres",
    "password": "CHANGE_ME",
    "database": "postgres",
}


# ==================== 设备信息 ====================
DEVICES = [
    # 球磨机
    ("1#球磨机", "BTR-QSDLQM-01-001", "QSDLQM"),
    ("2#球磨机", "BTR-QSDLQM-01-007", "QSDLQM"),
    ("3#球磨机", "BTR-QSDLQM-01-013", "QSDLQM"),
    ("4#球磨机", "BTR-QSDLQM-01-019", "QSDLQM"),
    ("5#球磨机", "BTR-QSDLQM-01-025", "QSDLQM"),
    ("6#球磨机", "BTR-QSDLQM-02-001", "QSDLQM"),
    ("7#球磨机", "BTR-QSDLQM-02-007", "QSDLQM"),
    ("8#球磨机", "BTR-QSDLQM-02-013", "QSDLQM"),
    ("9#球磨机", "BTR-QSDLQM-02-019", "QSDLQM"),
    ("10#球磨机", "BTR-QSDLQM-02-025", "QSDLQM"),
    ("11#球磨机", "BTR-QSDLQM-02-031", "QSDLQM"),
    ("12#球磨机", "BTR-QSDLQM-02-037", "QSDLQM"),
    ("13#球磨机", "BTR-QSDLQM-02-043", "QSDLQM"),
    ("14#球磨机", "BTR-QSDLQM-02-049", "QSDLQM"),
    ("15#球磨机", "BTR-QSDLQM-02-053", "QSDLQM"),
    # 合膏机
    ("负1#真空合膏机", "BTR-QSDLHG-01-001", "QSDLHG"),
    ("负2#真空合膏机", "BTR-QSDLHG-01-002", "QSDLHG"),
    ("负3#真空合膏机", "BTR-QSDLHG-01-004", "QSDLHG"),
    ("负4#真空合膏机", "BTR-QSDLHG-01-005", "QSDLHG"),
    ("负5#真空合膏机", "BTR-QSDLHG-01-007", "QSDLHG"),
    ("负6#真空合膏机", "BTR-QSDLHG-01-008", "QSDLHG"),
    ("正1#真空合膏机", "BTR-QSDLHG02-001", "QSDLHG"),
    ("正2#真空合膏机", "BTR-QSDLHG02-002", "QSDLHG"),
    ("正3#真空合膏机", "BTR-QSDLHG02-004", "QSDLHG"),
    ("正4#真空合膏机", "BTR-QSDLHG02-005", "QSDLHG"),
    # 固化室 - 正板
    ("正板1#固化室", "BTR-QSDLGH-02-001", "QSDLGH"),
    ("正板2#固化室", "BTR-QSDLGH-02-002", "QSDLGH"),
    ("正板3#固化室", "BTR-QSDLGH-02-003", "QSDLGH"),
    ("正板4#固化室", "BTR-QSDLGH-02-004", "QSDLGH"),
    ("正板5#固化室", "BTR-QSDLGH-02-005", "QSDLGH"),
    ("正板6#固化室", "BTR-QSDLGH-02-006", "QSDLGH"),
    ("正板7#固化室", "BTR-QSDLGH-02-007", "QSDLGH"),
    ("正板8#固化室", "BTR-QSDLGH-02-008", "QSDLGH"),
    ("正板9#固化室", "BTR-QSDLGH-02-009", "QSDLGH"),
    ("正板10#固化室", "BTR-QSDLGH-02-010", "QSDLGH"),
    ("正板11#固化室", "BTR-QSDLGH-02-011", "QSDLGH"),
    ("正板12#固化室", "BTR-QSDLGH-02-012", "QSDLGH"),
    ("正板13#固化室", "BTR-QSDLGH-02-013", "QSDLGH"),
    ("正板14#固化室", "BTR-QSDLGH-02-014", "QSDLGH"),
    ("正板15#固化室", "BTR-QSDLGH-02-015", "QSDLGH"),
    ("正板16#固化室", "BTR-QSDLGH-02-016", "QSDLGH"),
    ("正板17#固化室", "BTR-QSDLGH-02-017", "QSDLGH"),
    ("正板18#固化室", "BTR-QSDLGH-02-018", "QSDLGH"),
    ("正板19#固化室", "BTR-QSDLGH-02-019", "QSDLGH"),
    ("正板20#固化室", "BTR-QSDLGH-02-020", "QSDLGH"),
    ("正板21#固化室", "BTR-QSDLGH-02-021", "QSDLGH"),
    ("正板22#固化室", "BTR-QSDLGH-02-022", "QSDLGH"),
    ("正板23#固化室", "BTR-QSDLGH-02-023", "QSDLGH"),
    ("正板24#固化室", "BTR-QSDLGH-02-024", "QSDLGH"),
    ("正板25#固化室", "BTR-QSDLGH-02-025", "QSDLGH"),
    ("正板26#固化室", "BTR-QSDLGH-02-026", "QSDLGH"),
    ("正板27#固化室", "BTR-QSDLGH-02-027", "QSDLGH"),
    ("正板28#固化室", "BTR-QSDLGH-02-028", "QSDLGH"),
    ("正板29#固化室", "BTR-QSDLGH-02-029", "QSDLGH"),
    # 固化室 - 负板
    ("负板1#固化室", "BTR-QSDLGH-01-001", "QSDLGH"),
    ("负板2#固化室", "BTR-QSDLGH-01-002", "QSDLGH"),
    ("负板3#固化室", "BTR-QSDLGH-01-003", "QSDLGH"),
    ("负板4#固化室", "BTR-QSDLGH-01-004", "QSDLGH"),
    ("负板5#固化室", "BTR-QSDLGH-01-005", "QSDLGH"),
    ("负板6#固化室", "BTR-QSDLGH-01-006", "QSDLGH"),
    ("负板7#固化室", "BTR-QSDLGH-01-007", "QSDLGH"),
    ("负板8#固化室", "BTR-QSDLGH-01-008", "QSDLGH"),
    ("负板9#固化室", "BTR-QSDLGH-01-009", "QSDLGH"),
    ("负板10#固化室", "BTR-QSDLGH-01-010", "QSDLGH"),
    ("负板11#固化室", "BTR-QSDLGH-01-011", "QSDLGH"),
    ("负板12#固化室", "BTR-QSDLGH-01-012", "QSDLGH"),
    ("负板13#固化室", "BTR-QSDLGH-01-013", "QSDLGH"),
    ("负板14#固化室", "BTR-QSDLGH-01-014", "QSDLGH"),
    ("负板15#固化室", "BTR-QSDLGH-01-015", "QSDLGH"),
    ("负板16#固化室", "BTR-QSDLGH-01-016", "QSDLGH"),
    ("负板17#固化室", "BTR-QSDLGH-01-017", "QSDLGH"),
    ("负板18#固化室", "BTR-QSDLGH-01-018", "QSDLGH"),
    ("负板19#固化室", "BTR-QSDLGH-01-019", "QSDLGH"),
    ("负板20#固化室", "BTR-QSDLGH-01-020", "QSDLGH"),
    ("负板21#固化室", "BTR-QSDLGH-01-021", "QSDLGH"),
    ("负板22#固化室", "BTR-QSDLGH-01-022", "QSDLGH"),
]

# 设备类型分组
QSDLQM_DEVICES = [d[1] for d in DEVICES if d[2] == "QSDLQM"]
QSDLHG_DEVICES = [d[1] for d in DEVICES if d[2] == "QSDLHG"]
QSDLGH_DEVICES = [d[1] for d in DEVICES if d[2] == "QSDLGH"]


# ==================== 点位信息 ====================
# 球磨机点位
QSDLQM_POINTS = [
    ("Tec_AbsFilterDPre", "过滤器压差"),
    ("Tec_BagDPre", "布袋压差"),
    ("Tec_FrontBearingTemp", "前轴承温度"),
    ("Tec_FrontSecTemp", "前段温度"),
    ("Tec_LeadPelWT", "铅粒仓重量"),
    ("Tec_LeadPowTemp", "铅粉温度"),
    ("Tec_MidSecTemp", "中段温度"),
    ("Tec_NegDamPre", "负风门压差"),
    ("Tec_PosDamPre", "正风门压差"),
    ("Tec_Power", "功率"),
    ("Tec_RearBearingTemp", "后轴承温度"),
    ("Tec_RearSecTemp", "后段温度"),
]

# 合膏机点位
QSDLHG_POINTS = [
    ("Tec_AcidRealWT", "酸实时重量"),
    ("Tec_AcidRes", "酸残余量"),
    ("Tec_AcidWT", "酸用量"),
    ("Tec_End", "合膏结束"),
    ("Tec_LeadRealWT", "铅实时重量"),
    ("Tec_LeadRes", "铅残余量"),
    ("Tec_LeadWT", "铅用量"),
    ("Tec_MixMaxTemp", "合膏最高温度"),
    ("Tec_MixTemp", "合膏温度"),
    ("Tec_Stage", "合膏阶段"),
    ("Tec_VacDegree", "合膏真空度"),
    ("Tec_WaterRealWT", "水实时重量"),
    ("Tec_WaterRes", "水残余量"),
    ("Tec_WaterWT", "水用量"),
]

# 固化室点位
QSDLGH_POINTS = [
    ("Tec_DQD_DH", "当前段号"),
    ("Tec_DQD_Hour", "当前运行时间时"),
    ("Tec_DQD_Min", "当前运行时间分"),
    ("Tec_DQD_Sec", "当前运行时间秒"),
    ("Tec_DQG_TH", "当前工艺套数"),
    ("Tec_DQR_ZH", "当前运行组号"),
    ("Tec_Fan", "排湿风机运行"),
    ("Tec_Inverter_speed", "循环风机转速"),
    ("Tec_RRD_DH", "实际运行总阶段数"),
    ("Tec_Set_Hour", "阶段设定时间时"),
    ("Tec_Set_Hum", "设定湿度"),
    ("Tec_Set_Min", "阶段设定时间分"),
    ("Tec_Set_tep", "设定温度"),
    ("Tec_Time_Hum", "实时湿度"),
    ("Tec_Time_Tem", "实时温度"),
    ("Tec_Total_Hour", "总运行时间时"),
    ("Tec_Total_Min", "总运行时间分"),
]


def get_pg_connection():
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        print(f"[PostgreSQL] 已连接: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['database']}")
        return conn
    except Exception as e:
        print(f"[PostgreSQL] 连接失败: {e}")
        sys.exit(1)


def import_devices(pg_conn):
    """导入设备信息到 dev_device_param 表"""
    print(f"\n[Import] 开始导入设备信息 ({len(DEVICES)} 台)")
    
    with pg_conn.cursor() as cur:
        count = 0
        for device_name, device_no, device_type in DEVICES:
            cur.execute("""
                INSERT INTO dev_device_param (name, device_no, device_type, status)
                VALUES (%s, %s, %s, '1')
                ON CONFLICT DO NOTHING
            """, (device_name, device_no, device_type))
            count += cur.rowcount
        
        pg_conn.commit()
        print(f"[Import] 设备信息导入完成，新增 {count} 条")


def import_points(pg_conn):
    """导入点位信息到 point_info 表"""
    print(f"\n[Import] 开始导入点位信息")
    
    with pg_conn.cursor() as cur:
        # 球磨机点位
        count = 0
        for device_code in QSDLQM_DEVICES:
            for point_id, point_name in QSDLQM_POINTS:
                cur.execute("""
                    INSERT INTO point_info (point_id, point_name, belong_devide, remark)
                    VALUES (%s, %s, %s, '球磨机')
                    ON CONFLICT DO NOTHING
                """, (point_id, point_name, device_code))
                count += cur.rowcount
        print(f"[Import] 球磨机点位: 新增 {count} 条")
        
        # 合膏机点位
        count = 0
        for device_code in QSDLHG_DEVICES:
            for point_id, point_name in QSDLHG_POINTS:
                cur.execute("""
                    INSERT INTO point_info (point_id, point_name, belong_devide, remark)
                    VALUES (%s, %s, %s, '合膏机')
                    ON CONFLICT DO NOTHING
                """, (point_id, point_name, device_code))
                count += cur.rowcount
        print(f"[Import] 合膏机点位: 新增 {count} 条")
        
        # 固化室点位
        count = 0
        for device_code in QSDLGH_DEVICES:
            for point_id, point_name in QSDLGH_POINTS:
                cur.execute("""
                    INSERT INTO point_info (point_id, point_name, belong_devide, remark)
                    VALUES (%s, %s, %s, '固化室')
                    ON CONFLICT DO NOTHING
                """, (point_id, point_name, device_code))
                count += cur.rowcount
        print(f"[Import] 固化室点位: 新增 {count} 条")
        
        pg_conn.commit()
        print(f"[Import] 点位信息导入完成")


def verify_import(pg_conn):
    """验证导入结果"""
    print(f"\n[Verify] 验证导入结果")
    
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM dev_device_param")
        device_count = cur.fetchone()[0]
        print(f"[Verify] dev_device_param 表: {device_count} 条")
        
        cur.execute("SELECT COUNT(*) FROM point_info")
        point_count = cur.fetchone()[0]
        print(f"[Verify] point_info 表: {point_count} 条")
        
        # 按设备类型统计
        cur.execute("SELECT device_type, COUNT(*) FROM dev_device_param GROUP BY device_type")
        print(f"\n[Verify] 设备类型分布:")
        for dt, cnt in cur.fetchall():
            print(f"  - {dt}: {cnt} 台")
        
        # 按设备类型统计点位
        cur.execute("""
            SELECT p.remark, COUNT(*) 
            FROM point_info p 
            JOIN dev_device_param d ON p.belong_devide = d.device_no 
            GROUP BY p.remark
        """)
        print(f"\n[Verify] 点位类型分布:")
        for remark, cnt in cur.fetchall():
            print(f"  - {remark}: {cnt} 个")


def main():
    print("=" * 60)
    print("设备和工艺参数点位信息导入脚本")
    print("=" * 60)

    pg_conn = get_pg_connection()

    try:
        import_devices(pg_conn)
        import_points(pg_conn)
        verify_import(pg_conn)
        print("\n[Done] 所有数据导入完成!")
    except Exception as e:
        print(f"\n[Error] 导入失败: {e}")
        import traceback
        traceback.print_exc()
        pg_conn.rollback()
    finally:
        pg_conn.close()
        print("\n[Cleanup] 数据库连接已关闭")


if __name__ == "__main__":
    main()
