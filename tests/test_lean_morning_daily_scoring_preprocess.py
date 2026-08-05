"""第四份报告评分所需点检班次预处理测试。"""

from __future__ import annotations

from backend.utils.data_preprocessor import prep_maintain_task


def test_maintain_preprocess_preserves_shift_scoring_data() -> None:
    """点检预处理应保留白夜班执行数及异常闭环证据。"""
    data = {
        "records": [
            {
                "deviceName": "1#线",
                "startTime": "2026-07-20 06:00:00",
                "execTime": "2026-07-20 07:00:00",
                "status": "已执行",
                "execResult": "正常",
                "children": [],
            },
            {
                "deviceName": "1#线",
                "startTime": "2026-07-20 18:00:00",
                "execTime": "2026-07-20 18:10:00",
                "status": "已执行",
                "execResult": "异常",
                "repairNo": "",
                "children": [
                    {
                        "execResult": "异常",
                        "name": "压力",
                        "content": "5.6-8MPa",
                        "actValue": "9.6",
                    }
                ],
            },
        ]
    }

    result = prep_maintain_task(data)

    assert result is not None
    assert result["byClass"] == [
        {
            "className": "夜班",
            "total": 1,
            "executed": 1,
            "closed": 0,
            "notExecuted": 0,
            "abnormal": 1,
        },
        {
            "className": "白班",
            "total": 1,
            "executed": 1,
            "closed": 0,
            "notExecuted": 0,
            "abnormal": 0,
        },
    ]
    assert result["abnormalDetails"][0]["className"] == "夜班"
    assert result["abnormalDetails"][0]["repairNo"] == ""
