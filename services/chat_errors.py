"""Map persona failures without displaying provider bodies or internal exceptions."""
import httpx

REPLY_ERROR = "这次聊天没能生成有效回复，请换个说法再试一次；本次不扣次数。"
PROCESSING_ERROR = "这次聊天处理失败，请稍后重试；本次不扣次数。"

def chat_error_message(exc):
    if isinstance(exc, httpx.HTTPStatusError) and exc.request.url.path == "/api/mention-chat":
        if exc.response.status_code not in {500, 502}:
            return None
        try: data=exc.response.json()
        except (ValueError, UnicodeError): return PROCESSING_ERROR
        code=data.get("error_code") if isinstance(data,dict) else None
        legacy=data.get("error") if isinstance(data,dict) else None
        if not isinstance(code,str): code=None
        if not isinstance(legacy,str): legacy=None
        if code in {"chat_reply_format","chat_reply_rejected"} or legacy in {
            "No safe persona reply","Invalid persona reply","Invalid mention chat response","Invalid persona source references","Unsupported persona tool"}:
            return REPLY_ERROR
        return PROCESSING_ERROR
    if isinstance(exc, ValueError) and str(exc) in {
        "Invalid mention persona response","Unsafe mention persona response","Empty mention persona response",
        "Invalid persona sources","Invalid persona source URL","Private persona source URL",
        "Duplicate persona source URL","Persona source footer mismatch"}:
        return REPLY_ERROR
    return None
