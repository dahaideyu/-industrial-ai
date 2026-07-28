# cython: annotation_typing=False, infer_types=False, language_level=3
#!/usr/bin/env python3
"""
设备数据分析工具
用于循环读取设备数据并进行分析

使用方法:
    python -m src.tools.device_analyzer --list
    python -m src.tools.device_analyzer --filter-workshop "极板车间"
    python -m src.tools.device_analyzer --filter-area "正球磨三"
    python -m src.tools.device_analyzer --device-id 102000018415
    python -m src.tools.device_analyzer --long-running 24
    python -m src.tools.device_analyzer --export --output analysis_result.json
"""

import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_FILE = PROJECT_ROOT / "src" / "data" / "devices.json"


def load_devices() -> dict:
    """加载设备数据"""
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def format_duration(seconds: int) -> str:
    """格式化时长"""
    if seconds == 0:
        return "--"
    if seconds < 3600:
        return f"{seconds // 60}分钟{seconds % 60}秒"
    if seconds < 86400:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}小时{mins}分钟"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    return f"{days}天{hours}小时"


def get_all_devices(data: dict) -> list:
    """获取所有设备列表"""
    devices = []
    for workshop in data.get('workshops', []):
        for line in workshop.get('production_lines', []):
            for device in line.get('devices', []):
                device['workshop'] = workshop['name']
                device['line'] = line['name']
                device['department'] = workshop['department']
                devices.append(device)
    return devices


def list_devices(data: dict, verbose: bool = False):
    """列出所有设备"""
    devices = get_all_devices(data)
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"{'部门':<8} {'车间':<10} {'产线':<12} {'设备名称':<20} {'设备编号':<15} {'运行时长':<15}")
        print(f"{'='*80}")
        
        current_workshop = None
        for d in devices:
            if d['workshop'] != current_workshop:
                current_workshop = d['workshop']
                print(f"\n### {current_workshop} ###")
            
            print(f"{d['department']:<8} {d['workshop']:<10} {d['line']:<12} "
                  f"{d['name']:<20} {d['device_code']:<15} {d['run_time']:<15}")
    
    print(f"\n总计: {len(devices)} 台设备")


def filter_by_workshop(data: dict, workshop_name: str):
    """按车间筛选"""
    devices = get_all_devices(data)
    filtered = [d for d in devices if workshop_name in d['workshop']]
    
    print(f"\n### 车间: {workshop_name} (共 {len(filtered)} 台设备) ###\n")
    print(f"{'产线':<12} {'设备名称':<20} {'设备编号':<15} {'运行时长':<15}")
    print("-" * 65)
    
    for d in filtered:
        print(f"{d['line']:<12} {d['name']:<20} {d['device_code']:<15} {d['run_time']:<15}")


def filter_by_area(data: dict, area_name: str):
    """按产线区域筛选"""
    devices = get_all_devices(data)
    filtered = [d for d in devices if area_name in d['line']]
    
    print(f"\n### 产线区域: {area_name} (共 {len(filtered)} 台设备) ###\n")
    print(f"{'设备名称':<20} {'设备编号':<15} {'运行时长':<15}")
    print("-" * 50)
    
    for d in filtered:
        print(f"{d['name']:<20} {d['device_code']:<15} {d['run_time']:<15}")
    
    # 统计
    long_running = [d for d in filtered if d['run_time_seconds'] >= 3600]
    print(f"\n连续运行超过1小时: {len(long_running)} 台")


def find_device(data: dict, device_id: str):
    """查找指定设备"""
    devices = get_all_devices(data)
    for d in devices:
        if d['device_code'] == device_id or d['id'] == device_id or device_id in d['name']:
            print(f"\n### 设备信息 ###")
            print(f"名称: {d['name']}")
            print(f"编号: {d['device_code']}")
            print(f"部门: {d['department']}")
            print(f"车间: {d['workshop']}")
            print(f"产线: {d['line']}")
            print(f"运行时长: {d['run_time']}")
            
            # 风险评估
            seconds = d['run_time_seconds']
            if seconds >= 86400 * 7:
                print(f"⚠️ 警告: 连续运行超过7天，建议检查维护状态")
            elif seconds >= 86400:
                print(f"📊 注意: 连续运行超过24小时")
            elif seconds == 0:
                print(f"🆕 状态: 刚启动/空闲")
            else:
                print(f"[OK] 状态: 正常运行")
            return
    
    print(f"未找到设备: {device_id}")


def find_long_running(data: dict, hours: int):
    """查找连续运行超过指定小时的设备"""
    devices = get_all_devices(data)
    threshold = hours * 3600
    filtered = [d for d in devices if d['run_time_seconds'] >= threshold]
    filtered.sort(key=lambda x: x['run_time_seconds'], reverse=True)
    
    print(f"\n### 连续运行超过 {hours} 小时的设备 (共 {len(filtered)} 台) ###\n")
    print(f"{'设备名称':<20} {'设备编号':<15} {'运行时长':<15} {'产线':<12}")
    print("-" * 65)
    
    for d in filtered[:30]:  # 最多显示30条
        print(f"{d['name']:<20} {d['device_code']:<15} {d['run_time']:<15} {d['line']:<12}")
    
    if len(filtered) > 30:
        print(f"\n... 还有 {len(filtered) - 30} 台设备")


