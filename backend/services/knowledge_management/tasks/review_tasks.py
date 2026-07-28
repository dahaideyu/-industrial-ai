# cython: annotation_typing=False, infer_types=False, language_level=3
"""AI 评价任务：调用 DeepSeek 对文档进行关联性和质量评分（含版本差异对比）"""
import difflib
import json
import logging

import requests

from backend.services.knowledge_management.tasks.celery_app import kb_celery
from backend.core.knowledge_management.config import settings
from backend.core.knowledge_management.database import SessionLocal
from backend.core.knowledge_management.models import DocumentVersion, PlanItem

logger = logging.getLogger(__name__)

# 差异块最大字符数（避免变更太大时撑爆上下文）
_MAX_DIFF_CHARS = 2000


@kb_celery.task(bind=True, queue="kb_review")
def ai_review_task(self, version_id: str):
    """AI 审核任务：获取文档提取文本和收集要求，调 DeepSeek 评分。

    评分维度：
    - 关联性评分（0-100）：文档内容与收集要求的匹配程度
    - 质量评分（0-100）：文档内容的完整性、准确性、可读性
    - 版本改进度（0-100，仅非首版）：相比上一版本的实质性改进程度

    含版本差异对比：用 difflib 提取新旧版本差异块，仅发送变更部分，
    避免发送旧版全文撑爆上下文。

    完成后更新 version 的 ai_* 字段，设置 status 为 ai_completed_manual_pending，
    并自动触发收集项评估检查。
    """
    db = SessionLocal()
    try:
        version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        if not version:
            logger.warning("ai_review_task: 版本不存在, version_id=%s", version_id)
            return

        # 如果是重试，更新状态为"重试中"
        if self.request.retries > 0:
            version.status = "ai_retrying"
            version.ai_quality_remark = f"AI审核第{self.request.retries + 1}次重试中..."
            db.commit()
            logger.info("AI审核重试: version_id=%s, retry=%d", version_id, self.request.retries + 1)

        # 获取收集要求
        doc = version.document
        plan_item = doc.plan_item
        category = plan_item.category
        requirement_desc = plan_item.requirement_override or category.requirement_desc
        kb = plan_item.plan.knowledge_base if plan_item.plan else None
        is_compliance = kb and kb.kb_type == 'compliance'

        # 合规性文档：基于收集要求关键词，附加已识别的视觉信息到要求中
        if is_compliance:
            req_lower = (requirement_desc or '').lower()
            # 智能识别收集要求中是否强调某个视觉要素
            require_stamp = any(kw in requirement_desc for kw in ['盖章', '公章', '印章'])
            require_signature = any(kw in requirement_desc for kw in ['签字', '签名', '签发人'])
            require_validity = any(kw in requirement_desc for kw in ['有效期', '有效期限', '截止日期', '生效日期'])

            vision_hints = []
            if require_stamp:
                if version.has_stamp is True:
                    vision_hints.append("✓ 视觉检测已识别到红色公章")
                elif version.has_stamp is False:
                    vision_hints.append("✗ 视觉检测未识别到公章（收集要求要求盖章）")
            if require_signature:
                if version.has_signature is True:
                    vision_hints.append("✓ 视觉检测已识别到签名")
                elif version.has_signature is False:
                    vision_hints.append("✗ 视觉检测未识别到签名（收集要求要求签名）")
            if require_validity:
                if version.valid_from:
                    vision_hints.append(f"📅 有效期起始：{version.valid_from}")
                if version.valid_until:
                    vision_hints.append(f"📅 有效期截止：{version.valid_until}")
                if not version.valid_from and not version.valid_until:
                    vision_hints.append("⚠ 视觉检测未识别到有效期（收集要求要求识别有效期）")

            if vision_hints:
                requirement_desc = requirement_desc + "\n\n## 视觉检测已识别的合规要素\n" + "\n".join(vision_hints)
                logger.info(
                    "合规性文档 AI 审核：附加视觉检测信息, version_id=%s, hints=%d",
                    version_id, len(vision_hints),
                )

        # 判断是否是说明文档（自动生成的文档）
        is_explanation_doc = version.auto_generated or False

        # 获取提取文本
        text = version.extracted_text or ""
        if not text:
            # 文本提取尚未完成 → 延迟重试（最多5次，每次60秒）
            if version.extract_status in (None, "processing"):
                logger.info("文本尚未提取完成，60秒后重试: version_id=%s", version_id)
                raise self.retry(countdown=60, max_retries=5)
            logger.warning("ai_review_task: 无提取文本, version_id=%s", version_id)
            version.ai_relevance_score = 0
            version.ai_quality_score = 0
            version.ai_relevance_remark = "无法提取文本内容"
            version.ai_quality_remark = "无法提取文本内容" + \
                ("\n[AI审核建议] 驳回 — 无法提取文本内容" if is_compliance else "")
            version.status = "ai_completed_manual_pending"
            db.commit()
            _trigger_auto_evaluate(db, plan_item.id)
            return

        # 截取文本避免超长（增加到8000字以获得更好的分析质量）
        text_preview = text[:8000]

        # ── 版本差异对比 ──
        diff_section, duplicate_version_label = _build_version_diff(db, version)
        is_first_version = diff_section is None and duplicate_version_label is None

        # ── 构建评分提示 ──
        if is_explanation_doc:
            # 说明文档的特殊评分逻辑
            base_instruction = """你是一位工业文档质量评估专家。请对以下**说明文档**进行详细评分。

## 重要说明
这是一份由AI自动生成的**图纸解析说明文档**，用于解释和描述原始图纸的内容。请根据以下标准进行评分：

## 评分要求
- **关联性评分**：说明文档对原始图纸的解释是否准确、完整。评估是否涵盖了图纸的关键内容、技术要点和结构。
- **质量评分**：说明文档的结构是否清晰、描述是否准确、专业术语使用是否规范。评估文档的可读性和技术价值。
- **评价说明**：给出具体、详细的评价（150-300字）。重点评价文档作为技术说明文档的价值。"""
        else:
            base_instruction = """你是一位工业文档质量评估专家。请结合你的工业领域知识，对以下文档进行详细评分。

## 重要说明
文档内容由自动提取工具生成，可能存在格式瑕疵或字符识别偏差。请**忽略所有格式问题、乱码、编码错误**，只关注你能理解的文本内容本身。基于你理解的工业知识，判断内容质量。

## 评分要求

### 关联性评分（核心指标）
**严格评估文档与收集要求的匹配程度**，这是最重要的指标：
- 90-100分：文档完全符合收集要求，覆盖了所有必需内容
- 70-89分：文档基本符合要求，但有部分内容缺失或不够深入
- 50-69分：文档与要求有一定关联，但存在明显偏差或遗漏
- 30-49分：文档与要求关联性较差，主题或范围有较大偏差
- 0-29分：**文档与收集要求完全不相关**，或主题完全不同

**重要提示**：如果文档类型、主题、用途与收集要求明显不符（例如：机械说明书放到维修保养手册收集项下），关联性评分应控制在 **30分以下**。

### 合规性文档的"视觉合规要素"扣分规则
**只有收集要求中明确提到某要素时，才对其缺失进行扣分。** 例如：
- 收集要求说"识别有效期、盖章和签名" → 缺一扣一
- 收集要求只说"内容符合性" → 不检查视觉要素
- **缺少要求的公章**（视觉检测未识别到）：关联性评分上限 ≤ 50 分
- **缺少要求的签名**（视觉检测未识别到）：关联性评分上限 ≤ 50 分
- **缺少要求的有效期**：关联性评分上限 ≤ 30 分
- 多个要素同时缺失，按从严原则取最低上限

### 质量评分
内容的逻辑是否合理、操作步骤是否规范完整、是否有可操作性、专业术语使用是否准确。**不要因为格式问题扣分**。

### 评价说明
给出具体、详细的评价（150-300字）。只评价内容本身的优点和不足，不要提及"乱码"、"格式问题"、"编码错误"、"提取效果"等技术性问题。完全聚焦于文档的工业价值和内容质量。**必须明确说明文档是否符合收集要求**。"""

        if is_first_version:
            prompt = """{}

## 收集要求
{}

## 文档内容
{}

## 请输出 JSON 格式评分结果

**重要**：关联性评分必须严格按以下标准执行：
- 如果文档主题与收集要求完全不符（如：机械说明书 vs 维修保养手册），relevance_score 必须 < 30
- 如果文档类型与要求不匹配（如：操作手册 vs 故障案例），relevance_score 必须 < 50
- 只有文档真正符合收集要求时，relevance_score 才能 > 70

{{}}""".format(base_instruction, requirement_desc, text_preview, "relevance_score")
        else:
            # 内容重复时的特殊提示
            duplicate_note = ""
            if duplicate_version_label:
                duplicate_note = f"\n\n**注意：当前版本与{duplicate_version_label}版本内容完全一致，请在评价中说明这一点。**"

            prompt = """{}

## 收集要求
{}

## 上一版本 → 当前版本变更
{}{}

## 当前版本内容
{}

## 请输出 JSON 格式评分结果
{{}}""".format(base_instruction, requirement_desc, diff_section, duplicate_note, text_preview, "relevance_score")

        result = _call_llm(prompt)

        # 检查返回结果是否为空
        if not result or not result.strip():
            raise ValueError("AI 返回结果为空")

        # 尝试提取 JSON（AI 可能在 JSON 前后添加了其他文本）
        json_match = None
        import re
        json_pattern = r'\{[^{}]*\}'
        matches = re.findall(json_pattern, result)
        if matches:
            # 取最后一个匹配的 JSON（通常是最完整的）
            json_match = matches[-1]

        if json_match:
            eval_data = json.loads(json_match)
        else:
            # 直接尝试解析整个结果
            eval_data = json.loads(result)

        version.ai_relevance_score = eval_data.get("relevance_score", 0)
        version.ai_quality_score = eval_data.get("quality_score", 0)
        version.ai_relevance_remark = eval_data.get("relevance_remark", "")
        quality_remark = eval_data.get("quality_remark", "")
        # 版本改进说明合并到质量备注中
        improv_remark = eval_data.get("improvement_remark", "")
        if improv_remark:
            quality_remark = f"{quality_remark}\n[版本改进] {improv_remark}".strip()
        # 内容重复提示
        if duplicate_version_label:
            quality_remark = f"该版本与{duplicate_version_label}版本内容完全一致！\n{quality_remark}"
        version.ai_quality_remark = quality_remark
        version.status = "ai_completed_manual_pending"

        # ── 合规性文档严格评分 ──
        # 规则 1：AI 判断文档与收集要求无关（关联性 < 50）→ 质量和关联性都打 0 分
        if is_compliance and version.ai_relevance_score is not None and version.ai_relevance_score < 50:
            logger.info(
                "合规性文档关联性过低 (score=%d)，强制将关联性和质量设为 0: version_id=%s",
                version.ai_relevance_score, version_id,
            )
            version.ai_relevance_score = 0
            version.ai_quality_score = 0
            version.ai_relevance_remark = (version.ai_relevance_remark or '') + \
                '\n[合规性审查] 该文档与收集要求不相关，评分归零。'
            version.ai_quality_remark = (version.ai_quality_remark or '') + \
                '\n[合规性审查] 由于文档与收集要求不相关，质量评分归零。'

        # 规则 2：合规性文档已过期 → 强制 0 分
        if is_compliance and version.valid_until:
            from datetime import datetime, date
            try:
                if isinstance(version.valid_until, str):
                    expiry = datetime.strptime(version.valid_until, "%Y-%m-%d").date()
                else:
                    expiry = version.valid_until
                if expiry < date.today():
                    logger.info(
                        "合规性文档已过期 (valid_until=%s)，强制将关联性和质量设为 0: version_id=%s",
                        version.valid_until, version_id,
                    )
                    version.ai_relevance_score = 0
                    version.ai_quality_score = 0
                    version.ai_relevance_remark = (version.ai_relevance_remark or '') + \
                        f'\n[合规性审查] 该文档已于 {version.valid_until} 过期，评分归零。'
                    version.ai_quality_remark = (version.ai_quality_remark or '') + \
                        f'\n[合规性审查] 该文档已于 {version.valid_until} 过期，质量评分归零。'
            except (ValueError, TypeError):
                pass

        # 计算 AI 审核建议（decision）
        rel_score = version.ai_relevance_score if version.ai_relevance_score is not None else 0
        qual_score = version.ai_quality_score if version.ai_quality_score is not None else 0
        version.ai_quality_remark = _append_review_decision(
            version.ai_quality_remark or '',
            rel_score,
            qual_score,
            is_compliance,
        )

        # 统一提交（包含合规性严格评分和AI审核建议）
        db.commit()

        improv_score = eval_data.get("improvement_score")
        logger.info(
            "AI 审核完成: version_id=%s, relevance=%d, quality=%d, improvement=%s, is_v1=%s, compliance=%s",
            version_id, version.ai_relevance_score, version.ai_quality_score,
            str(improv_score) if improv_score is not None else "N/A", is_first_version,
            is_compliance,
        )

        # 自动触发收集项评估检查
        _trigger_auto_evaluate(db, plan_item.id)

    except Exception as exc:
        logger.exception("AI 审核失败: version_id=%s", version_id)
        # 如果是最后一次重试，更新状态为失败
        if self.request.retries >= self.max_retries - 1:
            try:
                version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
                if version:
                    version.status = "ai_review_failed"
                    version.ai_quality_remark = f"AI审核失败: {str(exc)[:200]}"
                    db.commit()
                    logger.info("AI 审核最终失败，已更新状态: version_id=%s", version_id)
            except Exception:
                pass
            return  # 不再重试
        raise self.retry(exc=exc)
    finally:
        db.close()


