"""
Agentic QA 端到端集成测试脚本。

用法（先启动后端）：
    # 安装依赖
    pip install requests

    # 运行测试
    python tests/test_agentic_query.py                    # 默认循环 3 次
    python tests/test_agentic_query.py --loops 5          # 循环 5 次
    python tests/test_agentic_query.py --verbose           # 详细输出
    python tests/test_agentic_query.py --question "你的问题"  # 自定义问题
"""
import argparse
import json
import sys
import time
import uuid
import requests

BASE_URL = "http://localhost:9300"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "adminchaowei123"
DEFAULT_QUESTION = "最近一个月制带机都出了什么问题，哪台设备坏的最多"


def login(username=DEFAULT_USERNAME, password=DEFAULT_PASSWORD):
    """登录获取 JWT token。"""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    # 兼容两种响应格式: {"token": ...} 或 {"code":200, "data":{"token": ...}}
    if "data" in data and isinstance(data["data"], dict):
        return data["data"]["token"]
    return data["token"]


def query(token, question, session_id=None, confirmed_entities=None, verbose=False):
    """调用 /api/query 或 /api/query/confirm。"""
    headers = {"Authorization": f"Bearer {token}"}
    sid = session_id or str(uuid.uuid4())

    if confirmed_entities:
        body = {
            "question": question,
            "session_id": sid,
            "confirmed_entities": confirmed_entities,
        }
        url = f"{BASE_URL}/api/query/confirm"
    else:
        body = {
            "question": question,
            "session_id": sid,
        }
        url = f"{BASE_URL}/api/query"

    if verbose:
        print(f"  -> POST {url}")
        print(f"     body: {json.dumps(body, ensure_ascii=False)[:200]}")

    resp = requests.post(url, json=body, headers=headers, timeout=300)
    resp.raise_for_status()
    return resp.json(), sid


def check_response(data, verbose=False):
    """检查响应质量，返回 (passed: bool, issues: list[str])。"""
    issues = []

    # 1. 基本成功
    if not data.get("success"):
        issues.append(f"success=False")

    # 2. 不应是澄清请求（直接查应能处理）
    if data.get("needs_clarification"):
        if verbose:
            groups = data.get("clarification_groups") or []
            print(f"     澄清: {json.dumps(groups, ensure_ascii=False)[:300]}")
        issues.append("needs_clarification=True（未直接回答）")

    # 3. 回答不应是兜底文本
    answer = data.get("answer", "")
    fallback_texts = [
        "抱歉，多次尝试后仍无法获取正确数据",
        "查询返回",
        "条数据。",
    ]
    is_fallback = any(ft in answer for ft in fallback_texts)
    if is_fallback or len(answer.strip()) < 20:
        issues.append(f"answer 是兜底文本或过短: {answer[:80]}")

    # 4. SQL 应该存在
    sql = data.get("sql")
    if not sql:
        issues.append("sql=None（未生成 SQL）")
    else:
        # SQL 应该查正确的表（dev_repair_order 或 dev_device）
        sql_upper = sql.upper()
        correct_tables = ["DEV_REPAIR_ORDER", "DEV_DEVICE"]
        if not any(t in sql_upper for t in correct_tables):
            issues.append(f"SQL 未查询正确表: {sql[:100]}")

    # 5. 结果应非空
    results = data.get("results")
    result_groups = data.get("result_groups")
    if not results and not result_groups:
        issues.append("results 和 result_groups 都为空")
    elif results is not None and len(results) == 0:
        issues.append("results=[]（空结果集）")

    # 6. 诊断信息
    if verbose:
        safe_answer = answer[:120].encode('gbk', errors='replace').decode('gbk')
        print(f"     answer: {safe_answer}")
        if sql:
            print(f"     sql: {sql[:150]}")
        if results:
            print(f"     results: {len(results)} rows")
        if result_groups:
            print(f"     result_groups: {len(result_groups)} groups")

    return len(issues) == 0, issues


def run_single_test(token, question, loop_idx, verbose=False):
    """单次完整测试流程（可能含确认实体）。"""
    print(f"\n{'='*60}")
    print(f"  第 {loop_idx + 1} 轮测试")
    print(f"  问题: {question}")
    print(f"{'='*60}")

    total_start = time.time()
    session_id = str(uuid.uuid4())
    issues_all = []

    # 第一次查询
    try:
        data, sid = query(token, question, session_id, verbose=verbose)
    except Exception as e:
        print(f"  [FAIL] 请求异常: {e}")
        return False, [str(e)]

    # 如果需要澄清，自动确认后重试
    if data.get("needs_clarification"):
        print(f"  [INFO] 返回了澄清请求，自动确认实体后重试...")
        groups = data.get("clarification_groups") or []
        confirmed = []
        for g in groups:
            if isinstance(g, dict):
                values = g.get("values") or g.get("options") or []
                if values:
                    confirmed.append({
                        "field": g.get("field", g.get("entity_type", "")),
                        "values": values[:3],  # 取前3个
                    })
        if confirmed:
            if verbose:
                print(f"     确认实体: {json.dumps(confirmed, ensure_ascii=False)}")
            try:
                data, sid = query(token, question, sid, confirmed_entities=confirmed, verbose=verbose)
            except Exception as e:
                print(f"  [FAIL] 确认后请求异常: {e}")
                return False, [str(e)]

    elapsed = round((time.time() - total_start) * 1000)
    passed, issues = check_response(data, verbose)

    status = "PASS" if passed else "FAIL"
    print(f"\n  [{status}] 耗时 {elapsed}ms")
    if issues:
        for issue in issues:
            print(f"    - {issue}")

    return passed, issues


def main():
    global BASE_URL

    parser = argparse.ArgumentParser(description="Agentic QA 端到端测试")
    parser.add_argument("--loops", type=int, default=3, help="测试循环次数 (默认 3)")
    parser.add_argument("--question", type=str, default=DEFAULT_QUESTION, help="测试问题")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--username", type=str, default=DEFAULT_USERNAME)
    parser.add_argument("--password", type=str, default=DEFAULT_PASSWORD)
    parser.add_argument("--url", type=str, default=BASE_URL, help="后端地址")
    args = parser.parse_args()

    BASE_URL = args.url

    print(f"Agentic QA 端到端测试")
    print(f"后端: {BASE_URL}")
    print(f"循环: {args.loops} 次")
    print(f"问题: {args.question}")

    # 登录
    try:
        token = login(args.username, args.password)
        print(f"登录成功")
    except Exception as e:
        print(f"登录失败: {e}")
        sys.exit(1)

    # 运行测试
    results = []
    for i in range(args.loops):
        passed, issues = run_single_test(token, args.question, i, verbose=args.verbose)
        results.append({"loop": i + 1, "passed": passed, "issues": issues})

    # 汇总
    print(f"\n{'='*60}")
    print(f"  测试汇总")
    print(f"{'='*60}")
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = total - passed_count

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        line = f"  第 {r['loop']} 轮: [{status}]"
        if r["issues"]:
            line += " " + "; ".join(r["issues"])
        print(line)

    print(f"\n  通过: {passed_count}/{total}  失败: {failed_count}/{total}")

    if failed_count > 0:
        # 分类统计失败原因
        issue_types = {}
        for r in results:
            for issue in r["issues"]:
                key = issue.split(":")[0].split("（")[0].strip()
                issue_types[key] = issue_types.get(key, 0) + 1
        print(f"\n  失败原因分布:")
        for k, v in sorted(issue_types.items(), key=lambda x: -x[1]):
            print(f"    {k}: {v} 次")

    print()
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