def find_idle_devices(data: dict, max_minutes: int = 30):
    """查找刚启动/空闲设备"""
    devices = get_all_devices(data)
    threshold = max_minutes * 60
    filtered = [d for d in devices if 0 < d['run_time_seconds'] <= threshold]
    filtered.sort(key=lambda x: x['run_time_seconds'])
    
    print(f"\n### 运行时长在 {max_minutes} 分钟以内的设备 (共 {len(filtered)} 台) ###\n")
    print(f"{'设备名称':<20} {'设备编号':<15} {'运行时长':<15} {'产线':<12}")
    print("-" * 65)
    
    for d in filtered:
        print(f"{d['name']:<20} {d['device_code']:<15} {d['run_time']:<15} {d['line']:<12}")


def export_analysis(data: dict, output_file: str):
    """导出分析结果"""
    devices = get_all_devices(data)
    
    # 统计分析
    total = len(devices)
    long_running_1h = len([d for d in devices if d['run_time_seconds'] >= 3600])
    long_running_24h = len([d for d in devices if d['run_time_seconds'] >= 86400])
    long_running_7d = len([d for d in devices if d['run_time_seconds'] >= 86400 * 7])
    idle = len([d for d in devices if d['run_time_seconds'] < 3600])
    
    result = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_devices": total,
            "running_over_1h": long_running_1h,
            "running_over_24h": long_running_24h,
            "running_over_7d": long_running_7d,
            "recently_started": idle
        },
        "devices": devices,
        "workshops": [
            {
                "name": w['name'],
                "department": w['department'],
                "device_count": sum(len(l['devices']) for l in w['production_lines'])
            }
            for w in data.get('workshops', [])
        ]
    }
    
    output_path = Path(output_file)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 分析结果已导出到: {output_path}")


def run_analysis(data: dict):
    """运行综合分析"""
    devices = get_all_devices(data)
    
    print(f"\n{'='*60}")
    print(f"           设备运行状态综合分析报告")
    print(f"{'='*60}")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 总体统计
    total = len(devices)
    long_running_1h = len([d for d in devices if d['run_time_seconds'] >= 3600])
    long_running_24h = len([d for d in devices if d['run_time_seconds'] >= 86400])
    long_running_7d = len([d for d in devices if d['run_time_seconds'] >= 86400 * 7])
    idle = len([d for d in devices if d['run_time_seconds'] < 3600])
    
    print(f"\n[4] 总体概况:")
    print(f"   设备总数: {total} 台")
    print(f"   运行超过1小时: {long_running_1h} 台 ({long_running_1h*100//total}%)")
    print(f"   运行超过24小时: {long_running_24h} 台")
    print(f"   运行超过7天: {long_running_7d} 台")
    print(f"   刚启动/空闲: {idle} 台")
    
    # 各车间统计
    print(f"\n[5] 车间分布:")
    for workshop in data.get('workshops', []):
        device_count = sum(len(l['devices']) for l in workshop['production_lines'])
        print(f"   {workshop['name']}: {device_count} 台设备")
    
    # 连续运行超过7天的设备
    print(f"\n[!] 连续运行超过7天的设备:")
    very_long = [d for d in devices if d['run_time_seconds'] >= 86400 * 7]
    very_long.sort(key=lambda x: x['run_time_seconds'], reverse=True)
    for d in very_long[:10]:
        print(f"   {d['name']:<20} {d['run_time']:<15} [{d['line']}]")
    
    # 刚启动的设备
    print(f"\n[*] 刚启动的设备 (运行<10分钟):")
    recent = [d for d in devices if 0 < d['run_time_seconds'] < 600]
    for d in recent[:10]:
        print(f"   {d['name']:<20} {d['run_time']:<15}")
    
    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(description='设备数据分析工具')
    parser.add_argument('--list', action='store_true', help='列出所有设备')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细列表模式')
    parser.add_argument('--filter-workshop', type=str, help='按车间筛选')
    parser.add_argument('--filter-area', type=str, help='按产线区域筛选')
    parser.add_argument('--device-id', type=str, help='查找指定设备')
    parser.add_argument('--long-running', type=int, metavar='HOURS', help='筛选连续运行超过指定小时的设备')
    parser.add_argument('--idle', action='store_true', help='显示刚启动的设备')
    parser.add_argument('--export', action='store_true', help='导出分析结果')
    parser.add_argument('--output', type=str, default='analysis_result.json', help='导出文件名')
    parser.add_argument('--analyze', action='store_true', help='运行综合分析')
    
    args = parser.parse_args()
    
    # 加载数据
    try:
        data = load_devices()
    except FileNotFoundError:
        print(f"错误: 找不到数据文件 {DATA_FILE}")
        return
    
    # 执行操作
    if args.list:
        list_devices(data, verbose=args.verbose)
    elif args.filter_workshop:
        filter_by_workshop(data, args.filter_workshop)
    elif args.filter_area:
        filter_by_area(data, args.filter_area)
    elif args.device_id:
        find_device(data, args.device_id)
    elif args.long_running:
        find_long_running(data, args.long_running)
    elif args.idle:
        find_idle_devices(data)
    elif args.export:
        export_analysis(data, args.output)
    elif args.analyze:
        run_analysis(data)
    else:
        # 默认运行综合分析
        run_analysis(data)


if __name__ == '__main__':
    main()
