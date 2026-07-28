# cython: annotation_typing=False, infer_types=False, language_level=3
"""
点位映射配置模块 - 打通 Excel 点位说明与 PostgreSQL 数据

从 docs/江西两台设备点位信息(1).xlsx 解析出的点位映射关系
"""

# ==================== 设备配置 ====================
DEVICES = {
    "102000018415": {"name": "正1#金帆球磨机", "type": "ball_mill"},
    "102000000996": {"name": "正2#衡远合膏机", "type": "mixer"},
}

# ==================== 工艺参数: point_id -> 中文显示名（来自Excel） ====================
PROCESS_POINT_DISPLAY_NAMES = {
    "102000018415": {
        "Tec_Bd_Yc": "布袋压差",
        "Tec_Ffy": "负压风压显示",
        "Tec_Glq_Yc": "过滤器压差",
        "Tec_Hd_Tep": "后段温度显示",
        "Tec_Power": "功率显示",
        "Tec_Qd_Tep": "前段温度显示",
        "Tec_Qf_Tep": "铅粉温度",
        "Tec_Qlc_Weight": "铅粒仓重量显示",
        "Tec_Zd_Tep": "中段温度显示",
        "Tec_Zfy": "正压风压显示",
    },
    "102000000996": {
        "Tec_DQD_DH": "合膏阶段状态",
        "Tec_End": "合膏结束标志位",
        "Tec_Hg_tep": "合膏温度",
        "Tec_Hg_tep_Max": "合膏最高温度",
        "Tec_lead_Actual_weight": "铅实际重量",  # Excel中为Tec_lead_Actual_weightt，数据库中为Tec_lead_Actual_weight
        "Tec_lead_Real_weight": "铅实时重量",
        "Tec_Sszkd": "合膏实时真空度",
        "Tec_sour_Actual_weight": "酸实际重量",
        "Tec_sour_Real_weight": "酸实时重量",
        "Tec_Water_Actual_weight": "水实际重量",
        "Tec_Water_Real_weight": "水实时重量",
    },
}

# ==================== 工艺参数: point_id -> 预测模块逻辑名 ====================
# 预测模块（anomaly_detector / fault_predictor / health_dashboard / energy_optimizer）
# 内部使用简化后的中文参数名，这里建立 point_id 到逻辑名的映射
PROCESS_POINT_LOGIC_NAMES = {
    "102000018415": {
        "Tec_Bd_Yc": "布袋压差",
        "Tec_Ffy": "负压风压",
        "Tec_Glq_Yc": "过滤器压差",
        "Tec_Hd_Tep": "后段温度",
        "Tec_Power": "主机功率",
        "Tec_Qd_Tep": "前段温度",
        "Tec_Qf_Tep": "铅粉温度",
        "Tec_Qlc_Weight": "铅粒仓重量",
        "Tec_Zd_Tep": "中段温度",
        "Tec_Zfy": "正压风压",
    },
    "102000000996": {
        "Tec_DQD_DH": "合膏阶段状态",
        "Tec_End": "合膏结束标志位",
        "Tec_Hg_tep": "合膏温度",
        "Tec_Hg_tep_Max": "合膏最高温度",
        "Tec_lead_Actual_weight": "铅实际重量",  # Excel中为Tec_lead_Actual_weightt，数据库中为Tec_lead_Actual_weight
        "Tec_lead_Real_weight": "铅实时重量",
        "Tec_Sszkd": "合膏实时真空度",
        "Tec_sour_Actual_weight": "酸实际重量",
        "Tec_sour_Real_weight": "酸实时重量",
        "Tec_Water_Actual_weight": "水实际重量",
        "Tec_Water_Real_weight": "水实时重量",
    },
}