def _build_version_diff(db, current_version: DocumentVersion) -> tuple[str | None, str | None]:
    """构建版本差异描述。

    查找同一文档的上一版本（is_current=False，按创建时间降序），
    用 difflib 提取差异块，仅返回新增/修改/删除的文本段。

    Returns:
        (差异描述字符串, 重复的版本号)；如果是首版（无旧版本）或旧版无提取文本，返回 (None, None)。
        如果内容完全相同，返回 (警告信息, 重复版本号)。
    """
    # 查找上一版本
    prev = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == current_version.document_id,
            DocumentVersion.id != current_version.id,
        )
        .order_by(DocumentVersion.created_at.desc())
        .first()
    )
    if not prev or not prev.extracted_text:
        return None, None

    old_text = prev.extracted_text
    new_text = current_version.extracted_text or ""

    # 检查内容是否完全相同
    if old_text.strip() == new_text.strip():
        return f"[内容重复] 该版本与{prev.version_label}版本内容完全一致！", prev.version_label

    # 用 SequenceMatcher 找出差异块
    matcher = difflib.SequenceMatcher(None, old_text, new_text)
    diff_blocks = []
    total_chars = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue  # 跳过未变更部分
        if total_chars >= _MAX_DIFF_CHARS:
            diff_blocks.append("...（变更过多，已截断）")
            break

        old_chunk = old_text[i1:i2].strip()
        new_chunk = new_text[j1:j2].strip()

        if tag == "insert":
            block = f"[新增]\n{new_chunk[:300]}"
        elif tag == "delete":
            block = f"[删除]\n{old_chunk[:300]}"
        elif tag == "replace":
            block = f"[修改] 旧:\n{old_chunk[:200]}\n→ 新:\n{new_chunk[:200]}"
        else:
            continue

        diff_blocks.append(block)
        total_chars += len(block)

    if not diff_blocks:
        return None, None

    return "\n\n".join(diff_blocks), None


