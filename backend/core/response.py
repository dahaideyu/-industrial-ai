# cython: annotation_typing=False, infer_types=False, language_level=3
from fastapi.responses import JSONResponse


def success_response(data=None, msg="ok"):
    """统一成功响应"""
    return JSONResponse(content={"code": 200, "msg": msg, "data": data})


def error_response(msg, code=500, status_code=500):
    """统一错误响应"""
    return JSONResponse(content={"code": code, "msg": msg}, status_code=status_code)