# ==================== 报警参数: point_id -> 报警名称（来自Excel） ====================
ALARM_POINT_NAMES = {
    "102000018415": {
        "Alarm1": "负风风压下限报警",
        "Alarm2": "负风风压上限报警",
        "Alarm3": "正风风压下限报警",
        "Alarm4": "正风风压上限报警",
        "Alarm5": "负风压力低报警",
        "Alarm6": "布袋压差报警",
        "Alarm7": "滤筒压差报警",
        "Alarm8": "过滤器压差报警",
        "Alarm9": "布袋1温上限报警",
        "Alarm10": "后温下限报警",
        "Alarm11": "后温上限报警",
        "Alarm12": "中温下限报警",
        "Alarm13": "中温上限报警",
        "Alarm14": "前温下限报警",
        "Alarm15": "前温上限报警",
        "Alarm16": "电机功率下限报警",
        "Alarm17": "电机功率上限报警",
        "Alarm18": "铅粒仓振动故障",
        "Alarm19": "主机升温时间过长",
        "Alarm20": "铅粒仓超重",
        "Alarm21": "集粉旋转启动失败",
        "Alarm22": "负压三角启动失败",
        "Alarm23": "前轴承缺油",
        "Alarm24": "负压星形启动失败",
        "Alarm25": "输粉系统启动失败",
        "Alarm26": "正压三角启动失败",
        "Alarm27": "正压星形启动失败",
        "Alarm28": "油泵启动失败",
        "Alarm29": "主机软启动失败",
        "Alarm30": "主机旁路失败",
        "Alarm31": "返螺旋启动失败",
        "Alarm32": "轴流风机启动失败",
        "Alarm33": "集粉器振动故障",
        "Alarm34": "后轴承缺油",
        "Alarm35": "冷却油泵启动失败",
        "Alarm36": "进料气缸不到位",
        "Alarm37": "水欠压故障",
        "Alarm38": "气欠压故障",
        "Alarm39": "前段热电偶故障",
        "Alarm40": "中段热电偶故障",
        "Alarm41": "后段热电偶故障",
        "Alarm42": "布袋1热电偶故障",
        "Alarm43": "铅块出料振动故障",
        "Alarm44": "返螺旋振动A故障",
        "Alarm45": "油泵缺油",
        "Alarm46": "返螺旋气锤故障",
        "Alarm47": "轴承超温故障",
        "Alarm48": "滤筒振动启动失败",
        "Alarm49": "滤筒旋转阀启动失败",
        "Alarm50": "集粉器旋转阀2启动失败",
        "Alarm51": "主机减速机超温报警",
        "Alarm52": "集粉器旋转阀1启动失败",
    },
    "102000000996": {
        "AlarmMix1": "请加液态辅料",
        "AlarmMix2": "自动合膏未完",
        "AlarmMix3": "筒盖没盖好",
        "AlarmMix4": "内桶搅拌电机过载",
        "AlarmMix5": "膏斗电机过载",
        "AlarmMix6": "真空泵过载",
        "AlarmMix7": "主机出膏门没关好",
        "AlarmMix8": "主机接触器未闭合",
        "AlarmMix9": "气压不正常",
        "AlarmMix10": "进粉超时报警",
        "AlarmMix11": "称量进水超时报警",
        "AlarmMix12": "称量进酸超时报警",
        "AlarmMix13": "称量装置漏水",
        "AlarmMix14": "称量装置漏酸",
        "AlarmMix15": "温度超温报警",
        "AlarmMix16": "进粉间隔超时报警",
        "AlarmMix17": "冷凝水位不正常",
        "AlarmMix18": "冷冻水超温",
        "AlarmMix19": "冷冻水压不正常",
        "AlarmMix20": "进料超重",
        "AlarmMix21": "搅拌接触器未闭合",
        "AlarmMix22": "变频未启",
        "AlarmMix23": "电动机断路器过载",
        "AlarmMix24": "变频器故障",
        "AlarmMix25": "变频器没运行",
        "AlarmMix26": "辅料没加完",
        "AlarmMix27": "辅料没料满",
        "AlarmMix28": "变频器没有电流输出",
        "AlarmMix29": "内筒电机过载",
        "AlarmMix30": "该加辅料",
        "AlarmMix31": "膏门打开关闭时间太短",
        "AlarmMix32": "另机没有到加酸后阶段",
        "AlarmMix33": "真空阀故障",
        "AlarmMix34": "2#膏斗移动过载",
        "AlarmMix35": "润滑油位低",
        "AlarmMix36": "冷冻水温度超高",
        "AlarmMix37": "称量系统采样故障",
    },
}

