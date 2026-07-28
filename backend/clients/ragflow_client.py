# cython: annotation_typing=False, infer_types=False, language_level=3
"""
RAGFlow 客户端
用于调用 RAGFlow 的对话 API 和检索 API（使用 HTTP 协议直接请求）
"""
import os
import json
import requests


class RAGFlowClient:
    """RAGFlow 客户端"""

    def __init__(
        self,
        conversation_id: str = None,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        dataset_id: str = None,
        timeout: float = 600.0,
        temperature: float = 0.7
    ):
        """
        初始化 RAGFlow 客户端

        Args:
            conversation_id: RAGFlow 对话ID（已在RAGFlow中配置知识库）
            base_url: RAGFlow API 基础URL
            api_key: RAGFlow API 密钥
            model: 模型名称
            dataset_id: RAGFlow 知识库ID（用于检索接口）
            timeout: 超时时间（秒）
            temperature: 温度参数
        """
        # 从环境变量读取配置
        self.base_url = base_url or os.getenv("RAGFLOW_BASE_URL")
        self.api_key = api_key or os.getenv("RAGFLOW_API_KEY")
        self.conversation_id = conversation_id or os.getenv("RAGFLOW_CONVERSATION_ID")
        self.dataset_id = dataset_id or os.getenv("RAGFLOW_DATASET_ID")
        self.model = model or os.getenv("RAGFLOW_MODEL", "qwen-plus")
        self.timeout = timeout
        self.temperature = temperature

        # 校验必需配置
        if not self.base_url:
            raise ValueError("请设置 RAGFLOW_BASE_URL 环境变量")

        # 对话接口需要 conversation_id，检索接口只需要 dataset_id
        if self.conversation_id:
            self.api_endpoint = f"{self.base_url.rstrip('/')}/api/v1/chats_openai/{self.conversation_id}/chat/completions"
        else:
            self.api_endpoint = None

        print(f"[RAGFlow] 已初始化")
        if self.conversation_id:
            print(f"[RAGFlow]   对话ID: {self.conversation_id}")
            print(f"[RAGFlow]   API地址: {self.api_endpoint}")
            print(f"[RAGFlow]   模型: {self.model}")
        if self.dataset_id:
            print(f"[RAGFlow]   知识库ID: {self.dataset_id}")

    def stream(self, prompt: str, context: str = None):
        """
        流式调用 RAGFlow

        Args:
            prompt: 提示词
            context: 上下文（第一份报告内容）

        Yields:
            content 为内容块
        """
        # 如果有上下文，添加到系统消息
        if context:
            prompt = """【基础质量周报】
{}

【分析任务】
{}""".format(context, prompt)

        # 构建请求 URL
        url = self.api_endpoint

        # 构建请求头
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        # 构建请求体
        body = {
            'model': self.model,
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'stream': True,
            'temperature': self.temperature
        }

        # 发送流式请求
        response = requests.post(
            url,
            headers=headers,
            json=body,
            stream=True,
            timeout=self.timeout
        )

        # 检查响应状态
        response.raise_for_status()

        # 正确解析 SSE 格式：累积行，遇到空行后解析为一个事件
        buffer = ""

        for line in response.iter_lines(decode_unicode=True):
            if line.strip() == "":
                # 空行表示一个事件的结束
                if buffer.strip():
                    # 解析缓冲区中的事件
                    if buffer.startswith('data: '):
                        data_str = buffer[6:]  # 移除 "data: " 前缀

                        # 跳过 "[DONE]" 标记
                        if data_str.strip() == '[DONE]':
                            break

                        try:
                            chunk_data = json.loads(data_str)

                            # 检查 choices[0].delta
                            delta = chunk_data.get('choices', [{}])[0].get('delta', {})

                            # 检查 content
                            content = delta.get('content')
                            if content:
                                yield content

                        except json.JSONDecodeError:
                            # 跳过无法解析的行
                            pass

                buffer = ""  # 清空缓冲区
            else:
                # 累积行
                if buffer:
                    buffer += "\n"
                buffer += line

    def download_document(
        self,
        dataset_id: str,
        document_id: str
    ) -> requests.Response:
        """
        下载 RAGFlow 文档文件

        调用 RAGFlow 下载 API:
        GET /api/v1/datasets/{dataset_id}/documents/{document_id}

        Args:
            dataset_id: 知识库ID（数据集ID）
            document_id: 文档ID

        Returns:
            requests.Response 对象，包含文件流和响应头
            - 可通过 response.content 获取文件二进制内容
            - 可通过 response.headers.get('Content-Type') 获取文件类型
            - 可通过 response.headers.get('Content-Disposition') 获取文件名

        Raises:
            ValueError: 缺少必要参数
            requests.exceptions.RequestException: 请求失败
        """
        if not dataset_id:
            raise ValueError("请传入 dataset_id 参数")
        if not document_id:
            raise ValueError("请传入 document_id 参数")

        url = f"{self.base_url.rstrip('/')}/api/v1/datasets/{dataset_id}/documents/{document_id}"
        headers = {
            'Authorization': f'Bearer {self.api_key}'
        }

        print(f"[RAGFlow] 下载文档: {url}")
        print(f"[RAGFlow]   dataset_id: {dataset_id}")
        print(f"[RAGFlow]   document_id: {document_id}")

        response = requests.get(
            url,
            headers=headers,
            timeout=self.timeout,
            stream=True
        )
        response.raise_for_status()

        print(f"[RAGFlow] 文档下载成功，Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        return response

    def retrieve(
        self,
        question: str,
        dataset_id: str = None,
        top_k: int = 5,
        page_size: int = 10,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
        keyword: bool = True,
        highlight: bool = False,
        job_logger=None
    ) -> list:
        """
        调用 RAGFlow 检索接口，获取与问题相关的知识块

        RAGFlow 检索模式：
        - 混合检索（Hybrid Search）：同时使用向量检索和关键词检索
        - vector_similarity_weight: 控制向量检索权重（0-1），默认0.3
          - 值越接近1，越偏向语义检索
          - 值越接近0，越偏向关键词检索
        - keyword: 是否启用关键词搜索

        RAGFlow 检索 API: POST /api/v1/retrieval
        请求体格式: {"question": "...", "dataset_ids": ["..."], "top_k": 5}

        Args:
            question: 检索问题/关键词
            dataset_id: 知识库ID，不传则使用环境变量中的默认值
            top_k: 涉及向量计算的块数
            page_size: 每页返回的结果数量
            similarity_threshold: 相似度阈值，低于此值的结果将被过滤（默认0.2）
            vector_similarity_weight: 向量检索权重（0-1），默认0.3
            keyword: 是否启用关键词搜索，默认True
            highlight: 是否启用高亮，默认False

        Returns:
            检索结果列表，每个元素包含：
            [
                {
                    "content": "检索到的文本块内容",
                    "document_name": "来源文档名称",
                    "chunk_id": "块ID",
                    "similarity": 0.85,
                    "term_similarity": 0.7,  # 关键词相似度
                    "vector_similarity": 0.9,  # 向量相似度
                    "position": "页码或位置信息",
                    "document_id": "文档ID（用于下载API）",
                    "dataset_id": "知识库ID（用于下载API）",
                    "positions": [[页码, x, y, 宽, 高]],  # 详细位置坐标，用于文档定位和高亮
                    "docnm": "文档原始名称",
                    "highlight": "高亮后的内容（如果启用highlight）"
                }
            ]
        """
        # 使用传入的 dataset_id 或从环境变量获取
        target_dataset_id = dataset_id or self.dataset_id
        if not target_dataset_id:
            raise ValueError("请设置 RAGFLOW_DATASET_ID 环境变量或传入 dataset_id 参数")

        # 构建检索 API 地址（注意：RAGFlow 的检索接口是 /api/v1/retrieval）
        url = f"{self.base_url.rstrip('/')}/api/v1/retrieval"

        # 构建请求头
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        # 构建请求体（参考 report-agent 的实现）
        body = {
            'question': question,
            'dataset_ids': [target_dataset_id],
            'page_size': page_size,
            'similarity_threshold': similarity_threshold
        }

        # 可选参数
        if top_k:
            body['top_k'] = top_k
        if vector_similarity_weight is not None:
            body['vector_similarity_weight'] = vector_similarity_weight
        if keyword is not None:
            body['keyword'] = keyword
        if highlight:
            body['highlight'] = highlight

        # 检查 question 是否为空
        if not question:
            if job_logger:
                job_logger.warning("[RAGFlow] 检索问题为空，跳过检索")
            else:
                print("[RAGFlow] 检索问题为空，跳过检索")
            return []

        if job_logger:
            job_logger.info("[RAGFlow] 开始检索，问题长度: %d 字符", len(question))
            job_logger.info("[RAGFlow] 检索参数: page_size=%d, top_k=%d, dataset_id=%s", page_size, top_k, target_dataset_id)
            job_logger.info("[RAGFlow] 检索模式: 混合检索 (vector_weight=%s, keyword=%s)", vector_similarity_weight, keyword)
            job_logger.info("[RAGFlow] 检索问题: %s", question[:100] + "...")
        else:
            print(f"[RAGFlow] 开始检索，问题长度: {len(question)} 字符")
            print(f"[RAGFlow] 检索参数: page_size={page_size}, top_k={top_k}, dataset_id={target_dataset_id}")
            print(f"[RAGFlow] 检索模式: 混合检索 (vector_weight={vector_similarity_weight}, keyword={keyword})")
            print(f"[RAGFlow] 检索问题: {question[:100]}...")

        try:
            response = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=self.timeout
            )
            response.raise_for_status()

            result = response.json()

            # 打印原始 API 返回结果（用于调试）
            if job_logger:
                job_logger.info("")
                job_logger.info("=" * 60)
                job_logger.info("[RAGFlow] API 原始返回结果:")
                job_logger.info("=" * 60)
                job_logger.info("[RAGFlow] HTTP 状态码: %s", response.status_code)
                job_logger.info("[RAGFlow] 返回 code: %s", result.get('code'))
                job_logger.info("[RAGFlow] 返回 message: %s", result.get('message', 'N/A'))
            else:
                print(f"\n{'='*60}")
                print(f"[RAGFlow] API 原始返回结果:")
                print(f"{'='*60}")
                print(f"[RAGFlow] HTTP 状态码: {response.status_code}")
                print(f"[RAGFlow] 返回 code: {result.get('code')}")
                print(f"[RAGFlow] 返回 message: {result.get('message', 'N/A')}")

            # 打印 data 部分的详细信息
            data = result.get('data', {})
            if data:
                if job_logger:
                    job_logger.info("[RAGFlow] data.total: %s", data.get('total', 'N/A'))
                    chunk_list = data.get('chunks', [])
                    job_logger.info("[RAGFlow] data.chunks 数量: %d", len(chunk_list))
                    for i, item in enumerate(chunk_list[:3]):  # 最多打印3个
                        job_logger.info("")
                        job_logger.info("[RAGFlow] Chunk %d:", i+1)
                        job_logger.info("  - id: %s", item.get('id', 'N/A'))
                        job_logger.info("  - document_id: %s", item.get('document_id', 'N/A'))
                        job_logger.info("  - dataset_id: %s", item.get('dataset_id', 'N/A'))
                        job_logger.info("  - document_keyword: %s", item.get('document_keyword', 'N/A'))
                        job_logger.info("  - document_name: %s", item.get('document_name', 'N/A'))
                        job_logger.info("  - similarity: %s", item.get('similarity', 'N/A'))
                        job_logger.info("  - term_similarity: %s", item.get('term_similarity', 'N/A'))
                        job_logger.info("  - vector_similarity: %s", item.get('vector_similarity', 'N/A'))
                        job_logger.info("  - positions: %s", item.get('positions', 'N/A'))
                        content = item.get('content', '')
                        job_logger.info("  - content (前100字符): %s...", content[:100])
                else:
                    print(f"[RAGFlow] data.total: {data.get('total', 'N/A')}")
                    chunk_list = data.get('chunks', [])
                    print(f"[RAGFlow] data.chunks 数量: {len(chunk_list)}")
                    for i, item in enumerate(chunk_list[:3]):  # 最多打印3个
                        print(f"\n[RAGFlow] Chunk {i+1}:")
                        print(f"  - id: {item.get('id', 'N/A')}")
                        print(f"  - document_id: {item.get('document_id', 'N/A')}")
                        print(f"  - dataset_id: {item.get('dataset_id', 'N/A')}")
                        print(f"  - document_keyword: {item.get('document_keyword', 'N/A')}")
                        print(f"  - document_name: {item.get('document_name', 'N/A')}")
                        print(f"  - similarity: {item.get('similarity', 'N/A')}")
                        print(f"  - term_similarity: {item.get('term_similarity', 'N/A')}")
                        print(f"  - vector_similarity: {item.get('vector_similarity', 'N/A')}")
                        print(f"  - positions: {item.get('positions', 'N/A')}")
                        content = item.get('content', '')
                        print(f"  - content (前100字符): {content[:100]}...")
            else:
                if job_logger:
                    job_logger.info("[RAGFlow] data 为空")
                    job_logger.info("[RAGFlow] 完整返回: %s", json.dumps(result, ensure_ascii=False, indent=2))
                else:
                    print(f"[RAGFlow] data 为空")
                    print(f"[RAGFlow] 完整返回: {json.dumps(result, ensure_ascii=False, indent=2)}")

            if job_logger:
                job_logger.info("%s\n", "=" * 60)
            else:
                print(f"{'='*60}\n")

            # 解析检索结果
            chunks = []
            if result.get('code') == 0 and result.get('data'):
                # RAGFlow 返回格式: {"code": 0, "data": {"chunks": [...], "total": N}}
                chunk_list = result['data'].get('chunks', [])
                for item in chunk_list:
                    similarity = item.get('similarity', 0.0)
                    # 过滤低相似度结果
                    if similarity >= similarity_threshold:
                        chunk = {
                            "content": item.get('content', ''),
                            "document_name": item.get('document_keyword', item.get('document_name', '')),
                            "chunk_id": item.get('id', item.get('chunk_id', '')),
                            "similarity": similarity,
                            "term_similarity": item.get('term_similarity', 0.0),
                            "vector_similarity": item.get('vector_similarity', 0.0),
                            "position": item.get('positions', ''),
                            # 以下字段用于文档下载和定位
                            "document_id": item.get('document_id', ''),
                            "dataset_id": item.get('dataset_id', ''),
                            "positions": item.get('positions', []),
                            "docnm": item.get('docnm', item.get('document_keyword', '')),
                            "highlight": item.get('highlight', '')
                        }
                        chunks.append(chunk)

            if job_logger:
                job_logger.info("[RAGFlow] 检索完成，返回 %d 个知识块（相似度阈值: %s）", len(chunks), similarity_threshold)
            else:
                print(f"[RAGFlow] 检索完成，返回 {len(chunks)} 个知识块（相似度阈值: {similarity_threshold}）")
            return chunks

        except requests.exceptions.RequestException as e:
            if job_logger:
                job_logger.error("[RAGFlow] 检索失败: %s", e, exc_info=True)
            else:
                print(f"[RAGFlow] 检索失败: {e}")
                import traceback
                traceback.print_exc()
            # 检索失败时返回空列表，不中断报告生成流程
            return []


# 单例
_ragflow_client = None


def get_ragflow_client(
    conversation_id: str = None,
    dataset_id: str = None
) -> RAGFlowClient:
    """
    获取 RAGFlow 客户端实例（单例）

    Args:
        conversation_id: RAGFlow 对话ID，不传则使用环境变量
        dataset_id: RAGFlow 知识库ID，不传则使用环境变量

    Returns:
        RAGFlowClient 实例
    """
    global _ragflow_client
    if _ragflow_client is None:
        _ragflow_client = RAGFlowClient(
            conversation_id=conversation_id,
            dataset_id=dataset_id
        )
    return _ragflow_client
