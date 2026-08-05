# cython: annotation_typing=False, infer_types=False, language_level=3
"""
上游系统客户端
封装对上游系统的 HTTP 调用（拉参与回写），自带重试与鉴权
支持 Mock 模式：UPSTREAM_MOCK=true 时，拉参使用 lean.json 本地数据，回调仅打印日志
"""
import os
import time
import json
import logging
import requests

logger = logging.getLogger(__name__)


class UpstreamClient:
    """上游系统 HTTP 客户端，封装拉参与回调接口"""

    def __init__(
        self,
        base_url: str = None,
        secret: str = None,
        timeout: float = 600.0,
        max_retries: int = 3,
        mock: bool = None,
    ):
        """
        初始化上游客户端

        Args:
            base_url: 上游系统基础地址（如 http://CHANGE_ME:8080）
            secret: 内部服务鉴权密钥（X-Internal-Service-Secret 请求头）
            timeout: 单次请求超时秒数
            max_retries: 5xx/网络错误最大重试次数
            mock: 是否启用 Mock 模式（为 None 时从环境变量 UPSTREAM_MOCK 读取）
        """
        # 注意：上游网关可能需要裸地址（不带 http://），但 requests 库必须要有协议
        # 这里保留 http:// 让 requests 正常工作，实际请求地址会在日志中显示
        url = base_url or os.getenv("UPSTREAM_BASE_URL", "")
        if url and not url.startswith(("http://", "https://")):
            url = "http://" + url
        self.base_url = url.rstrip("/")
        self.secret = secret or os.getenv("UPSTREAM_SECRET", "")
        self.timeout = timeout or float(os.getenv("UPSTREAM_TIMEOUT", "30"))
        self.max_retries = max_retries or int(os.getenv("UPSTREAM_RETRY_COUNT", "3"))

        # Mock 模式：默认从环境变量读取
        if mock is not None:
            self.mock = mock
        else:
            self.mock = os.getenv("UPSTREAM_MOCK", "false").lower() == "true"


        # Mock 模式下加载本地测试数据
        self._mock_payload_cache = None

        if self.mock:
            logger.info("[UpstreamClient] Mock 模式已启用，拉参将使用 lean.json，回调仅打印日志")
        elif not self.base_url:
            logger.warning("[UpstreamClient] UPSTREAM_BASE_URL 未配置，拉参/回调功能不可用")
        else:
            logger.info("[UpstreamClient] 上游地址: %s", self.base_url)

    def _load_mock_payload(self, mock_name: str = None) -> dict:
        """
        加载 Mock 拉参数据（带缓存）

        Args:
            mock_name: Mock 数据文件名（不含 .json 后缀），
                      默认为 None 时加载 lean.json

        Returns:
            Mock 数据解析后的字典
        """
        if self._mock_payload_cache is not None and mock_name is None:
            return self._mock_payload_cache

        if mock_name:
            filename = f"{mock_name}.json"
        else:
            filename = "lean.json"

        mock_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            filename
        )

        if not os.path.exists(mock_path):
            raise FileNotFoundError(f"Mock 数据文件不存在: {mock_path}")

        with open(mock_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        logger.info("[UpstreamClient] Mock 数据已加载: %s", mock_path)

        if mock_name is None:
            self._mock_payload_cache = payload

        return payload

    def _build_headers(self) -> dict:
        """构建鉴权请求头"""
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-Internal-Service-Secret"] = self.secret
        return headers

    def _request_with_retry(self, method: str, path: str, **kwargs) -> requests.Response:
        """
        带指数退避重试的 HTTP 请求

        - 4xx：不重试，直接抛异常
        - 5xx / 网络错误：指数退避重试 max_retries 次

        Args:
            method: HTTP 方法 (GET / POST)
            path: 请求路径（会拼接 base_url）
            **kwargs: 传递给 requests 的额外参数

        Returns:
            requests.Response

        Raises:
            requests.HTTPError: 4xx 响应
            Exception: 重试耗尽后仍失败
        """
        url = f"{self.base_url}{path}"
        headers = self._build_headers()
        kwargs.setdefault("headers", headers)
        kwargs.setdefault("timeout", self.timeout)

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(method, url, **kwargs)

                if resp.status_code < 400:
                    return resp

                # 4xx 不重试
                if 400 <= resp.status_code < 500:
                    logger.error(
                        "[UpstreamClient] 请求失败(4xx, 不重试) url=%s status=%s body=%s",
                        url, resp.status_code, resp.text[:500]
                    )
                    resp.raise_for_status()

                # 5xx 继续重试
                logger.warning(
                    "[UpstreamClient] 请求失败(5xx) url=%s status=%s 尝试 %d/%d",
                    url, resp.status_code, attempt, self.max_retries
                )
                last_exc = requests.HTTPError(f"{resp.status_code} {resp.text[:200]}")

            except requests.ConnectionError as e:
                logger.warning(
                    "[UpstreamClient] 连接失败 url=%s 尝试 %d/%d: %s",
                    url, attempt, self.max_retries, e
                )
                last_exc = e

            # 指数退避：1s, 2s, 4s ...
            if attempt < self.max_retries:
                wait = 2 ** (attempt - 1)
                time.sleep(wait)

        # 重试耗尽
        raise Exception(f"上游请求失败，已重试 {self.max_retries} 次: {last_exc}")

    def pull_lean_morning_daily_params(
        self,
        workshop_id: int,
        procedure_id: int,
        report_date: str = None,
    ) -> dict:
        """
        拉取精益早会日报参数

        GET /report/ai-agent/lean-morning-daily/param?workshopId=x&procedureId=y&reportDate=z

        Mock 模式下：直接读取 lean.json，返回 reportId=1 + payload

        Args:
            workshop_id: 车间 ID
            procedure_id: 工序 ID
            report_date: 报告日期（可选，默认昨日）

        Returns:
            {"reportId": int, "payload": dict}
            - reportId: 上游系统生成的报告 ID，回写时需要
            - payload: 传给报告生成器的完整数据（含 reportCode、meta、data 等）

        Raises:
            Exception: 拉参失败
        """
        logger.info(
            "[UpstreamClient] 拉取精益早会日报参数: workshopId=%s, procedureId=%s, reportDate=%s",
            workshop_id, procedure_id, report_date or "默认昨日"
        )

        # ---- Mock 模式 ----
        if self.mock:
            payload = self._load_mock_payload()
            # 用传入参数覆盖 meta 中的值，保证一致性
            if "meta" not in payload or not isinstance(payload["meta"], dict):
                payload["meta"] = {}
            payload["meta"]["workshopId"] = workshop_id
            payload["meta"]["procedureId"] = procedure_id
            if report_date:
                payload["meta"]["period"] = report_date

            logger.info(
                "[UpstreamClient] [Mock] 拉参返回: reportId=1, payload keys=%s",
                list(payload.keys())
            )
            return {"reportId": 1, "payload": payload}

        # ---- 真实模式 ----
        params = {
            "workshopId": workshop_id,
            "procedureId": procedure_id,
        }
        if report_date:
            params["reportDate"] = report_date

        path = "/report/ai-agent/lean-morning-daily/param"
        full_url = f"{self.base_url}{path}"
        logger.info("[UpstreamClient] 拉参请求: %s params=%s", full_url, params)

        resp = self._request_with_retry(
            "GET",
            path,
            params=params,
        )
        resp.raise_for_status()

        result = resp.json()
        logger.debug("[UpstreamClient] 拉参响应（前1000字符）: %s",
                     json.dumps(result, ensure_ascii=False)[:1000])

        # 先检查业务状态码（必须在解析数据前）
        resp_code = result.get("code")
        if resp_code is not None and resp_code != 200:
            error_msg = result.get("msg") or result.get("message") or f"上游返回业务失败 code={resp_code}"
            logger.error("[UpstreamClient] 上游业务失败: code=%s, msg=%s", resp_code, error_msg)
            raise Exception(f"上游拉参失败（code={resp_code}）: {error_msg}")

        # 兼容不同的响应格式
        if "data" in result and isinstance(result["data"], dict):
            data = result["data"]
            logger.info("[UpstreamClient] 使用 result.data 作为数据源")
        elif "result" in result and isinstance(result["result"], dict):
            data = result["result"]
            logger.info("[UpstreamClient] 使用 result.result 作为数据源")
        else:
            data = result
            logger.info("[UpstreamClient] 使用根对象作为数据源")

        report_id = data.get("reportId") or data.get("report_id") or data.get("id")
        payload = data.get("payload", data)

        # reportId 为空时直接报错，不做默认值处理
        if report_id is None:
            raise Exception(
                f"上游未返回 reportId！可用字段: {list(data.keys())}。"
                f"请检查上游接口是否正确返回了报告ID"
            )

        if report_id is None:
            logger.warning(
                "[UpstreamClient] ⚠️  未获取到 reportId！可用字段: %s",
                list(data.keys())
            )

        logger.info(
            "[UpstreamClient] 拉参成功: reportId=%s, payload keys=%s",
            report_id, list(payload.keys()) if isinstance(payload, dict) else "N/A"
        )

        return {"reportId": report_id, "payload": payload}

    def callback_complete(
        self,
        report_id: int,
        status: str,
        markdown_content: str = "",
        summary_markdown: str = "",
        kb_report_markdown: str = "",
        knowledge_base_payload: str = "",
        agent_response_raw: str = "",
        error_message: str = "",
        team_compare_markdown: str = "",
    ) -> dict:
        """
        回写报告生成结果

        POST /report/ai-agent/callback/complete

        Mock 模式下：仅打印回调内容摘要，不发送 HTTP 请求

        Args:
            report_id: 上游报告 ID
            status: "0" 成功 / "1" 失败
            markdown_content: 日会早报内容（第1份报告 → markdownContent）
            summary_markdown: 日会早报改善建议（第3份报告 → summaryMarkdown）
            kb_report_markdown: 日会早报趋势分析内容（第2份报告 → kbReportMarkdown）
            knowledge_base_payload: 趋势分析的引用信息 JSON（第2份报告 citations → knowledgeBasePayload）
            agent_response_raw: 全部原始报告 JSON（→ agentResponseRaw）
            error_message: 失败原因
            team_compare_markdown: 班次/班组绩效对比内容（第4份报告 → teamCompareMarkdown）

        Returns:
            回调响应体（Mock 模式下返回模拟成功响应）

        Raises:
            Exception: 回调失败
        """
        body = {
            "reportId": report_id,
            "status": status,
        }

        # 只在成功时填充报告字段
        if status == "0":
            body["markdownContent"] = markdown_content
            body["kbReportMarkdown"] = kb_report_markdown
            body["knowledgeBasePayload"] = knowledge_base_payload
            body["summaryMarkdown"] = summary_markdown
            # 该回调客户端被多类报告共用，只有日报传入第四份报告时才扩展请求体。
            if team_compare_markdown:
                body["teamCompareMarkdown"] = team_compare_markdown
            body["agentResponseRaw"] = agent_response_raw

        if error_message:
            body["errorMessage"] = error_message

        logger.info(
            "[UpstreamClient] 回调上游: reportId=%s, status=%s, "
            "markdownContent=%d字, kbReportMarkdown=%d字, summaryMarkdown=%d字",
            report_id, status,
            len(markdown_content), len(kb_report_markdown), len(summary_markdown)
        )

        if report_id is None:
            logger.warning(
                "[UpstreamClient] ⚠️  reportId 为 None！上游可能无法识别这份报告"
            )

        # ---- Mock 模式 ----
        if self.mock:
            logger.info("[UpstreamClient] [Mock] 回调内容: reportId=%s, status=%s, "
                        "markdownContent=%d字, kbReportMarkdown=%d字, "
                        "knowledgeBasePayload=%d字, summaryMarkdown=%d字, "
                        "agentResponseRaw=%d字, errorMessage=%s",
                        report_id, status,
                        len(markdown_content), len(kb_report_markdown),
                        len(knowledge_base_payload), len(summary_markdown),
                        len(agent_response_raw), error_message or "无")
            logger.info(
                "[UpstreamClient] [Mock] 回调请求体摘要: %s",
                json.dumps(body, ensure_ascii=False)[:300]
            )
            return {"code": 200, "msg": "ok", "data": {"mock": True}}

        # ---- 真实模式 ----
        logger.info(
            "[UpstreamClient] 回调请求体（前300字符）: %s",
            json.dumps(body, ensure_ascii=False)[:300]
        )

        resp = self._request_with_retry(
            "POST",
            "/report/ai-agent/callback/complete",
            json=body,
        )
        resp.raise_for_status()

        result = resp.json()
        logger.info(
            "[UpstreamClient] 回调响应完整内容: %s",
            json.dumps(result, ensure_ascii=False)
        )

        # 检查上游是否真的成功（可能返回 200 但 code 非 200）
        if "code" in result and result["code"] != 200:
            logger.error(
                "[UpstreamClient] ❌ 上游返回业务失败: code=%s, msg=%s",
                result.get("code"), result.get("msg")
            )
        else:
            logger.info("[UpstreamClient] ✅ 回调成功")

        return result

    def callback_factory_summary(
        self,
        report_code: str,
        period_label: str,
        report_date: str,
        status: str,
        markdown_content: str = "",
        title: str = None,
        summary_markdown: str = "",
        kb_report_markdown: str = "",
        knowledge_base_payload: str = "",
        agent_response_raw: str = "",
        date_type: str = "day",
        request_payload: str = None,
        error_message: str = "",
    ) -> dict:
        """
        工厂级汇总报告入库回调

        POST /report/ai-agent/callback/factory-summary

        与工序级报告的区别：
        - 无拉参阶段，无 reportId
        - workshop_id/class_id/procedure_id 等车间维度为空
        - 服务端在 ai_analysis_report 表中新增一条记录

        Mock 模式下：仅打印回调内容摘要，不发送 HTTP 请求

        Args:
            report_code: 报告类型，早会日报：leanMorningDailyReport
            period_label: 业务账期描述，如 2026-03-29
            report_date: 报告锚点日期，yyyy-MM-dd
            status: "0" 成功 / "1" 失败
            markdown_content: 汇总正文 Markdown（成功时必填）
            title: 标题；不传则由服务端生成默认标题
            summary_markdown: 总结类 Markdown
            kb_report_markdown: 含知识库上下文的 Markdown
            knowledge_base_payload: 知识库信息 JSON 字符串
            agent_response_raw: 原始响应/调试信息
            date_type: 如 day、week、month，便于与查询维度对齐
            request_payload: Agent 侧上下文 JSON 字符串
            error_message: status 为 "1" 时原因

        Returns:
            回调响应体，data 字段包含新插入记录的主键 reportId
            Mock 模式下返回模拟成功响应

        Raises:
            Exception: 回调失败
        """
        body = {
            "reportCode": report_code,
            "periodLabel": period_label,
            "reportDate": report_date,
            "status": status,
        }

        # 只在成功时填充报告字段
        if status == "0":
            body["markdownContent"] = markdown_content
            body["summaryMarkdown"] = summary_markdown
            body["kbReportMarkdown"] = kb_report_markdown
            body["knowledgeBasePayload"] = knowledge_base_payload
            body["agentResponseRaw"] = agent_response_raw
            body["dateType"] = date_type
            if request_payload:
                body["requestPayload"] = request_payload

        # 可选字段：title（不传则由服务端自动生成）
        if title:
            body["title"] = title

        if error_message:
            body["errorMessage"] = error_message

        logger.info(
            "[UpstreamClient] 工厂级报告回调: reportDate=%s, reportCode=%s, status=%s, "
            "markdownContent=%d字, summaryMarkdown=%d字, kbReportMarkdown=%d字",
            report_date, report_code, status,
            len(markdown_content), len(summary_markdown), len(kb_report_markdown)
        )

        # ---- Mock 模式 ----
        if self.mock:
            logger.info(
                "[UpstreamClient] [Mock] 工厂级报告回调内容: reportDate=%s, reportCode=%s, status=%s, "
                "title=%s, markdownContent=%d字, summaryMarkdown=%d字, "
                "kbReportMarkdown=%d字, knowledgeBasePayload=%d字, "
                "agentResponseRaw=%d字, dateType=%s, requestPayload=%s, errorMessage=%s",
                report_date, report_code, status,
                title or "(自动生成)",
                len(markdown_content), len(summary_markdown),
                len(kb_report_markdown), len(knowledge_base_payload),
                len(agent_response_raw), date_type,
                "有" if request_payload else "无",
                error_message or "无"
            )
            logger.info(
                "[UpstreamClient] [Mock] 工厂级报告回调请求体摘要: %s",
                json.dumps(body, ensure_ascii=False)[:500]
            )
            return {"code": 200, "msg": "ok", "data": {"reportId": 0, "mock": True}}

        # ---- 真实模式 ----
        logger.info(
            "[UpstreamClient] 工厂级报告回调请求体（前500字符）: %s",
            json.dumps(body, ensure_ascii=False)[:500]
        )

        resp = self._request_with_retry(
            "POST",
            "/report/ai-agent/callback/factory-summary",
            json=body,
        )
        resp.raise_for_status()

        result = resp.json()
        logger.info(
            "[UpstreamClient] 工厂级报告回调响应完整内容: %s",
            json.dumps(result, ensure_ascii=False)
        )

        # 检查上游是否真的成功（可能返回 200 但 code 非 200）
        if "code" in result and result["code"] != 200:
            logger.error(
                "[UpstreamClient] ❌ 工厂级报告回调上游返回业务失败: code=%s, msg=%s",
                result.get("code"), result.get("msg")
            )
        else:
            logger.info(
                "[UpstreamClient] ✅ 工厂级报告回调成功，新记录 reportId: %s",
                result.get("data", {}).get("reportId")
            )

        return result

    def _pull_quality_params(
        self,
        path: str,
        report_date: str,
        mock_name: str,
        report_type_label: str,
        workshop_id: int = None,
    ) -> dict:
        """
        通用质量概览拉参方法（日报/周报/月报共用）

        Args:
            path: 上游接口路径
            report_date: 报告日期/锚点日
            mock_name: Mock 数据文件名（不含 .json）
            report_type_label: 报告类型名称（用于日志）

        Returns:
            {"reportId": int, "payload": dict}
        """
        logger.info(
            "[UpstreamClient] 拉取%s参数: reportDate=%s",
            report_type_label, report_date or "默认"
        )

        # ---- Mock 模式 ----
        if self.mock:
            payload = self._load_mock_payload(mock_name)
            if report_date and "meta" in payload and isinstance(payload["meta"], dict):
                payload["meta"]["period"] = report_date
            logger.info(
                "[UpstreamClient] [Mock] 拉参返回: reportId=1, payload keys=%s",
                list(payload.keys())
            )
            return {"reportId": 1, "payload": payload}

        # ---- 真实模式 ----
        params = {}
        if report_date:
            params["reportDate"] = report_date
        if workshop_id:
            params["workshopId"] = workshop_id

        resp = self._request_with_retry("GET", path, params=params)
        resp.raise_for_status()

        result = resp.json()
        resp_code = result.get("code")
        if resp_code is not None and resp_code != 200:
            error_msg = result.get("msg") or result.get("message") or f"上游返回业务失败 code={resp_code}"
            raise Exception(f"上游拉参失败（code={resp_code}）: {error_msg}")

        data = result.get("data", result)
        report_id = data.get("reportId") or data.get("report_id") or data.get("id")
        payload = data.get("payload", data)

        if report_id is None:
            raise Exception(f"上游未返回 reportId！可用字段: {list(data.keys())}")

        logger.info(
            "[UpstreamClient] 拉参成功: reportId=%s, payload keys=%s",
            report_id, list(payload.keys()) if isinstance(payload, dict) else "N/A"
        )
        return {"reportId": report_id, "payload": payload}

    def pull_quality_daily_params(self, report_date: str = None, workshop_id: int = None) -> dict:
        """
        拉取质量概览日报参数

        GET /report/ai-agent/quality-daily/param?reportDate=xxx&workshopId=xxx
        """
        return self._pull_quality_params(
            path="/report/ai-agent/quality-daily/param",
            report_date=report_date,
            mock_name="mock_quality_daily",
            report_type_label="质量概览日报",
            workshop_id=workshop_id,
        )

    def pull_quality_weekly_params(self, report_date: str = None, workshop_id: int = None) -> dict:
        """
        拉取质量概览周报参数

        GET /report/ai-agent/quality-weekly/param?reportDate=xxx&workshopId=xxx
        """
        return self._pull_quality_params(
            path="/report/ai-agent/quality-weekly/param",
            report_date=report_date,
            mock_name="mock_quality_weekly",
            report_type_label="质量概览周报",
            workshop_id=workshop_id,
        )

    def pull_quality_monthly_params(self, report_date: str = None, workshop_id: int = None) -> dict:
        """
        拉取质量概览月报参数

        GET /report/ai-agent/quality-monthly/param?reportDate=xxx&workshopId=xxx
        """
        return self._pull_quality_params(
            path="/report/ai-agent/quality-monthly/param",
            report_date=report_date,
            mock_name="mock_quality_monthly",
            report_type_label="质量概览月报",
            workshop_id=workshop_id,
        )

    def pull_device_efficiency_params(
        self,
        report_date: str = None,
        workshop_id: int = None,
        period_type: str = "day",
    ) -> dict:
        """
        拉取设备效率报告参数

        GET /report/ai-agent/device-efficiency/param?reportDate=xxx&workshopId=xxx&periodType=xxx

        Args:
            report_date: 报告日期（可选，默认昨日）
            workshop_id: 车间 ID（可选，不传则工厂级）
            period_type: 周期类型：day/week/month，默认 day

        Returns:
            {"reportId": int, "payload": dict}
        """
        period_label_map = {"day": "日报", "week": "周报", "month": "月报"}
        report_type_label = f"设备效率{period_label_map.get(period_type, '日报')}"
        logger.info(
            "[UpstreamClient] 拉取%s参数: reportDate=%s, workshopId=%s, periodType=%s",
            report_type_label, report_date or "默认", workshop_id or "工厂级", period_type
        )

        # ---- Mock 模式 ----
        if self.mock:
            payload = self._load_mock_payload("mock_device_efficiency")
            if "meta" not in payload or not isinstance(payload["meta"], dict):
                payload["meta"] = {}
            if report_date:
                payload["meta"]["period"] = report_date
            if workshop_id:
                payload["meta"]["workshopId"] = workshop_id
            payload["meta"]["periodType"] = period_type
            logger.info(
                "[UpstreamClient] [Mock] 拉参返回: reportId=1, payload keys=%s",
                list(payload.keys())
            )
            return {"reportId": 1, "payload": payload}

        # ---- 真实模式 ----
        params = {"periodType": period_type}
        if report_date:
            params["reportDate"] = report_date
        if workshop_id:
            params["workshopId"] = workshop_id

        path = "/report/ai-agent/device-efficiency/param"
        resp = self._request_with_retry("GET", path, params=params)
        resp.raise_for_status()

        result = resp.json()
        resp_code = result.get("code")
        if resp_code is not None and resp_code != 200:
            error_msg = result.get("msg") or result.get("message") or f"上游返回业务失败 code={resp_code}"
            raise Exception(f"上游拉参失败（code={resp_code}）: {error_msg}")

        data = result.get("data", result)
        report_id = data.get("reportId") or data.get("report_id") or data.get("id")
        payload = data.get("payload", data)

        if report_id is None:
            raise Exception(f"上游未返回 reportId！可用字段: {list(data.keys())}")

        logger.info(
            "[UpstreamClient] 拉参成功: reportId=%s, payload keys=%s",
            report_id, list(payload.keys()) if isinstance(payload, dict) else "N/A"
        )
        return {"reportId": report_id, "payload": payload}

    def pull_device_maintenance_params(
        self,
        report_date: str = None,
        period_type: str = "week",
    ) -> dict:
        """
        拉取设备运维报告参数

        GET /report/ai-agent/device-maintenance/param?reportDate=xxx&periodType=xxx

        Args:
            report_date: 报告日期（可选，默认今日）
            period_type: 周期类型：week/month，默认 week

        Returns:
            {"reportId": int, "payload": dict}
        """
        period_label_map = {"week": "周报", "month": "月报"}
        report_type_label = f"设备运维{period_label_map.get(period_type, '周报')}"
        logger.info(
            "[UpstreamClient] 拉取%s参数: reportDate=%s, periodType=%s",
            report_type_label, report_date or "默认", period_type
        )

        # ---- Mock 模式 ----
        if self.mock:
            payload = self._load_mock_payload("mock_device_maintenance")
            if "meta" not in payload or not isinstance(payload["meta"], dict):
                payload["meta"] = {}
            if report_date:
                payload["meta"]["period"] = report_date
            payload["meta"]["periodType"] = period_type
            logger.info(
                "[UpstreamClient] [Mock] 拉参返回: reportId=1, payload keys=%s",
                list(payload.keys())
            )
            return {"reportId": 1, "payload": payload}

        # ---- 真实模式 ----
        params = {"periodType": period_type}
        if report_date:
            params["reportDate"] = report_date

        path = "/report/ai-agent/device-maintenance/param"
        resp = self._request_with_retry("GET", path, params=params)
        resp.raise_for_status()

        result = resp.json()
        resp_code = result.get("code")
        if resp_code is not None and resp_code != 200:
            error_msg = result.get("msg") or result.get("message") or f"上游返回业务失败 code={resp_code}"
            raise Exception(f"上游拉参失败（code={resp_code}）: {error_msg}")

        data = result.get("data", result)
        report_id = data.get("reportId") or data.get("report_id") or data.get("id")
        payload = data.get("payload", data)

        if report_id is None:
            raise Exception(f"上游未返回 reportId！可用字段: {list(data.keys())}")

        logger.info(
            "[UpstreamClient] 拉参成功: reportId=%s, payload keys=%s",
            report_id, list(payload.keys()) if isinstance(payload, dict) else "N/A"
        )
        return {"reportId": report_id, "payload": payload}

    def get_workshop_tree(self) -> list:
        """
        获取车间产线树

        GET /system/workshop/tree

        Returns:
            车间列表，格式:
            [
                {"id": 1, "name": "极板车间"},
                {"id": 2, "name": "装配车间"},
                ...
            ]

        Raises:
            Exception: 接口调用失败
        """
        logger.info("[UpstreamClient] 获取车间产线树")

        # ---- Mock 模式 ----
        if self.mock:
            logger.info("[UpstreamClient] [Mock] 返回模拟车间列表")
            return [
                {"id": 1, "name": "极板车间"},
                {"id": 2, "name": "装配车间"},
                {"id": 3, "name": "化成车间"},
            ]

        # ---- 真实模式 ----
        resp = self._request_with_retry(
            "GET",
            "/system/workshop/tree",
        )
        resp.raise_for_status()

        result = resp.json()

        # 检查业务状态码
        if "code" in result and result["code"] != 200:
            error_msg = result.get("msg") or f"获取车间树失败 code={result['code']}"
            logger.error("[UpstreamClient] ❌ %s", error_msg)
            raise Exception(error_msg)

        # 解析数据
        data = result.get("data", [])

        # 提取第一层节点（车间），兼容列表或树结构
        workshop_list = []
        if isinstance(data, list):
            for node in data:
                if isinstance(node, dict):
                    workshop_id = node.get("id")
                    workshop_name = node.get("label") or node.get("name")
                    if workshop_id is not None and workshop_name:
                        workshop_list.append({
                            "id": workshop_id,
                            "name": workshop_name,
                        })

        logger.info(
            "[UpstreamClient] ✅ 获取车间树成功，共 %d 个车间: %s",
            len(workshop_list),
            ", ".join([f"{w['name']}(ID:{w['id']})" for w in workshop_list])
        )

        return workshop_list

    def get_procedure_list(self, workshop_id: int) -> list:
        """
        按车间查询工序列表

        GET /mes/procedure/list?workshopId={workshop_id}

        Args:
            workshop_id: 车间 ID

        Returns:
            工序列表，格式:
            [
                {"id": 1, "name": "和膏工序"},
                {"id": 2, "name": "涂板工序"},
                ...
            ]

        Raises:
            Exception: 接口调用失败
        """
        logger.info(
            "[UpstreamClient] 获取车间工序列表: workshopId=%s",
            workshop_id
        )

        # ---- Mock 模式 ----
        if self.mock:
            logger.info("[UpstreamClient] [Mock] 返回模拟工序列表")
            mock_procedures = {
                1: [
                    {"id": 1, "name": "和膏工序"},
                    {"id": 2, "name": "涂板工序"},
                    {"id": 3, "name": "固化干燥"},
                ],
                2: [
                    {"id": 4, "name": "装配工序"},
                    {"id": 5, "name": "包片工序"},
                ],
                3: [
                    {"id": 6, "name": "化成工序"},
                    {"id": 7, "name": "充电工序"},
                ],
            }
            return mock_procedures.get(workshop_id, [])

        # ---- 真实模式 ----
        resp = self._request_with_retry(
            "GET",
            "/mes/procedure/list",
            params={"workshopId": workshop_id},
        )
        resp.raise_for_status()

        result = resp.json()

        # 检查业务状态码
        if "code" in result and result["code"] != 200:
            error_msg = result.get("msg") or f"获取工序列表失败 code={result['code']}"
            logger.error("[UpstreamClient] ❌ %s", error_msg)
            raise Exception(error_msg)

        # 解析数据
        data = result.get("data", [])
        procedure_list = []

        if isinstance(data, list):
            for node in data:
                if isinstance(node, dict):
                    proc_id = node.get("id")
                    proc_name = node.get("name") or node.get("label")
                    if proc_id is not None and proc_name:
                        procedure_list.append({
                            "id": proc_id,
                            "name": proc_name,
                        })

        logger.info(
            "[UpstreamClient] ✅ 获取工序列表成功，车间ID=%d, 共 %d 个工序: %s",
            workshop_id,
            len(procedure_list),
            ", ".join([f"{p['name']}(ID:{p['id']})" for p in procedure_list])
        )

        return procedure_list


# 单例
_upstream_client = None


def get_upstream_client() -> UpstreamClient:
    """获取上游客户端单例"""
    global _upstream_client
    if _upstream_client is None:
        _upstream_client = UpstreamClient()
    return _upstream_client
