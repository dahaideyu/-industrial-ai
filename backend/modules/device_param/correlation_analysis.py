# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备参数相关性分析模块
分析 dev_device_param_detail_record 中各参数之间的相关性，
找出运行状态下参数变化的关联性，为后续深入分析提供分组草案。
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from core.pg_env import pg_params


class CorrelationAnalyzer:
    """参数相关性分析器"""
    
    def __init__(self):
        self.conn = None
        self.device_info = {}
        self.params_cache = {}
    
    def connect(self) -> bool:
        """建立数据库连接"""
        try:
            self.conn = psycopg2.connect(**pg_params())
            print("✓ PostgreSQL 连接成功")
            return True
        except Exception as e:
            print(f"✗ PostgreSQL 连接失败: {e}")
            self.conn = None
            return False
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
    
    def get_devices(self) -> List[Dict]:
        """获取所有设备列表"""
        if not self.conn:
            return []
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id, device_id AS device_code, device_name FROM device_info ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]
    
    def get_device_params(self, device_code: str) -> List[Dict]:
        """获取设备的所有参数定义"""
        if device_code in self.params_cache:
            return self.params_cache[device_code]
        
        if not self.conn:
            return []
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT name AS p_name, description, unit 
                   FROM dev_device_param 
                   WHERE device_no = %s 
                   ORDER BY sort_num NULLS LAST, id""",
                (device_code,),
            )
            result = [
                {
                    "p_name": row["p_name"],
                    "display_name": row["description"] or row["p_name"],
                    "unit": row["unit"] or "",
                }
                for row in cursor.fetchall()
            ]
            self.params_cache[device_code] = result
            return result
    
    def get_running_status_code(self) -> Optional[int]:
        """获取运行状态对应的状态码"""
        if not self.conn:
            return None
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT code FROM dev_device_status WHERE status = '运行' LIMIT 1")
            row = cursor.fetchone()
            return row[0] if row else None
    
    def get_running_periods(
        self,
        device_id: int,
        status_code: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict]:
        """获取设备在指定时间范围内的运行时段"""
        if not self.conn:
            return []
        
        query = """
            SELECT start_time, end_time, duration
            FROM dev_device_status_record
            WHERE device_id = %s
              AND status = %s
              AND start_time < %s
              AND (end_time IS NULL OR end_time > %s)
            ORDER BY start_time ASC
        """
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (device_id, status_code, end_time, start_time))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_param_data_for_periods(
        self,
        device_code: str,
        p_names: List[str],
        running_periods: List[Dict],
    ) -> pd.DataFrame:
        """获取运行时段内的参数数据"""
        if not self.conn or not running_periods:
            return pd.DataFrame()
        
        # 构建时间条件
        period_conditions = []
        params = []
        for period in running_periods:
            p_start = period["start_time"]
            p_end = period.get("end_time") or datetime.now()
            period_conditions.append("(gather_time >= %s AND gather_time < %s)")
            params.extend([p_start, p_end])
        
        time_cond = "(" + " OR ".join(period_conditions) + ")"
        
        # 查询参数数据
        p_name_cond = "p_name IN (%s)" % ",".join(["%s"] * len(p_names))
        params = [device_code] + p_names + params
        
        query = """
            SELECT gather_time, p_name, p_value
            FROM dev_device_param_detail_record
            WHERE device_code = %s
              AND {}
              AND {}
            ORDER BY gather_time, p_name
        """.format(p_name_cond, time_cond)
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
        
        if not rows:
            return pd.DataFrame()
        
        # 转换为DataFrame并处理数值
        df = pd.DataFrame(rows)
        df["gather_time"] = pd.to_datetime(df["gather_time"])
        df["p_value_num"] = pd.to_numeric(df["p_value"], errors="coerce")
        df = df.dropna(subset=["p_value_num"])
        
        return df
    
    def calculate_correlation(
        self,
        df: pd.DataFrame,
        time_window: str = "5min",
    ) -> pd.DataFrame:
        """计算参数之间的相关性
        
        Args:
            df: 参数数据DataFrame，包含 gather_time, p_name, p_value_num
            time_window: 时间窗口，用于聚合数据
        
        Returns:
            相关性矩阵DataFrame
        """
        if df.empty:
            return pd.DataFrame()
        
        # 按时间窗口聚合
        df["time_bin"] = df["gather_time"].dt.floor(time_window)
        
        # 透视表：时间窗口 × 参数名
        pivot_df = df.pivot_table(
            index="time_bin",
            columns="p_name",
            values="p_value_num",
            aggfunc="mean"
        )
        
        # 计算皮尔逊相关系数
        corr_matrix = pivot_df.corr(method="pearson")
        
        return corr_matrix
    
    def analyze_device_correlation(
        self,
        device_code: str,
        device_name: str,
        start_time: datetime,
        end_time: datetime,
        min_correlation: float = 0.7,
    ) -> Dict:
        """分析单个设备的参数相关性"""
        print(f"\n===== 分析设备: {device_name} ({device_code}) =====")
        
        # 获取设备ID（用于查询状态记录）
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT id FROM device_info WHERE device_id = %s LIMIT 1", (device_code,))
            row = cursor.fetchone()
            device_id = row[0] if row else None
        
        if not device_id:
            print(f"✗ 未找到设备ID: {device_code}")
            return {}
        
        # 获取运行状态码
        status_code = self.get_running_status_code()
        if status_code is None:
            print("✗ 未找到运行状态码")
            return {}
        
        # 获取运行时段
        print("获取运行时段...")
        running_periods = self.get_running_periods(device_id, status_code, start_time, end_time)
        if not running_periods:
            print("✗ 未找到运行时段")
            return {}
        
        total_duration = sum(p.get("duration", 0) for p in running_periods)
        print(f"✓ 找到 {len(running_periods)} 个运行时段，总时长: {total_duration/3600:.1f} 小时")
        
        # 获取参数列表
        params = self.get_device_params(device_code)
        if not params:
            print("✗ 未找到参数定义")
            return {}
        
        p_names = [p["p_name"] for p in params]
        print(f"✓ 找到 {len(p_names)} 个参数")
        
        # 获取运行时段内的参数数据
        print("查询参数数据...")
        df = self.get_param_data_for_periods(device_code, p_names, running_periods)
        if df.empty:
            print("✗ 未找到参数数据")
            return {}
        
        print(f"✓ 获取到 {len(df)} 条数据记录")
        
        # 计算相关性
        print("计算相关性...")
        corr_matrix = self.calculate_correlation(df)
        if corr_matrix.empty:
            print("✗ 相关性计算失败")
            return {}
        
        # 找出强相关的参数对
        correlated_pairs = []
        p_names_list = corr_matrix.columns.tolist()
        
        for i, p1 in enumerate(p_names_list):
            for j, p2 in enumerate(p_names_list):
                if i < j:  # 避免重复
                    corr = corr_matrix.loc[p1, p2]
                    if abs(corr) >= min_correlation:
                        correlated_pairs.append({
                            "param1": p1,
                            "param2": p2,
                            "correlation": round(corr, 4),
                            "strength": "强正相关" if corr > 0 else "强负相关",
                        })
        
        # 按相关性强度排序
        correlated_pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        
        # 构建参数分组（基于相关性聚类）
        groups = self._cluster_params_by_correlation(corr_matrix, p_names_list, min_correlation)
        
        # 获取参数显示名映射
        display_name_map = {p["p_name"]: p["display_name"] for p in params}
        
        return {
            "device_code": device_code,
            "device_name": device_name,
            "analysis_period": f"{start_time.strftime('%Y-%m-%d')} ~ {end_time.strftime('%Y-%m-%d')}",
            "total_running_hours": round(total_duration / 3600, 1),
            "param_count": len(p_names),
            "data_points": len(df),
            "correlation_matrix": corr_matrix.round(4).to_dict(),
            "correlated_pairs": correlated_pairs,
            "param_groups": groups,
            "display_name_map": display_name_map,
        }
    
    def _cluster_params_by_correlation(
        self,
        corr_matrix: pd.DataFrame,
        p_names: List[str],
        threshold: float,
    ) -> List[Dict]:
        """基于相关性进行参数分组"""
        visited = set()
        groups = []
        
        for p_name in p_names:
            if p_name in visited:
                continue
            
            # 找到所有与当前参数强相关的参数
            group_members = [p_name]
            visited.add(p_name)
            
            for other_p in p_names:
                if other_p == p_name or other_p in visited:
                    continue
                
                corr = corr_matrix.loc[p_name, other_p]
                if abs(corr) >= threshold:
                    group_members.append(other_p)
                    visited.add(other_p)
            
            # 如果组内有多个参数，或者是孤立参数但有一定数据
            if len(group_members) >= 1:
                # 计算组内平均相关性
                if len(group_members) > 1:
                    total_corr = 0
                    count = 0
                    for i, p1 in enumerate(group_members):
                        for j, p2 in enumerate(group_members):
                            if i < j:
                                total_corr += abs(corr_matrix.loc[p1, p2])
                                count += 1
                    avg_corr = total_corr / count if count > 0 else 0
                else:
                    avg_corr = 0
                
                groups.append({
                    "members": group_members,
                    "size": len(group_members),
                    "avg_correlation": round(avg_corr, 4),
                })
        
        # 按组大小排序
        groups.sort(key=lambda x: x["size"], reverse=True)
        
        return groups
    
    def generate_report(self, results: List[Dict]) -> str:
        """生成分析报告"""
        lines = ["=" * 70]
        lines.append("设备参数相关性分析报告")
        lines.append("=" * 70)
        lines.append(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        for result in results:
            if not result:
                continue
            
            lines.append(f"【设备】{result['device_name']} ({result['device_code']})")
            lines.append(f"  分析周期: {result['analysis_period']}")
            lines.append(f"  运行时长: {result['total_running_hours']} 小时")
            lines.append(f"  参数数量: {result['param_count']} 个")
            lines.append(f"  数据点数: {result['data_points']} 条")
            lines.append("")
            
            # 相关参数对
            pairs = result["correlated_pairs"]
            if pairs:
                lines.append("  ┌─ 强相关参数对（相关性 ≥ 0.7）")
                for pair in pairs[:10]:  # 最多显示10对
                    p1_name = result["display_name_map"].get(pair["param1"], pair["param1"])
                    p2_name = result["display_name_map"].get(pair["param2"], pair["param2"])
                    lines.append(f"    • {p1_name} ↔ {p2_name}: {pair['correlation']:.4f} ({pair['strength']})")
                if len(pairs) > 10:
                    lines.append(f"    ... 还有 {len(pairs) - 10} 对")
                lines.append("")
            
            # 参数分组建议
            groups = result["param_groups"]
            lines.append("  ┌─ 参数分组草案（按相关性聚类）")
            for idx, group in enumerate(groups, 1):
                member_names = [
                    result["display_name_map"].get(m, m) for m in group["members"]
                ]
                lines.append(f"    组{idx} [{group['size']}个参数，组内平均相关:{group['avg_correlation']:.4f}]:")
                lines.append(f"      {', '.join(member_names)}")
            lines.append("")
        
        lines.append("=" * 70)
        lines.append("分析说明:")
        lines.append("  1. 强相关参数对：皮尔逊相关系数绝对值 ≥ 0.7")
        lines.append("  2. 参数分组基于相关性聚类，可用于后续深入分析")
        lines.append("  3. 正相关表示参数同向变化，负相关表示反向变化")
        lines.append("=" * 70)
        
        return "\n".join(lines)


def main():
    """主函数"""
    # 连接参数从环境变量读（PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD），
    # 不在源码里兜底生产口令 —— 漏配就应该连不上并报错
    
    analyzer = CorrelationAnalyzer()
    
    if not analyzer.connect():
        print("无法连接数据库，退出")
        return
    
    try:
        # 获取设备列表
        devices = analyzer.get_devices()
        if not devices:
            print("未找到设备")
            return
        
        # 设置分析时间范围：从3月1日到现在
        end_time = datetime.now()
        start_time = datetime(end_time.year, 3, 1)
        
        print(f"分析时间范围: {start_time.strftime('%Y-%m-%d')} ~ {end_time.strftime('%Y-%m-%d')}")
        print(f"共 {len(devices)} 台设备")
        
        # 分析每个设备
        results = []
        for device in devices:
            result = analyzer.analyze_device_correlation(
                device_code=device["device_code"],
                device_name=device["device_name"],
                start_time=start_time,
                end_time=end_time,
                min_correlation=0.7,
            )
            if result:
                results.append(result)
        
        # 生成报告
        report = analyzer.generate_report(results)
        print("\n" + "=" * 70)
        print("生成分析报告...")
        print("=" * 70)
        print(report)
        
        # 保存报告到文件
        report_filename = f"correlation_report_{end_time.strftime('%Y%m%d_%H%M%S')}.txt"
        with open(report_filename, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n✓ 报告已保存到: {report_filename}")
        
    finally:
        analyzer.close()


if __name__ == "__main__":
    main()