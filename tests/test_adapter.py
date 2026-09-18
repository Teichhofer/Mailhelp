from datetime import datetime, timezone
import imaplib
import httpx
import pytest

from mailhelp.adapter import PermanentError, RetryableError, RetryInterrupted, RetryPolicy, UncertainWriteError, uncertain_write
from mailhelp.config import AdapterPolicySettings
from mailhelp.openrouter import OpenRouterClient, ProviderResponseInvalid, RateLimitExceeded


def test_provider_response_error_exposes_only_machine_readable_reason():
    error = ProviderResponseInvalid("message_content_null")
    assert error.reason == "message_content_null"
    assert "mail body" not in str(error)


def status(code, headers=None):
    request=httpx.Request("GET", "https://example.test")
    response=httpx.Response(code, request=request, headers=headers)
    return httpx.HTTPStatusError("bad", request=request, response=response)


def test_retry_transport_exponential_exhaustion_and_shutdown():
    waits=[]; attempts=[]
    policy=RetryPolicy(2, 1, 2, lambda delay: waits.append(delay) or False)
    def flaky():
        attempts.append(1)
        if len(attempts)<3: raise httpx.ConnectError("x")
        return "ok"
    assert policy.run(flaky)=="ok" and waits==[1,2]
    with pytest.raises(RetryableError):
        RetryPolicy(0,1,2,lambda _:False).run(lambda: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(RetryInterrupted):
        RetryPolicy(1,1,2,lambda _:True).run(lambda: (_ for _ in ()).throw(imaplib.IMAP4.abort()))


def test_http_status_retry_after_and_permanent():
    errors=[status(429,{"Retry-After":"7"}), status(503)]
    waits=[]
    def operation():
        if errors: raise errors.pop(0)
        return 3
    assert RetryPolicy(2,1,5,lambda delay: waits.append(delay) or False).run(operation)==3
    assert waits==[5,2]
    date="Thu, 01 Jan 1970 00:01:40 GMT"
    errors=[status(429,{"Retry-After":date})]
    assert RetryPolicy(1,1,60,lambda delay: waits.append(delay) or False,lambda:50).run(operation)==3
    assert waits[-1]==50
    errors=[status(429,{"Retry-After":"nonsense"})]
    assert RetryPolicy(1,3,5,lambda delay: waits.append(delay) or False).run(operation)==3
    assert waits[-1]==3
    errors=[status(429)]
    assert RetryPolicy(1,4,5,lambda delay: waits.append(delay) or False).run(operation)==3
    with pytest.raises(PermanentError): RetryPolicy(2,1,2,lambda _:False).run(lambda: (_ for _ in ()).throw(status(400)))


def test_uncertain_write_classification():
    with pytest.raises(UncertainWriteError): uncertain_write(lambda: (_ for _ in ()).throw(httpx.ReadTimeout("x")))
    with pytest.raises(UncertainWriteError): uncertain_write(lambda: (_ for _ in ()).throw(status(500)))
    with pytest.raises(PermanentError): uncertain_write(lambda: (_ for _ in ()).throw(status(401)))
    detailed=status(401); detailed.safe_detail="Telegram sendMessage: Bad Request: chat not found"
    with pytest.raises(PermanentError, match="Telegram sendMessage: Bad Request: chat not found"):
        uncertain_write(lambda: (_ for _ in ()).throw(detailed))
    assert uncertain_write(lambda: 4)==4


def test_backoff_model_order():
    with pytest.raises(ValueError): AdapterPolicySettings(timeout_seconds=1,retries=1,initial_backoff_seconds=2,max_backoff_seconds=1)


def test_llm_budget_survives_client_restart():
    state={"calls":[]}; now=[100.0]
    response={"id":"x","choices":[{"message":{"content":"{}"}}]}
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json=response,request=request))
    arguments=dict(key="x",timeout=1,retries=0,calls_per_minute=1,transport=transport,clock=lambda:now[0],load_calls=lambda:state["calls"],save_calls=lambda calls:state.update(calls=calls))
    OpenRouterClient(**arguments).complete("m",{},"s",{})
    with pytest.raises(RateLimitExceeded) as error: OpenRouterClient(**arguments).complete("m",{},"s",{})
    assert error.value.next_allowed_at==160
    now[0]=160
    OpenRouterClient(**arguments).complete("m",{},"s",{})
