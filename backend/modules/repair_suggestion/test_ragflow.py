# cython: annotation_typing=False, infer_types=False, language_level=3
import asyncio
import sys
sys.path.insert(0, '.')

from services.ragflow_service import RAGFlowService


async def test_connection():
    print("=" * 60)
    print("测试RAGFlow连接")
    print("=" * 60)

    ragflow = RAGFlowService()

    # 测试：直接用chat查询
    print("\n[测试1] 查询历史维修单")
    answer, err = await ragflow.query_history_repair_orders(
        "3#负连铸线",
        "超声波烘干机",
        "负连铸三号机超声波烘干机故障"
    )
    if err:
        print(f"❌ 查询失败: {err}")
    else:
        print(f"✅ 查询结果:\n{answer}")

    print("\n" + "=" * 60)
    print("✅ 所有测试完成!")


if __name__ == "__main__":
    asyncio.run(test_connection())
