# cython: annotation_typing=False, infer_types=False, language_level=3
"""系统管理 · 设备列表管理。

参数分析页(/device-params)的设备下拉框以前是写死在代码里的（球磨机白名单 +
每类型最多3台，见 modules/device_param/services.py 里 get_devices() 的历史逻辑）。
这里给管理员一个页面：

  ① 从 MySQL 业务库(jxcw) 同步设备清单到 device_info（复用
     deploy/docker/scripts/sync_device_dict.py 已验证过的取数逻辑，做成按钮）
  ② 勾选哪些设备要出现在参数分析页下拉框（device_info.visible_in_params，
     见 services.ensure_visible_in_params_column() 的迁移说明）

同步只增改 device_id/device_name，绝不碰 visible_in_params——设备的可见性
完全由管理员在这个页面手动维护，不会被重新同步覆盖掉。
"""
import os
from typing import Any, Dict, List, Optional

import psycopg2
import pymysql
import pymysql.cursors
from fastapi import APIRouter
from psycopg2.extras import RealDictCursor, execute_values
from pydantic import BaseModel

from core.pg_env import pg_params
from core.response import error_response, success_response
from modules.device_param.services import ensure_visible_in_params_column

router = APIRouter(prefix="/api/system", tags=["device-config"])


def _connect_mysql():
    """连业务库(jxcw)取设备字典——跟 TimescaleDB.connect_mysql() 不是同一个库
    (那个是 AQA_MYSQL_*/btr，运行状态/告警字典)，这里固定读 MYSQL_* 这套。"""
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "jxcw"),
        charset="utf8mb4",
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _fetch_devices_from_mysql(my) -> List[Dict[str, Any]]:
    """跟 deploy/docker/scripts/sync_device_dict.py 的 fetch_devices_from_mysql() 同一套查询。"""
    sql = """
        SELECT p.device_no, d.name AS device_name, d.id
        FROM (SELECT DISTINCT device_no, device_id FROM dev_device_param
              WHERE device_no IS NOT NULL AND device_no <> '') p
        JOIN dev_device d ON d.id = p.device_id
        WHERE d.del_flag = 0
        ORDER BY d.id
    """
    with my.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    seen, devices = set(), []
    for r in rows:
        if r["device_no"] in seen:
            continue
        seen.add(r["device_no"])
        devices.append(r)
    return devices


def _device_type(device_id: str) -> str:
    if device_id.startswith("BTR-QSDLQM"):
        return "球磨机"
    if device_id.startswith("BTR-QSDLHG"):
        return "合膏机"
    if device_id.startswith("BTR-QSDLGH"):
        return "固化室"
    return "其他"


@router.get("/devices")
def list_devices():
    """设备列表管理页用：device_info 全表（不按可见性过滤），带设备类型分组和当前可见状态。"""
    conn = None
    try:
        conn = psycopg2.connect(**pg_params())
        ensure_visible_in_params_column(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT device_id AS device_code, device_name, visible_in_params
                FROM device_info
                ORDER BY device_id
            """)
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["device_type"] = _device_type(r["device_code"])
        return success_response(data={"devices": rows, "count": len(rows)})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"读取设备列表失败: {e}", code=500)
    finally:
        if conn:
            conn.close()


class DeviceVisibilityItem(BaseModel):
    device_id: str
    visible: bool


class DeviceVisibilityRequest(BaseModel):
    devices: List[DeviceVisibilityItem]


@router.post("/devices/visibility")
def save_device_visibility(req: DeviceVisibilityRequest):
    """批量保存"这台设备要不要出现在参数分析页下拉框"。"""
    if not req.devices:
        return error_response(msg="devices 不能为空", code=400)
    conn = None
    try:
        conn = psycopg2.connect(**pg_params())
        ensure_visible_in_params_column(conn)
        with conn.cursor() as cur:
            # execute_values 超过一页(默认100行)会分多批执行，rowcount 只反映最后一批，
            # 不能用来报总数——这里只是批量写入的效率手段，成功与否看有没有抛异常，
            # 报给前端的"改了几条"直接用请求里的条数即可。
            execute_values(
                cur,
                """UPDATE device_info AS di SET visible_in_params = v.visible
                   FROM (VALUES %s) AS v(device_id, visible)
                   WHERE di.device_id = v.device_id""",
                [(d.device_id, d.visible) for d in req.devices],
            )
        conn.commit()
        return success_response(data={"updated": len(req.devices)})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"保存设备可见性失败: {e}", code=500)
    finally:
        if conn:
            conn.close()


@router.post("/devices/sync")
def sync_devices():
    """从 MySQL(jxcw) 同步设备清单到 device_info——只 upsert device_name/id，
    不碰 visible_in_params(新设备默认 false，需要管理员手动勾选可见)。
    """
    my = pg = None
    try:
        my = _connect_mysql()
        devices = _fetch_devices_from_mysql(my)
        if not devices:
            return success_response(data={"synced": 0, "total_mysql": 0},
                                    msg="MySQL 里没有可同步的设备定义")

        pg = psycopg2.connect(**pg_params())
        ensure_visible_in_params_column(pg)
        with pg.cursor() as cur:
            execute_values(
                cur,
                """INSERT INTO device_info (device_id, device_name, id) VALUES %s
                   ON CONFLICT (device_id) DO UPDATE
                   SET device_name = EXCLUDED.device_name, id = EXCLUDED.id""",
                [(d["device_no"], d["device_name"], d["id"]) for d in devices],
            )
        pg.commit()
        return success_response(data={"synced": len(devices), "total_mysql": len(devices)},
                                msg=f"已同步 {len(devices)} 台设备")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(msg=f"同步设备列表失败: {e}", code=500)
    finally:
        if my:
            my.close()
        if pg:
            pg.close()
