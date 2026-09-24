"""RAG 规则问答共享配置与固定失败文案（各 RAG 调用点复用）。"""
import os

import httpx

RIFT_QA_DEFAULT_BASE_URL = "http://127.0.0.1:7862"

RIFT_QA_CONNECT_ERROR = "连接失败：请确认 7862 端口服务已启动"
RIFT_QA_TIMEOUT = "请求超时，请稍后重试"
RIFT_QA_UPSTREAM_ERROR = "RAG 服务返回异常：上游服务响应错误"
RIFT_QA_FORMAT_ERROR = "RAG 服务返回异常：响应数据格式错误"
RIFT_QA_INTERNAL_ERROR = "RAG 服务内部错误，请稍后重试或检查 7862 端口日志"
RIFT_QA_EMPTY_RESULT = "RAG 服务返回了空结果，请检查 7862 端口服务日志"


def rift_rag_qa_base_url() -> str:
    """RAG 问答服务 base URL，RIFT_RAG_BASE_URL / RIFT_QA_BASE_URL 可覆盖。"""
    raw = (
        os.getenv("RIFT_RAG_BASE_URL")
        or os.getenv("RIFT_QA_BASE_URL")
        or ""
    ).strip()
    return (raw or RIFT_QA_DEFAULT_BASE_URL).rstrip("/")


def map_rag_qa_error(exc: Exception) -> str:
    """RAG 调用异常 → 固定 QQ 失败文案。"""
    if isinstance(exc, httpx.TimeoutException):
        return RIFT_QA_TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else None
        if status is not None and status >= 500:
            return RIFT_QA_INTERNAL_ERROR
        return RIFT_QA_UPSTREAM_ERROR
    if isinstance(exc, httpx.RequestError):
        return RIFT_QA_CONNECT_ERROR
    if isinstance(exc, ValueError):
        if str(exc) == RIFT_QA_EMPTY_RESULT:
            return RIFT_QA_EMPTY_RESULT
        return RIFT_QA_FORMAT_ERROR
    return RIFT_QA_UPSTREAM_ERROR