# ==================== 预测模块参数阈值配置（按逻辑参数名） ====================
# 这些阈值来自现有预测模块的经验配置，后续可根据实际运行数据校准
PARAMETER_THRESHOLDS = {
    "正1#金帆球磨机": {
        "铅粒仓重量": (15000, 38000, 10000, 40000),
        "中段温度": (180, 220, 150, 230),
        "后段温度": (180, 220, 150, 230),
        "前段温度": (180, 220, 150, 230),
        "主机功率": (90, 106, 80, 110),
        "负压风压": (180, 230, 150, 250),
        "正压风压": (450, 535, 400, 550),
        "铅粉温度": (90, 115, 80, 120),
        "布袋压差": (40, 70, 30, 80),
        "过滤器压差": (70, 95, 60, 100),
    },
    "正2#衡远合膏机": {
        "合膏温度": (40, 80, 30, 90),
        "合膏最高温度": (40, 85, 30, 95),
        "合膏实时真空度": (-90, -30, -95, -20),
        "水实时重量": (0, 5000, -100, 5500),
        "水实际重量": (0, 5000, -100, 5500),
        "酸实时重量": (0, 500, -50, 600),
        "酸实际重量": (0, 500, -50, 600),
        "铅实时重量": (0, 5000, -100, 5500),
        "铅实际重量": (0, 5000, -100, 5500),
    },
}

# ==================== 报警与工艺参数的关联（用于报警预测） ====================
ALARM_PARAMETER_MAPPING = {
    "正1#金帆球磨机": {
        "负风风压下限报警": ("负压风压", "lower"),
        "负风风压上限报警": ("负压风压", "upper"),
        "正风风压下限报警": ("正压风压", "lower"),
        "正风风压上限报警": ("正压风压", "upper"),
        "后温下限报警": ("后段温度", "lower"),
        "后温上限报警": ("后段温度", "upper"),
        "中温下限报警": ("中段温度", "lower"),
        "中温上限报警": ("中段温度", "upper"),
        "前温下限报警": ("前段温度", "lower"),
        "前温上限报警": ("前段温度", "upper"),
        "电机功率下限报警": ("主机功率", "lower"),
        "电机功率上限报警": ("主机功率", "upper"),
        "布袋压差报警": ("布袋压差", "upper"),
        "过滤器压差报警": ("过滤器压差", "upper"),
    },
    "正2#衡远合膏机": {
        "温度超温报警": ("合膏温度", "upper"),
        "冷冻水超温": ("合膏温度", "upper"),
        "冷冻水温度超高": ("合膏温度", "upper"),
        "气压不正常": ("合膏实时真空度", "lower"),
        "进料超重": ("铅实时重量", "upper"),
        "进粉超时报警": ("铅实时重量", "lower"),
    },
}