def _trigger_auto_evaluate(db, plan_item_id: str):
    """触发收集项自动评估检查（懒加载避免循环依赖）。"""
    try:
        from backend.services.knowledge_management.evaluation_svc import evaluation_svc
        evaluation_svc.check_auto_evaluate(db, plan_item_id)
    except Exception:
        logger.warning("自动评估触发失败: plan_item_id=%s", plan_item_id, exc_info=True)


def _append_review_decision(
    quality_remark: str,
    relevance_score: int,
    quality_score: int,
    is_compliance: bool = False,
) -> str:
    """根据评分生成 AI 审核建议状态，追加到质量备注中。

    合规性文档的判定更严格：
    - 通过: relevance >= 80 AND quality >= 80
    - 待完善: relevance >= 60 AND quality >= 60（合规性: relevance >= 50 AND quality >= 50）
    - 驳回: 不满足以上条件
    """
    if is_compliance:
        if relevance_score >= 80 and quality_score >= 80:
            decision = "通过"
        elif relevance_score >= 50 and quality_score >= 50:
            decision = "待完善"
        else:
            decision = "驳回"
    else:
        if relevance_score >= 80 and quality_score >= 80:
            decision = "通过"
        elif relevance_score >= 60 and quality_score >= 60:
            decision = "待完善"
        else:
            decision = "驳回"

    return f"{quality_remark}\n[AI审核建议] {decision}"


def _call_llm(prompt: str) -> str:
    """调用 LLM API 生成文本（根据 PROVIDER 环境变量自动适配模型供应商）。

    Args:
        prompt: 用户提示。

    Returns:
        模型返回的文本内容。

    Raises:
        RuntimeError: API 调用失败。
    """
    url = f"{settings.deepseek_base_url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.deepseek_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4000,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("LLM API 未返回有效响应")

    return choices[0]["message"]["content"].strip()
