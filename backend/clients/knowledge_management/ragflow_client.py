# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库管理专用 RAGFlow 客户端"""
import logging
from pathlib import Path

import requests

from backend.core.knowledge_management.config import settings
from backend.core.knowledge_management.exceptions import RAGFlowError

logger = logging.getLogger(__name__)


class KnowledgeRAGFlowClient:
    """知识库管理模块专用 RAGFlow 客户端，提供数据集和文档管理功能。"""

    def __init__(self):
        self.base_url = settings.ragflow_api_url.rstrip("/")
        self.api_key = settings.ragflow_api_key
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
        })

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """统一请求方法，检查 HTTP 状态码和 JSON 响应中的 code 字段。

        Args:
            method: HTTP 方法（GET/POST/PUT/DELETE）。
            path: API 路径（相对于 /api/v1）。
            **kwargs: 传递给 requests 的额外参数。

        Returns:
            解析后的 JSON 响应体。

        Raises:
            RAGFlowError: 当 HTTP 请求失败或响应 code 非 0 时。
        """
        url = f"{self.base_url}/api/v1{path}"
        try:
            resp = self._session.request(method, url, timeout=30, **kwargs)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise RAGFlowError(f"RAGFlow 请求失败: {method} {path} — {e}") from e

        data = resp.json()
        code = data.get("code", 0) if data.get("code") is not None else 0
        if code != 0:
            msg = data.get("message", "未知错误")
            raise RAGFlowError(f"RAGFlow API 错误 (code={code}): {msg}")
        return data

    # ------------------------------------------------------------------ #
    #  数据集（Dataset）管理
    # ------------------------------------------------------------------ #

    def list_datasets(
        self,
        page: int = 1,
        page_size: int = 30,
        orderby: str = "create_time",
        desc: bool = True,
        name: str | None = None,
        dataset_id: str | None = None,
        include_parsing_status: bool = False,
    ) -> dict:
        """列出 RAGFlow 数据集。

        Args:
            page: 页码（从 1 开始）。
            page_size: 每页数量。
            orderby: 排序字段（create_time/update_time）。
            desc: 是否降序排列。
            name: 按名称筛选。
            dataset_id: 按 ID 筛选。
            include_parsing_status: 是否包含文档解析状态统计。

        Returns:
            包含数据集列表和总数的字典。
        """
        params = {
            "page": page,
            "page_size": page_size,
            "orderby": orderby,
            "desc": desc,
        }
        if name:
            params["name"] = name
        if dataset_id:
            params["id"] = dataset_id
        if include_parsing_status:
            params["include_parsing_status"] = "true"

        data = self._request("GET", "/datasets", params=params)
        return {
            "datasets": data.get("data", []),
            "total": data.get("total_datasets", 0),
        }

    def find_dataset_by_name(self, name: str) -> str | None:
        """按名称查找 RAGFlow 数据集，返回已存在的 dataset_id 或 None。

        用于：避免重复创建同名 dataset（开发/测试环境共用 RAGFlow 时尤其重要）。

        Args:
            name: 数据集名称（精确匹配）。

        Returns:
            已存在则返回 dataset_id，否则返回 None。
        """
        try:
            result = self.list_datasets(name=name, page=1, page_size=10)
            datasets = result.get("datasets", [])
            for ds in datasets:
                if ds.get("name") == name:
                    return ds.get("id")
        except RAGFlowError:
            pass
        return None

    def get_dataset(self, dataset_id: str) -> dict:
        """获取单个数据集详情。

        Args:
            dataset_id: 数据集 ID。

        Returns:
            数据集信息字典。
        """
        data = self.list_datasets(dataset_id=dataset_id)
        datasets = data.get("datasets", [])
        if not datasets:
            raise RAGFlowError(f"数据集不存在: {dataset_id}")
        return datasets[0]

    def create_dataset(
        self,
        name: str,
        description: str = "",
        chunk_method: str = "naive",
        parser_config: dict | None = None,
        embedding_model: str | None = None,
    ) -> str:
        """创建 RAGFlow 数据集。

        如果 RAGFlow 中已存在同名 dataset（按名称精确匹配），直接复用其 ID，
        避免开发/测试环境共用 RAGFlow 时重复创建。

        Args:
            name: 数据集名称。
            description: 数据集描述。
            chunk_method: 分块方法（naive/qa/book/laws/manual/table/picture/one/email 等）。
            parser_config: 解析器配置。
            embedding_model: 嵌入模型名称（格式：model_name@model_factory）。

        Returns:
            新建（或复用）数据集的 ID。
        """
        if embedding_model is None:
            embedding_model = settings.ragflow_embedding_model

        # 先按名称查找，避免重复创建
        existing_id = self.find_dataset_by_name(name)
        if existing_id:
            return existing_id

        # 先不传 embedding_model 创建，成功后再更新模型
        # （RAGFlow API 创建时传 embedding_model 可能报错，但更新时可用）
        payload = {
            "name": name,
            "description": description,
            "chunk_method": chunk_method,
        }
        if parser_config is not None:
            payload["parser_config"] = parser_config

        data = self._request("POST", "/datasets", json=payload)
        dataset_id = data["data"]["id"]

        # 创建成功后更新 embedding_model
        try:
            self.update_dataset(dataset_id, embedding_model=embedding_model)
        except Exception as e:
            # 更新失败不影响创建，记录警告
            import logging
            logging.getLogger(__name__).warning(
                "Dataset %s 创建成功但更新 embedding_model 失败: %s", dataset_id, e
            )

        return dataset_id

    def update_dataset(
        self,
        dataset_id: str,
        name: str | None = None,
        description: str | None = None,
        chunk_method: str | None = None,
        parser_config: dict | None = None,
        embedding_model: str | None = None,
        permission: str | None = None,
        pagerank: int | None = None,
    ) -> bool:
        """更新 RAGFlow 数据集。

        Args:
            dataset_id: 数据集 ID。
            name: 数据集名称。
            description: 数据集描述。
            chunk_method: 分块方法。
            parser_config: 解析器配置。
            embedding_model: 嵌入模型名称。
            permission: 访问权限（me/team）。
            pagerank: PageRank 值（0-100）。

        Returns:
            是否更新成功。
        """
        payload = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if chunk_method is not None:
            payload["chunk_method"] = chunk_method
        if parser_config is not None:
            payload["parser_config"] = parser_config
        if embedding_model is not None:
            payload["embedding_model"] = embedding_model
        if permission is not None:
            payload["permission"] = permission
        if pagerank is not None:
            payload["pagerank"] = pagerank

        self._request("PUT", f"/datasets/{dataset_id}", json=payload)
        return True

    def delete_dataset(self, dataset_id: str) -> bool:
        """删除 RAGFlow 数据集。

        Args:
            dataset_id: 数据集 ID。

        Returns:
            是否删除成功。
        """
        self._request("DELETE", "/datasets", json={"ids": [dataset_id]})
        return True

    def delete_datasets(self, dataset_ids: list[str]) -> bool:
        """批量删除 RAGFlow 数据集。

        Args:
            dataset_ids: 数据集 ID 列表。

        Returns:
            是否删除成功。
        """
        self._request("DELETE", "/datasets", json={"ids": dataset_ids})
        return True

    # ------------------------------------------------------------------ #
    #  文档（Document）管理
    # ------------------------------------------------------------------ #

    def list_documents(self, dataset_id: str, page: int = 1, page_size: int = 30) -> dict:
        """列出数据集中的文档。

        Args:
            dataset_id: 数据集 ID。
            page: 页码（从 1 开始）。
            page_size: 每页数量。

        Returns:
            包含文档列表和分页信息的字典。
        """
        params = {"page": page, "page_size": page_size}
        data = self._request("GET", f"/datasets/{dataset_id}/documents", params=params)
        return data.get("data", {})

    def upload_document(self, dataset_id: str, file_path: str, file_name: str | None = None) -> str:
        """上传文档到 RAGFlow 数据集。

        Args:
            dataset_id: 数据集 ID。
            file_path: 本地文件路径。
            file_name: 文件名（默认使用 file_path 的文件名）。

        Returns:
            RAGFlow 文档 ID。
        """
        path = Path(file_path)
        if file_name is None:
            file_name = path.name

        with open(file_path, "rb") as f:
            files = {"file": (file_name, f)}
            data = self._request("POST", f"/datasets/{dataset_id}/documents", files=files)

        doc_list = data.get("data", [])
        if not doc_list:
            raise RAGFlowError("上传文档成功但未返回文档信息")
        return doc_list[0]["id"]

    def get_document(self, dataset_id: str, doc_id: str) -> bytes:
        """下载文档。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。

        Returns:
            文档内容的字节流。
        """
        url = f"{self.base_url}/api/v1/datasets/{dataset_id}/documents/{doc_id}"
        resp = self._session.get(url)
        resp.raise_for_status()
        return resp.content

    def update_document(
        self,
        dataset_id: str,
        doc_id: str,
        name: str | None = None,
        chunk_method: str | None = None,
        parser_config: dict | None = None,
        meta_fields: dict | None = None,
        enabled: bool | None = None,
    ) -> bool:
        """更新文档属性。

        RAGFlow PUT /datasets/{id}/documents/{doc_id} 新版本对单次请求的多字段组合
        可能返回 code=102 "Not supported yet!"（典型组合：name + chunk_method +
        meta_fields）。这里采用"逐字段调用 + 单点失败容忍"：每次只更新一个字段，
        单个字段失败不影响其他字段更新。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。
            name: 文档名称。
            chunk_method: 分块方法。
            parser_config: 解析器配置。
            meta_fields: 元数据字段。
            enabled: 是否启用。

        Returns:
            是否所有字段都更新成功（任意字段失败返回 False，但不抛异常）。
        """
        all_ok = True

        # 1. name
        if name is not None:
            try:
                self._request(
                    "PUT",
                    f"/datasets/{dataset_id}/documents/{doc_id}",
                    json={"name": name},
                )
            except RAGFlowError as e:
                logger.warning(f"[RAGFlow] 更新 name 失败: {e}")
                all_ok = False

        # 2. chunk_method（部分 RAGFlow 版本不支持运行时改 chunk_method，跳过不算错）
        if chunk_method is not None:
            try:
                self._request(
                    "PUT",
                    f"/datasets/{dataset_id}/documents/{doc_id}",
                    json={"chunk_method": chunk_method},
                )
            except RAGFlowError as e:
                logger.warning(f"[RAGFlow] 更新 chunk_method 失败（已跳过）: {e}")
                # 不标记失败 — chunk_method 通常在上传时已确定，运行时改是 nice-to-have

        # 3. parser_config
        if parser_config is not None:
            try:
                self._request(
                    "PUT",
                    f"/datasets/{dataset_id}/documents/{doc_id}",
                    json={"parser_config": parser_config},
                )
            except RAGFlowError as e:
                logger.warning(f"[RAGFlow] 更新 parser_config 失败: {e}")
                all_ok = False

        # 4. meta_fields（最可能触发 102 的字段；meta_fields 含中文时新版本 RAGFlow
        #    可能拒绝。先尝试，如果失败就降级：用单字段逐个设置，最小化冲突）
        if meta_fields is not None:
            try:
                self._request(
                    "PUT",
                    f"/datasets/{dataset_id}/documents/{doc_id}",
                    json={"meta_fields": meta_fields},
                )
            except RAGFlowError as e:
                logger.warning(
                    f"[RAGFlow] 更新 meta_fields 整体失败，尝试单字段更新: {e}"
                )
                # 降级：逐个字段设置
                meta_ok = True
                for k, v in meta_fields.items():
                    try:
                        existing_resp = self._request(
                            "GET",
                            f"/datasets/{dataset_id}/documents/{doc_id}",
                        )
                        existing_meta = (
                            existing_resp.get("data", {}).get("meta_fields", {})
                            or {}
                        )
                        existing_meta[k] = v
                        self._request(
                            "PUT",
                            f"/datasets/{dataset_id}/documents/{doc_id}",
                            json={"meta_fields": existing_meta},
                        )
                    except RAGFlowError as e2:
                        logger.warning(
                            f"[RAGFlow] meta_fields['{k}'] 更新失败: {e2}"
                        )
                        meta_ok = False
                if not meta_ok:
                    all_ok = False

        # 5. enabled
        if enabled is not None:
            try:
                self._request(
                    "PUT",
                    f"/datasets/{dataset_id}/documents/{doc_id}",
                    json={"enabled": 1 if enabled else 0},
                )
            except RAGFlowError as e:
                logger.warning(f"[RAGFlow] 更新 enabled 失败: {e}")
                all_ok = False

        return all_ok

    def delete_document(self, dataset_id: str, doc_id: str) -> bool:
        """删除数据集中的文档。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。

        Returns:
            是否删除成功。
        """
        self._request("DELETE", f"/datasets/{dataset_id}/documents", json={"ids": [doc_id]})
        return True

    def delete_documents(self, dataset_id: str, doc_ids: list[str]) -> bool:
        """批量删除数据集中的文档。

        Args:
            dataset_id: 数据集 ID。
            doc_ids: 文档 ID 列表。

        Returns:
            是否删除成功。
        """
        self._request("DELETE", f"/datasets/{dataset_id}/documents", json={"ids": doc_ids})
        return True

    def delete_all_documents(self, dataset_id: str) -> bool:
        """删除数据集中的所有文档。

        Args:
            dataset_id: 数据集 ID。

        Returns:
            是否删除成功。
        """
        self._request("DELETE", f"/datasets/{dataset_id}/documents", json={"delete_all": True})
        return True

    # ------------------------------------------------------------------ #
    #  文档解析
    # ------------------------------------------------------------------ #

    def get_document_info(self, dataset_id: str, doc_id: str) -> dict:
        """获取单个文档的详细信息（含解析状态）。

        通过 list_documents 的 id 过滤参数实现单文档查询。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。

        Returns:
            文档信息字典，关键字段：
            - run: 解析状态 (UNSTART/RUNNING/CANCEL/DONE/FAIL)
            - progress: 解析进度 (0.0 ~ 1.0)
            - progress_msg: 解析日志消息
            - process_begin_at: 解析开始时间
            - process_duration: 解析耗时（秒）
            - chunk_count: 已生成分块数
            - token_count: 已生成 token 数

        Raises:
            RAGFlowError: 文档不存在或 API 错误。
        """
        params = {"page": 1, "page_size": 1, "id": doc_id}
        data = self._request(
            "GET", f"/datasets/{dataset_id}/documents", params=params
        )
        docs = data.get("data", {}).get("docs", [])
        if not docs:
            raise RAGFlowError(f"RAGFlow 文档不存在: dataset={dataset_id}, doc={doc_id}")
        return docs[0]

    def run_parse(self, dataset_id: str, doc_ids: list[str] | None = None) -> bool:
        """触发文档解析。

        Args:
            dataset_id: 数据集 ID。
            doc_ids: 要解析的文档 ID 列表，None 表示解析所有文档。

        Returns:
            是否成功触发。
        """
        payload: dict = {"document_ids": doc_ids or []}
        self._request("POST", f"/datasets/{dataset_id}/chunks", json=payload)
        return True

    def stop_parse(self, dataset_id: str, doc_ids: list[str] | None = None) -> bool:
        """停止文档解析。

        Args:
            dataset_id: 数据集 ID。
            doc_ids: 要停止解析的文档 ID 列表，None 表示停止所有。

        Returns:
            是否成功停止。
        """
        payload = {}
        if doc_ids:
            payload["document_ids"] = doc_ids
        self._request("DELETE", f"/datasets/{dataset_id}/chunks", json=payload)
        return True

    # ------------------------------------------------------------------ #
    #  切片（Chunk）与预览
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  分块（Chunk）管理
    # ------------------------------------------------------------------ #

    def list_chunks(
        self,
        dataset_id: str,
        doc_id: str,
        keywords: str = "",
        page: int = 1,
        page_size: int = 30,
    ) -> dict:
        """获取文档的分块列表。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。
            keywords: 搜索关键词。
            page: 页码。
            page_size: 每页数量。

        Returns:
            包含分块列表和分页信息的字典。
        """
        params = {"page": page, "page_size": page_size}
        if keywords:
            params["keywords"] = keywords
        data = self._request("GET", f"/datasets/{dataset_id}/documents/{doc_id}/chunks", params=params)
        return data.get("data", {})

    def get_chunk(self, dataset_id: str, doc_id: str, chunk_id: str) -> dict:
        """获取单个分块详情。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。
            chunk_id: 分块 ID。

        Returns:
            分块信息字典。
        """
        data = self._request("GET", f"/datasets/{dataset_id}/documents/{doc_id}/chunks/{chunk_id}")
        return data.get("data", {})

    def add_chunk(
        self,
        dataset_id: str,
        doc_id: str,
        content: str,
        important_keywords: list[str] | None = None,
        questions: list[str] | None = None,
    ) -> str:
        """添加分块。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。
            content: 分块内容。
            important_keywords: 重要关键词列表。
            questions: 相关问题列表。

        Returns:
            新建分块的 ID。
        """
        payload = {"content": content}
        if important_keywords:
            payload["important_keywords"] = important_keywords
        if questions:
            payload["questions"] = questions
        data = self._request("POST", f"/datasets/{dataset_id}/documents/{doc_id}/chunks", json=payload)
        return data["data"]["chunk_id"]

    def update_chunk(
        self,
        dataset_id: str,
        doc_id: str,
        chunk_id: str,
        content: str | None = None,
        important_keywords: list[str] | None = None,
        questions: list[str] | None = None,
        available: bool | None = None,
    ) -> bool:
        """更新分块内容或配置。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。
            chunk_id: 分块 ID。
            content: 分块内容。
            important_keywords: 重要关键词列表。
            questions: 相关问题列表。
            available: 是否可用。

        Returns:
            是否更新成功。
        """
        payload = {}
        if content is not None:
            payload["content"] = content
        if important_keywords is not None:
            payload["important_keywords"] = important_keywords
        if questions is not None:
            payload["questions"] = questions
        if available is not None:
            payload["available"] = available
        self._request("PATCH", f"/datasets/{dataset_id}/documents/{doc_id}/chunks/{chunk_id}", json=payload)
        return True

    def delete_chunks(self, dataset_id: str, doc_id: str, chunk_ids: list[str]) -> bool:
        """删除分块。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。
            chunk_ids: 分块 ID 列表。

        Returns:
            是否删除成功。
        """
        self._request("DELETE", f"/datasets/{dataset_id}/documents/{doc_id}/chunks", json={"chunk_ids": chunk_ids})
        return True

    def delete_all_chunks(self, dataset_id: str, doc_id: str) -> bool:
        """删除文档的所有分块。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。

        Returns:
            是否删除成功。
        """
        self._request("DELETE", f"/datasets/{dataset_id}/documents/{doc_id}/chunks", json={"delete_all": True})
        return True

    def batch_update_chunks_status(
        self,
        dataset_id: str,
        doc_id: str,
        chunk_ids: list[str],
        available: bool,
    ) -> bool:
        """批量更新分块可用状态。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。
            chunk_ids: 分块 ID 列表。
            available: 是否可用。

        Returns:
            是否更新成功。
        """
        payload = {
            "chunk_ids": chunk_ids,
            "available": available,
        }
        self._request("PATCH", f"/datasets/{dataset_id}/documents/{doc_id}/chunks", json=payload)
        return True

    # ------------------------------------------------------------------ #
    #  检索
    # ------------------------------------------------------------------ #

    def retrieval(
        self,
        dataset_ids: list[str],
        question: str,
        page: int = 1,
        page_size: int = 30,
        similarity_threshold: float | None = None,
        vector_similarity_weight: float | None = None,
        top_k: int | None = None,
        rerank_model: str | None = None,
        keyword: bool = False,
    ) -> dict:
        """从指定数据集检索分块。

        Args:
            dataset_ids: 数据集 ID 列表。
            question: 检索问题。
            page: 页码。
            page_size: 每页数量。
            similarity_threshold: 相似度阈值。
            vector_similarity_weight: 向量相似度权重。
            top_k: 返回 top k 个结果。
            rerank_model: 重排序模型名称。
            keyword: 是否启用关键词检索。

        Returns:
            检索结果字典。
        """
        payload = {
            "dataset_ids": dataset_ids,
            "question": question,
            "page": page,
            "page_size": page_size,
        }
        if similarity_threshold is not None:
            payload["similarity_threshold"] = similarity_threshold
        if vector_similarity_weight is not None:
            payload["vector_similarity_weight"] = vector_similarity_weight
        if top_k is not None:
            payload["top_k"] = top_k
        if rerank_model is not None:
            payload["rerank_model"] = rerank_model
        if keyword:
            payload["keyword"] = keyword

        data = self._request("POST", "/retrieval", json=payload)
        return data.get("data", {})

    # ------------------------------------------------------------------ #
    #  兼容旧接口（保留向后兼容）
    # ------------------------------------------------------------------ #

    def get_document_chunks(self, *args, **kwargs) -> dict:
        """向后兼容：等同于 list_chunks。"""
        return self.list_chunks(*args, **kwargs)

    def get_document_preview_url(self, dataset_id: str, doc_id: str) -> str:
        """获取文档预览 URL（RAGFlow Web UI 路径，非标准 API）。

        Args:
            dataset_id: 数据集 ID。
            doc_id: 文档 ID。

        Returns:
            文档预览的完整 URL。
        """
        return f"{self.base_url}/dataset/{dataset_id}/document/{doc_id}"
