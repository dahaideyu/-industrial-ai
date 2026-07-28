# cython: annotation_typing=False, infer_types=False, language_level=3
"""合规性文档视觉检测任务：使用视觉模型检测公章、签名、有效期"""
import base64
import json
import logging
import os
import tempfile

import requests
from openai import OpenAI

from backend.services.knowledge_management.tasks.celery_app import kb_celery
from backend.core.knowledge_management.database import SessionLocal
from backend.core.knowledge_management.models import DocumentVersion, Document
# 复用 PLC 解析器的 DashScope 配置（已验证可用的 API key）
from backend.services.plc_analysis_report.config import settings as vision_settings

logger = logging.getLogger(__name__)


@kb_celery.task(bind=True, queue="kb_review")
def compliance_vision_detect(self, version_id: str):
    """合规性文档视觉检测：检测公章、签名、有效期。

    流程：
    1. 获取文档版本的 MinIO 存储路径
    2. 下载文件并转为 base64 图片（PDF 取首页）
    3. 调用视觉模型（qwen-vl-plus）检测
    4. 更新 has_stamp、has_signature、valid_from、valid_until
    """
    db = SessionLocal()
    try:
        version = db.query(DocumentVersion).filter(
            DocumentVersion.id == version_id
        ).first()
        if not version:
            logger.warning("compliance_vision_detect: 版本不存在, version_id=%s", version_id)
            return

        # 获取存储路径
        from backend.clients.knowledge_management.minio_client import MinIOClient
        minio = MinIOClient()

        # 优先使用 PDF 预览路径，其次 storage_path
        file_path = version.pdf_preview_path or version.storage_path
        if not file_path:
            logger.warning("compliance_vision_detect: 无文件路径, version_id=%s", version_id)
            version.has_stamp = False
            version.has_signature = False
            db.commit()
            return

        # 下载到临时文件
        tmp_dir = tempfile.mkdtemp(prefix="compliance_vision_")
        tmp_file = os.path.join(tmp_dir, os.path.basename(file_path))
        try:
            minio.download_file(file_path, tmp_file)

            # 转换为 base64 图片列表
            ext = os.path.splitext(tmp_file)[1].lower()
            image_list = []  # [(base64_str, mime_type), ...]

            if ext == '.pdf':
                try:
                    import fitz
                    doc_pdf = fitz.open(tmp_file)
                    total = doc_pdf.page_count
                    if total == 0:
                        raise ValueError("PDF 无页面")

                    # 选页策略：≤3页全选，>3页取前2+末页（公章/签名/有效期通常在前两页或末页）
                    if total <= 3:
                        page_nums = list(range(total))
                    else:
                        page_nums = [0, 1, total - 1]

                    mat = fitz.Matrix(150 / 72, 150 / 72)
                    for pn in page_nums:
                        pix = doc_pdf[pn].get_pixmap(matrix=mat)
                        img_b64 = base64.b64encode(pix.tobytes("jpeg")).decode("utf-8")
                        image_list.append((img_b64, "image/jpeg"))
                    doc_pdf.close()
                    logger.info(
                        "PDF 视觉检测: total_pages=%d, selected=%s, version_id=%s",
                        total, page_nums, version_id,
                    )
                except ImportError:
                    logger.warning("PyMuPDF 未安装，无法解析PDF视觉检测")
                    version.has_stamp = False
                    version.has_signature = False
                    db.commit()
                    return
            elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff'):
                mime = "image/jpeg" if ext in ('.jpg', '.jpeg') else "image/png"
                with open(tmp_file, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("utf-8")
                image_list.append((img_b64, mime))
            else:
                logger.info("compliance_vision_detect: 非图片/PDF文件，跳过视觉检测, version_id=%s", version_id)
                version.has_stamp = False
                version.has_signature = False
                db.commit()
                return

            # 调用视觉模型（支持多图）
            result = _call_vision_model(image_list)
            logger.info("合规性视觉检测结果: version_id=%s, result=%s", version_id, result)

            # 更新版本
            version.has_stamp = result.get("has_stamp", False)
            version.has_signature = result.get("has_signature", False)
            if result.get("valid_from"):
                version.valid_from = result["valid_from"]
            if result.get("valid_until"):
                version.valid_until = result["valid_until"]
            # 视觉模型 OCR 文字 → 填充 extracted_text（图片文档无文本时 AI 审核也能用）
            ocr_text = result.get("ocr_text", "")
            if ocr_text and not version.extracted_text:
                version.extracted_text = ocr_text
                version.extract_status = "done"
                logger.info("视觉模型 OCR 文字已填充: version_id=%s, len=%d", version_id, len(ocr_text))

            # 生成合规性评分
            _compute_compliance_score(version, result)

            db.commit()
            logger.info(
                "合规性视觉检测完成: version_id=%s, stamp=%s, signature=%s, valid_until=%s",
                version_id, version.has_stamp, version.has_signature, version.valid_until,
            )

        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as exc:
        logger.exception("合规性视觉检测失败: version_id=%s", version_id)
        if self.request.retries >= 2:
            try:
                version = db.query(DocumentVersion).filter(
                    DocumentVersion.id == version_id
                ).first()
                if version:
                    version.has_stamp = False
                    version.has_signature = False
                    db.commit()
            except Exception:
                pass
            return
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


def _call_vision_model(image_list: list) -> dict:
    """调用视觉模型检测公章、签名、有效期。

    Args:
        image_list: [(base64_str, mime_type), ...] 图片列表。

    Returns:
        {"has_stamp": bool, "has_signature": bool, "valid_from": str|None, "valid_until": str|None}
    """
    client = OpenAI(
        api_key=vision_settings.dashscope_api_key,
        base_url=vision_settings.dashscope_base_url,
    )

    # 构建多图 content 列表
    content_parts = []
    for i, (img_b64, mime) in enumerate(image_list):
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_b64}"},
        })

    page_hint = ""
    if len(image_list) > 1:
        page_hint = f"共 {len(image_list)} 张图片，按顺序对应文档的不同页面。"

    prompt = """你是一个合规性文档审核专家。请仔细检查以下{}张图片（同一份文档的关键页面），完成两项任务：

## 任务一：合规检测
1. **has_stamp**：任意页面上是否有红色圆形公章/印章？
2. **has_signature**：任意页面上是否有手写签名或电子签名？
3. **valid_from**：有效期起始日期（YYYY-MM-DD），未找到填 null
4. **valid_until**：有效期截止日期（YYYY-MM-DD），未找到填 null

## 任务二：文字提取（OCR）
将所有页面上可见的文字内容提取出来，包括标题、正文、表格、日期、编号等。不要遗漏任何文字。如果某页无文字，注明"（无文字）"。

{}
请输出 JSON，不要加其他说明：
{{}}""".format(len(image_list), page_hint, "has_stamp")

    content_parts.append({"type": "text", "text": prompt})

    response = client.chat.completions.create(
        model=vision_settings.vision_model,
        messages=[
            {
                "role": "user",
                "content": content_parts,
            }
        ],
        timeout=vision_settings.vision_timeout,
        max_tokens=2000,
    )

    content = response.choices[0].message.content.strip()

    # 尝试提取 JSON（支持嵌套花括号的 ocr_text）
    import re
    # 用更宽松的匹配：找最后一个 } 的位置
    json_match = re.search(r'\{[\s\S]*\}', content)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            # 兜底：手动提取字段
            logger.warning("JSON 解析失败，尝试手动提取: %s", content[:200])
            result = {"has_stamp": False, "has_signature": False, "valid_from": None, "valid_until": None, "ocr_text": ""}
            for field in ["has_stamp", "has_signature"]:
                m = re.search(rf'"{field}"\s*:\s*(true|false)', content)
                if m:
                    result[field] = m.group(1) == "true"
            for field in ["valid_from", "valid_until"]:
                m = re.search(rf'"{field}"\s*:\s*"([^"]*)"', content)
                if m and m.group(1) and m.group(1) != "null":
                    result[field] = m.group(1)
            m = re.search(r'"ocr_text"\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.DOTALL)
            if m:
                result["ocr_text"] = m.group(1)
            return result

    logger.warning("视觉模型返回无法解析: %s", content[:200])
    return {"has_stamp": False, "has_signature": False, "valid_from": None, "valid_until": None}


def _compute_compliance_score(version: DocumentVersion, vision_result: dict):
    """根据视觉检测结果计算合规性评分。

    评分规则（满分 100）：
    - 已过期 → 直接归零（过期证件无效）
    - 未过期/无日期：
      - 有公章: +40 分
      - 有签名: +30 分
      - 有效期完整且未过期: +30 分
    """
    if not version:
        return

    from datetime import datetime, date

    # 先检查是否过期——过期的合规文档直接归零
    valid_until = vision_result.get("valid_until")
    is_expired = False
    if valid_until:
        try:
            if isinstance(valid_until, str):
                expiry = datetime.strptime(valid_until, "%Y-%m-%d").date()
            else:
                expiry = valid_until
            if expiry < date.today():
                is_expired = True
        except (ValueError, TypeError):
            pass

    if is_expired:
        version.compliance_score = 0
        return

    # 未过期：按项目打分
    score = 0
    if vision_result.get("has_stamp"):
        score += 40
    if vision_result.get("has_signature"):
        score += 30
    if valid_until and not is_expired:
        score += 30

    version.compliance_score = score


def _trigger_compliance_vision(db, version_id: str):
    """在文档上传后异步触发合规性视觉检测。"""
    try:
        compliance_vision_detect.delay(version_id)
        logger.info("已调度合规性视觉检测: version_id=%s", version_id)
    except Exception as e:
        logger.warning("调度合规性视觉检测失败: %s", e)
