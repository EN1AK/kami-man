import httpx,pytest
from services.chat_errors import chat_error_message,REPLY_ERROR,PROCESSING_ERROR
from services.ygo_rag_agent_api import map_agent_error,AGENT_HTTP_ERROR
@pytest.mark.parametrize("code,expected",[("chat_reply_format",REPLY_ERROR),("chat_reply_rejected",REPLY_ERROR),("chat_internal_error",PROCESSING_ERROR)])
def test_chat_errors_are_specific(code,expected):
    response=httpx.Response(500,json={"error_code":code},request=httpx.Request("POST","http://localhost/api/mention-chat"))
    exc=httpx.HTTPStatusError("error",request=response.request,response=response)
    assert map_agent_error(exc)==expected
def test_professional_errors_unchanged():
    response=httpx.Response(500,json={"error_code":"chat_reply_format"},request=httpx.Request("POST","http://localhost/api/agent"))
    assert map_agent_error(httpx.HTTPStatusError("error",request=response.request,response=response))==AGENT_HTTP_ERROR
def test_local_persona_validation_is_not_rag_outage():
    assert map_agent_error(ValueError("Unsafe mention persona response"))==REPLY_ERROR
