# cython: annotation_typing=False, infer_types=False, language_level=3
from collections import Counter
import re

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from core.response import success_response, error_response

router = APIRouter(prefix="/api", tags=["document-analysis"])


class DocumentAnalysisRequest(BaseModel):
    title: str | None = Field(default=None, description="文档标题")
    content: str = Field(..., min_length=1, description="文档正文内容")
    top_n_keywords: int = Field(default=10, ge=1, le=30, description="返回关键词数量")


@router.post("/document_analysis")
def analyze_document(data: DocumentAnalysisRequest = Body(...)):
    """文档分析接口：返回文档基础统计和高频关键词。"""
    try:
        text = data.content.strip()
        if not text:
            return error_response(msg="文档内容不能为空", code=400, status_code=400)

        lines = [line for line in text.splitlines() if line.strip()]
        words = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text.lower())
        stop_words = {"the", "and", "for", "with", "this", "that", "is", "are", "to", "of", "在", "的", "了", "和", "是"}
        tokens = [w for w in words if w not in stop_words and len(w) > 1]
        keyword_counts = Counter(tokens).most_common(data.top_n_keywords)

        result = {
            "title": data.title,
            "char_count": len(text),
            "line_count": len(lines),
            "word_count": len(words),
            "keywords": [{"word": word, "count": count} for word, count in keyword_counts],
        }
        return success_response(data=result, msg="文档分析完成")
    except Exception as e:
        return error_response(msg=f"文档分析失败: {str(e)}")