# ==================== 故障模式配置（point_id / 逻辑名 -> 故障类型） ====================
FAULT_PATTERN_CONFIG = {
    "正1#金帆球磨机": {
        "thermal": {
            "name": "温度异常",
            "point_ids": ["Tec_Qd_Tep", "Tec_Zd_Tep", "Tec_Hd_Tep", "Tec_Qf_Tep"],
            "logic_names": ["前段温度", "中段温度", "后段温度", "铅粉温度"],
            "thresholds": {"diff_max": 20, "std_max": 5, "rise_count": 2},
        },
        "pressure": {
            "name": "风压系统异常",
            "point_ids": ["Tec_Zfy", "Tec_Ffy"],
            "logic_names": ["正压风压", "负压风压"],
            "thresholds": {"ratio_min": 1.5, "ratio_max": 3.0, "neg_min": 180, "pos_max": 540},
        },
        "mechanical": {
            "name": "机械部件异常",
            "point_ids": ["Tec_Power"],
            "logic_names": ["主机功率"],
            "thresholds": {"std_max": 5, "rise_ratio": 1.1, "drop_ratio": 0.85},
        },
        "filter": {
            "name": "过滤系统堵塞",
            "point_ids": ["Tec_Bd_Yc", "Tec_Glq_Yc"],
            "logic_names": ["布袋压差", "过滤器压差"],
            "thresholds": {"max_bd": 75, "max_glq": 100},
        },
        "material": {
            "name": "物料系统异常",
            "point_ids": ["Tec_Qlc_Weight"],
            "logic_names": ["铅粒仓重量"],
            "thresholds": {"rate_min": 50, "rate_max": 200, "std_min": 100},
        },
    },
    "正2#衡远合膏机": {
        "thermal": {
            "name": "温度异常",
            "point_ids": ["Tec_Hg_tep", "Tec_Hg_tep_Max"],
            "logic_names": ["合膏温度", "合膏最高温度"],
            "thresholds": {"diff_max": 15, "std_max": 3, "rise_count": 2},
        },
        "vacuum": {
            "name": "真空系统异常",
            "point_ids": ["Tec_Sszkd"],
            "logic_names": ["合膏实时真空度"],
            "thresholds": {"min": -90, "max": -20},
        },
        "weight": {
            "name": "称量系统异常",
            "point_ids": ["Tec_Water_Real_weight", "Tec_sour_Real_weight", "Tec_lead_Real_weight"],
            "logic_names": ["水实时重量", "酸实时重量", "铅实时重量"],
            "thresholds": {"std_max": 10, "drift_max": 50},
        },
    },
}


def get_logic_name(device_id: str, point_id: str) -> str:
    """获取工艺参数的逻辑参数名（用于预测模块）"""
    mapping = PROCESS_POINT_LOGIC_NAMES.get(device_id, {})
    return mapping.get(point_id, point_id)


def get_display_name(device_id: str, point_id: str) -> str:
    """获取工艺参数的显示名称（来自Excel）"""
    mapping = PROCESS_POINT_DISPLAY_NAMES.get(device_id, {})
    return mapping.get(point_id, point_id)


def get_alarm_name(device_id: str, point_id: str) -> str:
    """获取报警参数的报警名称"""
    mapping = ALARM_POINT_NAMES.get(device_id, {})
    return mapping.get(point_id, point_id)


def get_all_point_mappings(device_id: str) -> dict:
    """获取指定设备的所有点位映射（point_id -> 中文名）"""
    result = {}
    result.update(PROCESS_POINT_DISPLAY_NAMES.get(device_id, {}))
    result.update(ALARM_POINT_NAMES.get(device_id, {}))
    return result


def get_device_name(device_id: str) -> str:
    """获取设备名称"""
    return DEVICES.get(device_id, {}).get("name", device_id)


def get_device_config_for_predictor(device_id: str) -> dict:
    """
    获取指定设备的预测配置
    返回: {
        "thresholds": {...},
        "alarm_mapping": {...},
        "fault_patterns": {...},
    }
    """
    device_name = get_device_name(device_id)
    return {
        "device_id": device_id,
        "device_name": device_name,
        "thresholds": PARAMETER_THRESHOLDS.get(device_name, {}),
        "alarm_mapping": ALARM_PARAMETER_MAPPING.get(device_name, {}),
        "fault_patterns": FAULT_PATTERN_CONFIG.get(device_name, {}),
    }
