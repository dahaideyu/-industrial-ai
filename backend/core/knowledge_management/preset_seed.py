# cython: annotation_typing=False, infer_types=False, language_level=3
"""预设文档类别种子数据 — 70个叶子节点 + 中间层级"""
from sqlalchemy.orm import Session
from backend.core.knowledge_management.models import PresetCategory
import uuid

PRESET_CATEGORIES = [
    # ========== 设备说明文档 (device_doc) ==========
    # 一级
    {"id": "3cb6b693-6d58-57a9-95b4-184f4465f6a5", "parent_id": None, "name": "设备说明文档", "category_type": "device_doc", "level": 0, "is_leaf": False, "sort_order": 1,
     "requirement_desc": ""},
    # 二级: 图纸类
    {"id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "parent_id": "3cb6b693-6d58-57a9-95b4-184f4465f6a5", "name": "图纸类", "category_type": "device_doc", "level": 1, "is_leaf": False, "sort_order": 1,
     "requirement_desc": ""},
    # 三级(叶子): 机械图纸
    {"id": "699534ce-441b-5740-943f-db9811816eec", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "设备总装配图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "展示设备整体结构、各大部件装配关系"},
    {"id": "6f6af52a-c1c0-5b14-bbab-d6f4699b9b98", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "部件装配图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "各独立功能模块的装配关系图（如主轴箱、工作台、刀库、磨头架、冷却过滤系统等）"},
    {"id": "32f45536-ed07-5f9c-b830-c394e9be6e70", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "关键零部件图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "所有自制件的详细加工图纸，包含尺寸、公差、形位公差、表面粗糙度、材料、热处理等技术要求"},
    {"id": "6772541d-922f-54c6-8775-7aa1c806666b", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "工装夹具图纸", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 4,
     "requirement_desc": "标准配置及可选配的夹具全套图纸，包含定位、夹紧元件图"},
    # 三级(叶子): 电气图纸
    {"id": "e29c10c7-eee9-55b8-abff-44da053d5434", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "电气原理图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 5,
     "requirement_desc": "完整的主电路、控制电路、信号电路原理图"},
    {"id": "6ae3ccbb-a3be-53c8-bd2a-e5bb21e9192d", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "电气接线图/布线图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 6,
     "requirement_desc": "电柜内外所有元器件的实际接线位置与线号对照图"},
    {"id": "504adad6-b871-5db7-81e1-19b7a242fb6c", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "电气元器件布局图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 7,
     "requirement_desc": "控制柜内及操作面板上各电气元件的物理安装位置图"},
    {"id": "65d263ac-b090-54cd-aecf-2e4483424690", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "端子排接线图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 8,
     "requirement_desc": "所有端子排的详细编号及对应连接线的来源/去向定义"},
    # 三级(叶子): 气动与液压图纸
    {"id": "80f08408-0f64-53be-9bad-612fb62dc248", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "气动回路原理图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 9,
     "requirement_desc": "包含所有气动元件的图形符号与管路连接关系"},
    {"id": "826831fe-8feb-59ab-a110-683810886c41", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "液压回路原理图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 10,
     "requirement_desc": "包含泵、阀、油缸、马达等元件的系统原理图"},
    {"id": "9c4840dd-6297-5bf6-9acb-4b97df9eb9ed", "parent_id": "0de3c1b5-d191-5984-b613-44b2b9a75660", "name": "气动/液压元件布局图", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 11,
     "requirement_desc": "各气动/液压元件在设备上的实际安装位置标识"},
    # 二级: 手册类
    {"id": "acd41d04-fc14-5006-9e28-e86fddf2fbc6", "parent_id": "3cb6b693-6d58-57a9-95b4-184f4465f6a5", "name": "手册类", "category_type": "device_doc", "level": 1, "is_leaf": False, "sort_order": 2,
     "requirement_desc": ""},
    {"id": "7acb94b3-85a0-5511-be72-63908697980a", "parent_id": "acd41d04-fc14-5006-9e28-e86fddf2fbc6", "name": "机床操作手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "独立成册，含：安全操作规范与警示、控制面板及人机界面详细说明、开机与关机标准操作程序、手动/MDI/自动模式操作流程、工件装夹与刀具/砂轮安装对刀操作、程序传输与管理操作步骤"},
    {"id": "9c894023-05fb-50c4-928a-76076745cbd0", "parent_id": "acd41d04-fc14-5006-9e28-e86fddf2fbc6", "name": "数控系统编程手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "独立成册，含：标准G代码/M代码的格式与功能详解、厂家自定义宏程序与固定循环的调用格式及参数说明、系统变量与R参数完整地址及功能定义表、高级编程功能使用说明"},
    # 二级: 维护与子系统手册
    {"id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "parent_id": "3cb6b693-6d58-57a9-95b4-184f4465f6a5", "name": "维护与子系统手册", "category_type": "device_doc", "level": 1, "is_leaf": False, "sort_order": 3,
     "requirement_desc": ""},
    {"id": "4ab61958-74c5-52dd-a3a3-f406c1b4b9b8", "parent_id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "name": "维修保养手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "独立成册，含：日常保养指导、定期维护计划表（周/月/季/半年/年度保养项目）、润滑图表、常见故障排查指南"},
    {"id": "60288ff9-8baa-55a1-b9f9-8cb103d83125", "parent_id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "name": "数控系统(CNC)功能说明书", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "独立成册的子系统手册"},
    {"id": "e68a07c2-214f-5bbd-a87a-671e707364ea", "parent_id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "name": "伺服驱动系统手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "独立成册的子系统手册"},
    {"id": "bd610a66-c459-54c2-8258-4ecfb96dc7ed", "parent_id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "name": "主轴驱动系统手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 4,
     "requirement_desc": "独立成册的子系统手册"},
    {"id": "73f1051a-da9f-5839-885d-60b6f09428a0", "parent_id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "name": "PLC系统手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 5,
     "requirement_desc": "独立成册的子系统手册"},
    {"id": "28185784-0371-5fee-bf8e-9cc254e1545e", "parent_id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "name": "测量系统手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 6,
     "requirement_desc": "如有在线测量功能，独立成册"},
    {"id": "da086e71-0f08-548e-9de6-885eda96a33c", "parent_id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "name": "冷却与过滤系统手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 7,
     "requirement_desc": "如适用，独立成册"},
    {"id": "926a4733-e18a-50c0-800a-da262a9c7fe1", "parent_id": "51aff1aa-2925-5ee4-8b72-3a5e16e1ca86", "name": "排屑系统手册", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 8,
     "requirement_desc": "如适用，独立成册"},
    # 二级: 程序与参数类
    {"id": "d781b215-9a89-5871-9500-0c17ed305f3e", "parent_id": "3cb6b693-6d58-57a9-95b4-184f4465f6a5", "name": "程序与参数类", "category_type": "device_doc", "level": 1, "is_leaf": False, "sort_order": 4,
     "requirement_desc": ""},
    {"id": "ebb3e579-07f7-5a95-8fba-70b9cc3dbaf8", "parent_id": "d781b215-9a89-5871-9500-0c17ed305f3e", "name": "PLC程序文件", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "原始格式（如西门子.awl或源文件）和便于阅读的PDF格式，包含完整的符号表与注释"},
    {"id": "0bdedbbb-4911-5a9d-b7e9-5813cff04844", "parent_id": "d781b215-9a89-5871-9500-0c17ed305f3e", "name": "PLC I/O点定义表", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "独立表格文件，详细列出每个I/O点的物理地址、电气符号、功能描述（如：I0.0, 急停按钮, X轴正极限开关）"},
    {"id": "5fd3a0a1-38db-5dcc-9e29-79c1a52b7137", "parent_id": "d781b215-9a89-5871-9500-0c17ed305f3e", "name": "机床数据/参数文件", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "CNC所有通用参数、通道参数、轴参数、驱动参数等备份包"},
    {"id": "4e32a146-35c1-59bb-b747-89f3d1611ab5", "parent_id": "d781b215-9a89-5871-9500-0c17ed305f3e", "name": "设定数据文件", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 4,
     "requirement_desc": "用户自定义的界面配置、软限位等数据"},
    {"id": "c3668358-ee7e-57c2-8ea4-f40eb9cc8688", "parent_id": "d781b215-9a89-5871-9500-0c17ed305f3e", "name": "PLC程序与报警文本备份包", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 5,
     "requirement_desc": "确保与原机完全一致的完整项目备份"},
    {"id": "9e391465-097e-589e-b3bd-697a7a73d4bd", "parent_id": "d781b215-9a89-5871-9500-0c17ed305f3e", "name": "加工程序/宏程序存储包", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 6,
     "requirement_desc": "设备出厂自带的所有工件加工程序、宏程序文件"},
    {"id": "f0afb2fa-ff13-5449-af6a-1ba568f36cf1", "parent_id": "d781b215-9a89-5871-9500-0c17ed305f3e", "name": "刀具/砂轮管理数据", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 7,
     "requirement_desc": "初始的刀具/砂轮库配置、标准刀/砂轮补偿数据"},
    {"id": "959ea12f-c44f-593f-9e3b-196905cf86a7", "parent_id": "d781b215-9a89-5871-9500-0c17ed305f3e", "name": "零点偏置数据文件", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 8,
     "requirement_desc": "出厂设置的全部坐标系的零点偏置数据"},
    # 二级: 备件清单
    {"id": "9aaf90a3-52e4-5990-a55c-1be3237ae61e", "parent_id": "3cb6b693-6d58-57a9-95b4-184f4465f6a5", "name": "备件清单", "category_type": "device_doc", "level": 1, "is_leaf": False, "sort_order": 5,
     "requirement_desc": ""},
    {"id": "86a83d8e-9d55-5299-a5f0-5556ec585d31", "parent_id": "9aaf90a3-52e4-5990-a55c-1be3237ae61e", "name": "易损件与备件总清单", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "汇总所有推荐备件的总表，包含类别、名称、品牌、型号、订货号、制造商、推荐备件数量、所在部件图号等列"},
    {"id": "fff78058-1d5e-5dd0-adbd-d6e15ce53183", "parent_id": "9aaf90a3-52e4-5990-a55c-1be3237ae61e", "name": "电气/电子件清单", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "继电器、接触器、传感器、开关电源、熔断器、电路板等详细备件信息"},
    {"id": "db273949-f9a5-5293-a5f1-751f87048d3c", "parent_id": "9aaf90a3-52e4-5990-a55c-1be3237ae61e", "name": "流体件清单", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "电磁阀、密封圈、过滤器滤芯、液压软管、油封、接头等详细备件信息"},
    {"id": "2981b423-ea72-5fb5-b3ff-c321407b80bf", "parent_id": "9aaf90a3-52e4-5990-a55c-1be3237ae61e", "name": "机械外购件清单", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 4,
     "requirement_desc": "轴承、丝杠螺母副、线性导轨滑块、联轴器、同步带/链条等详细备件信息"},
    {"id": "abdd2572-a7db-561c-813c-9e2cd3090804", "parent_id": "9aaf90a3-52e4-5990-a55c-1be3237ae61e", "name": "厂家自制件清单", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 5,
     "requirement_desc": "明确指向机械图纸类中关键零部件图的图号列表，以作对照"},
    # 二级: 通信接口
    {"id": "3677c37f-c4de-51b1-853c-eaaacd0ea1c2", "parent_id": "3cb6b693-6d58-57a9-95b4-184f4465f6a5", "name": "通信接口", "category_type": "device_doc", "level": 1, "is_leaf": False, "sort_order": 6,
     "requirement_desc": ""},
    {"id": "06db0a7e-3333-56ee-83a1-2d661d00e79d", "parent_id": "3677c37f-c4de-51b1-853c-eaaacd0ea1c2", "name": "设备集成接口规范", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "明确列出设备支持的物理接口和通信协议：硬件接口、协议栈（OPC UA、MTConnect、Modbus TCP/IP、Profinet等支持版本、功能限制及授权说明）"},
    {"id": "4110fbaa-2dbc-5157-ab94-8e17bfe516bd", "parent_id": "3677c37f-c4de-51b1-853c-eaaacd0ea1c2", "name": "设备数据点详细说明", "category_type": "device_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "完整地址映射与含义说明表，每个数据点须含：功能描述、系统内部地址或变量名、数据类型、读写权限、数据范围与单位"},

    # ========== 设备SOP文档 (sop_doc) ==========
    {"id": "38a526b6-a1b3-5396-a59e-52386bfe1cb2", "parent_id": None, "name": "设备SOP文档", "category_type": "sop_doc", "level": 0, "is_leaf": False, "sort_order": 2,
     "requirement_desc": ""},
    # 二级: 人员资质与培训
    {"id": "17a1aa66-52b8-527b-9a67-75a300c9f88b", "parent_id": "38a526b6-a1b3-5396-a59e-52386bfe1cb2", "name": "人员资质与培训", "category_type": "sop_doc", "level": 1, "is_leaf": False, "sort_order": 1,
     "requirement_desc": ""},
    {"id": "cad82993-2ee0-5dd6-a648-47d727e8be7c", "parent_id": "17a1aa66-52b8-527b-9a67-75a300c9f88b", "name": "岗位技能矩阵/资质标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "不能只有合格的结论。具体内容：矩阵看板、资质定义（明确理论与实操的及格线）、认证规范（附岗位资格证实物模板，注明有效期和复审周期）"},
    {"id": "3da26902-3362-547b-92c2-7a8cbfcafa55", "parent_id": "17a1aa66-52b8-527b-9a67-75a300c9f88b", "name": "岗位多能工规范与要求标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "跨岗位培训路径图。具体内容：技能清单、支援机制（规定触发支援的条件以及支援期间的品质责任界定）"},
    # 二级: 设备操作与维护
    {"id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "parent_id": "38a526b6-a1b3-5396-a59e-52386bfe1cb2", "name": "设备操作与维护", "category_type": "sop_doc", "level": 1, "is_leaf": False, "sort_order": 2,
     "requirement_desc": ""},
    {"id": "75ef469f-085e-59c9-a8f0-d21e87be7aec", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "设备操作标准(SOP)", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "图文并茂而非纯文字。具体内容：开机九步法、操作界面截图。避免只贴设备说明书，要转化为工人的动作"},
    {"id": "9a5073ba-3fc7-5e67-8c6c-cef81afbb2c4", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "日常点检标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "基于感官和简易工具。具体内容：点检部位图、量化标准。避免检查是否正常这种主观描述，必须量化"},
    {"id": "1a7481f9-62b3-5de3-ac29-ad23745d3e64", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "定期保养标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "时间与职责分流。具体内容：分级执行、备件提前期。避免把所有保养全写一起，要按频次和角色分页"},
    {"id": "abe9f61c-4e5b-5164-81e5-ff81f3444f9d", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "工装备件标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 4,
     "requirement_desc": "卡物一致与寿命预警。具体内容：备件身份证、更换教程。避免只提供厂家采购清单，要有自制/修旧利废的标准"},
    {"id": "08e8ad9c-bf45-5605-aecc-0fb175ad93d1", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "设备运行工艺参数标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 5,
     "requirement_desc": "权限与参数的物理隔离。具体内容：参数对照表、锁闭证据。不能只给参数范围，必须明确严禁自行调整并写入操作证考核"},
    {"id": "2411422d-f299-553a-8c64-19a700bda027", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "设备变更操作指导书", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 6,
     "requirement_desc": "恢复生产的强制验证点。具体内容：场景细化。避免仔细检查的笼统写法，必须列出具体动作和数据"},
    {"id": "bab77da4-1c00-5947-8651-80fcceebb7cb", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "设备异常反应计划", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 7,
     "requirement_desc": "可执行的响应树。具体内容：现象词典、逐级上报流程图。避免只写及时上报，要带人名、电话、权限边界"},
    {"id": "79bad634-855b-5776-b62e-3aea568ebf67", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "标准工时", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 8,
     "requirement_desc": "作业分解与山积表。具体内容：工序拆解、区分周期。避免给笼统的总时间，要能看出可改善的浪费"},
    {"id": "09a30c8d-3ef8-59da-8bd8-496a82f0555d", "parent_id": "b1f3ca86-8ec8-59bc-8edf-51f599f84b37", "name": "防错装置验证标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 9,
     "requirement_desc": "破坏性试验与验证频次。具体内容：装置清单、黑盒测试记录"},
    # 二级: 物料与检验
    {"id": "88b8058f-78e5-5940-8d3e-0fcdc2ba9bc0", "parent_id": "38a526b6-a1b3-5396-a59e-52386bfe1cb2", "name": "物料与检验", "category_type": "sop_doc", "level": 1, "is_leaf": False, "sort_order": 3,
     "requirement_desc": ""},
    {"id": "a42aa059-e488-50e4-88ec-acf203f7ef94", "parent_id": "88b8058f-78e5-5940-8d3e-0fcdc2ba9bc0", "name": "来料/上工序接受标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "不可逾越的红线清单。具体内容：拒收准则、让步接收"},
    {"id": "9b171416-3fb1-51e3-b7aa-04202c1803fe", "parent_id": "88b8058f-78e5-5940-8d3e-0fcdc2ba9bc0", "name": "物料标识与批次管理", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "目视化与FIFO物理实现。具体内容：颜色与符号、FIFO逻辑"},
    {"id": "a3cd3fbd-39de-5e2a-81b9-04be42f72830", "parent_id": "88b8058f-78e5-5940-8d3e-0fcdc2ba9bc0", "name": "产品检验标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "取样规则与边界样品。具体内容：采样频次、视密度测定SOP、限度样品。避免只复制国标文字，必须转化为具象的判定依据"},
    {"id": "2f270952-055e-50c2-b6dd-4520149cce6d", "parent_id": "88b8058f-78e5-5940-8d3e-0fcdc2ba9bc0", "name": "不合格品处理标准及反应计划", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 4,
     "requirement_desc": "质量阀与追溯链路。具体内容：处置矩阵、追溯要求"},
    {"id": "f6e7a648-1651-5e2d-9a35-eba81b72d5f2", "parent_id": "88b8058f-78e5-5940-8d3e-0fcdc2ba9bc0", "name": "材料/辅料消耗定额", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 5,
     "requirement_desc": "BOM表与损耗率。具体内容：理论净重+工艺损耗、领料限制"},
    {"id": "e73f1d2f-f013-59bb-b418-fb2a8928d586", "parent_id": "88b8058f-78e5-5940-8d3e-0fcdc2ba9bc0", "name": "在制品(WIP)标准存量", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 6,
     "requirement_desc": "时间管理比数量管理更重要。具体内容：时效指标、暂存环境"},
    # 二级: 环境与安全
    {"id": "37ad0382-73e4-56b4-afa7-e850a99279b3", "parent_id": "38a526b6-a1b3-5396-a59e-52386bfe1cb2", "name": "环境与安全", "category_type": "sop_doc", "level": 1, "is_leaf": False, "sort_order": 4,
     "requirement_desc": ""},
    {"id": "130acf86-b2d8-5bfb-a715-0340b4fb1f9e", "parent_id": "37ad0382-73e4-56b4-afa7-e850a99279b3", "name": "环境参数标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "监控点位与监测频率。具体内容：颗粒度（温度冬夏两季标准、湿度重点监控低湿报警、粉尘浓度规定车间内部环境粉尘最高限值）、控制手段"},
    {"id": "aa617a69-793f-5aa5-a4af-86f4537046c0", "parent_id": "37ad0382-73e4-56b4-afa7-e850a99279b3", "name": "5S与安全操作标准", "category_type": "sop_doc", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "高风险作业与应急演练痕迹。具体内容：PPE穿戴图、应急设施检查表、清理SOP"},

    # ========== 合规性文档 (compliance) ==========
    {"id": "483a9028-5aba-5263-a23a-09c0999e8b7d", "parent_id": None, "name": "合规性文档", "category_type": "compliance", "level": 0, "is_leaf": False, "sort_order": 3,
     "requirement_desc": ""},
    # 许可与证照
    {"id": "940a9f7b-61b5-50bf-9def-dcc03c4165c2", "parent_id": "483a9028-5aba-5263-a23a-09c0999e8b7d", "name": "许可与证照", "category_type": "compliance", "level": 1, "is_leaf": False, "sort_order": 1,
     "requirement_desc": ""},
    {"id": "06c27778-5a1f-581b-8c20-3c5493b7ee0c", "parent_id": "940a9f7b-61b5-50bf-9def-dcc03c4165c2", "name": "安全生产许可证", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "需加盖企业公章，有效期内在安全生产许可证查询平台可验证。识别有效期、盖章和签名"},
    {"id": "8669c956-bf13-59ed-ba02-5acc41cec8a9", "parent_id": "940a9f7b-61b5-50bf-9def-dcc03c4165c2", "name": "排污许可证", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "需加盖企业公章，有效期内在排污许可证管理平台可验证。识别有效期、盖章和签名"},
    {"id": "3db5e20e-90d9-5ab9-9686-879560665ccd", "parent_id": "940a9f7b-61b5-50bf-9def-dcc03c4165c2", "name": "消防验收意见书", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "需加盖消防部门公章，识别有效期、盖章"},
    {"id": "221d2ec2-c396-5354-8336-987e687c8243", "parent_id": "940a9f7b-61b5-50bf-9def-dcc03c4165c2", "name": "特种设备使用登记证", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 4,
     "requirement_desc": "需加盖质监部门公章，登记证编号清晰可查。识别有效期、盖章"},
    # 应急管理
    {"id": "cad35a49-d8be-5eaf-86ea-54135cf6557c", "parent_id": "483a9028-5aba-5263-a23a-09c0999e8b7d", "name": "应急管理", "category_type": "compliance", "level": 1, "is_leaf": False, "sort_order": 2,
     "requirement_desc": ""},
    {"id": "dac1ba34-a6fa-55b1-b372-4a00c5c05ed3", "parent_id": "cad35a49-d8be-5eaf-86ea-54135cf6557c", "name": "环境应急预案备案表", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "需加盖企业公章及环保部门备案章。识别有效期、盖章和签名"},
    {"id": "4c80dc5c-1036-5464-8234-cfdfeb4191ca", "parent_id": "cad35a49-d8be-5eaf-86ea-54135cf6557c", "name": "安全生产事故应急预案", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "需加盖企业公章。识别有效期、盖章和签名"},
    {"id": "b642f394-57e6-570d-8251-d2de41c88178", "parent_id": "cad35a49-d8be-5eaf-86ea-54135cf6557c", "name": "应急演练记录", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "每年至少一次，含演练照片、签到表、总结报告。识别日期和签名"},
    # 人员资质
    {"id": "84f4eb01-ed88-5206-8e36-c89d7bcebf3b", "parent_id": "483a9028-5aba-5263-a23a-09c0999e8b7d", "name": "人员资质", "category_type": "compliance", "level": 1, "is_leaf": False, "sort_order": 3,
     "requirement_desc": ""},
    {"id": "cf9a8360-3892-5f1c-a8bd-60f2d2a88d1a", "parent_id": "84f4eb01-ed88-5206-8e36-c89d7bcebf3b", "name": "特种作业人员操作证", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "电工、焊工、起重工等。识别有效期、盖章"},
    {"id": "ec0464b3-cd83-50bd-9c4a-c5f251cca288", "parent_id": "84f4eb01-ed88-5206-8e36-c89d7bcebf3b", "name": "安全管理人员资格证", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "主要负责人和安全管理人员的资格证书。识别有效期、盖章"},
    # 检测报告
    {"id": "ef09c09a-0682-59b2-9ea4-8d0bea903340", "parent_id": "483a9028-5aba-5263-a23a-09c0999e8b7d", "name": "检测报告", "category_type": "compliance", "level": 1, "is_leaf": False, "sort_order": 4,
     "requirement_desc": ""},
    {"id": "84a4b2ee-f470-5315-b5ab-6e674818920b", "parent_id": "ef09c09a-0682-59b2-9ea4-8d0bea903340", "name": "防雷检测报告", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 1,
     "requirement_desc": "每年一次，由具备资质的检测机构出具。识别有效期、盖章"},
    {"id": "a13c7a59-d9d0-56d2-ad6e-4d7053116bec", "parent_id": "ef09c09a-0682-59b2-9ea4-8d0bea903340", "name": "职业病危害因素检测报告", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 2,
     "requirement_desc": "每年一次。识别有效期、盖章"},
    {"id": "2c4799b1-5fb2-5143-9ee7-4e8c96bf414f", "parent_id": "ef09c09a-0682-59b2-9ea4-8d0bea903340", "name": "消防设施检测报告", "category_type": "compliance", "level": 2, "is_leaf": True, "sort_order": 3,
     "requirement_desc": "每年一次。识别有效期、盖章"},
]


def seed_preset_categories(db: Session, force: bool = False):
    """幂等插入预设类别种子数据。
    force=True 时：清空表重新插入（用于修复数据污染）。
    """
    import logging
    logger = logging.getLogger(__name__)

    # 强制模式：清空再重建
    if force:
        deleted = db.query(PresetCategory).delete()
        db.commit()
        logger.info("强制清空预设类别表: 删除=%d", deleted)

    inserted = 0
    updated = 0
    errors = 0
    for item in PRESET_CATEGORIES:
        try:
            existing = db.query(PresetCategory).filter(PresetCategory.id == item["id"]).first()
            if existing:
                existing.name = item["name"]
                existing.requirement_desc = item["requirement_desc"]
                existing.category_type = item["category_type"]
                existing.level = item["level"]
                existing.is_leaf = item["is_leaf"]
                existing.sort_order = item["sort_order"]
                existing.parent_id = item.get("parent_id")
                existing.is_active = True
                updated += 1
            else:
                db.add(PresetCategory(
                    id=item["id"], parent_id=item.get("parent_id"),
                    name=item["name"], requirement_desc=item["requirement_desc"],
                    category_type=item["category_type"], level=item["level"],
                    is_leaf=item["is_leaf"], sort_order=item["sort_order"],
                ))
                inserted += 1
        except Exception as e:
            errors += 1
            logger.error("预设类别写入失败 id=%s name=%s: %s", item.get("id"), item.get("name"), e)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("预设类别提交失败: %s", e)
        return {"status": "error", "message": str(e)}
    logger.info("预设类别种子完成: 新增=%d 更新=%d 错误=%d 总计=%d", inserted, updated, errors, len(PRESET_CATEGORIES))
    return {"status": "ok", "inserted": inserted, "updated": updated, "errors": errors, "total": len(PRESET_CATEGORIES)}
