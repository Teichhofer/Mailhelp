"""7.2.5: Notion OAuth grants – rotation, workspace binding and concurrent renewals (synthetic)."""
import base64
import json

import httpx
import pytest

from mailhelp.external.contracts import ExternalUnavailable, OAuthTokenError
from mailhelp.external.notion_oauth import NotionGrant, NotionTokenFile, NotionTokenProvider, exchange, token_path

GRANT = {"access_token": "a1", "refresh_token": "r1", "workspace_id": "w1", "bot_id": "b1"}


def provider(tmp_path, handler):
    tokens = NotionTokenFile(tmp_path / "notion-token.json")
    tokens.save(NotionGrant.model_validate(GRANT))
    return tokens, NotionTokenProvider("cid", "csecret", tokens, transport=httpx.MockTransport(handler))


def test_the_saved_grant_is_used_and_a_refused_one_is_renewed_and_rotated(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:csecret").decode()
        assert json.loads(request.content) == {"grant_type": "refresh_token", "refresh_token": "r1"}
        return httpx.Response(200, json={**GRANT, "access_token": "a2", "refresh_token": "r2",
                                         "workspace_name": "Synthetisch"})
    tokens, tokens_provider = provider(tmp_path, handler)
    assert tokens_provider.access_token() == "a1" and tokens_provider.access_token() == "a1" and calls == []
    tokens_provider.invalidate()
    assert tokens_provider.access_token() == "a2" and len(calls) == 1
    saved = json.loads((tmp_path / "notion-token.json").read_text())
    assert saved["refresh_token"] == "r2" and saved["workspace_name"] == "Synthetisch"
    assert tokens.load().refresh_token == "r2"
    tokens_provider.close()


def test_a_pair_rotated_meanwhile_by_another_process_is_taken_instead_of_renewing(tmp_path):
    tokens, tokens_provider = provider(tmp_path, lambda request: pytest.fail("erneuert"))
    assert tokens_provider.access_token() == "a1"
    tokens.save(NotionGrant.model_validate({**GRANT, "access_token": "a9", "refresh_token": "r9"}))
    tokens_provider.invalidate()
    assert tokens_provider.access_token() == "a9"


def test_a_renewal_for_another_workspace_or_bot_is_refused(tmp_path):
    for changed in ({"workspace_id": "fremd"}, {"bot_id": "fremd"}):
        tokens, tokens_provider = provider(
            tmp_path, lambda request, changed=changed: httpx.Response(200, json={**GRANT, **changed}))
        tokens_provider.access_token()
        tokens_provider.invalidate()
        with pytest.raises(OAuthTokenError, match="anderen Arbeitsbereich"):
            tokens_provider.access_token()
        assert tokens.load().workspace_id == "w1"


@pytest.mark.parametrize(("answer", "error"), [
    (httpx.Response(400, json={"error": "invalid_grant", "access_token": "geheim"}), OAuthTokenError),
    (httpx.Response(200, content=b"kein json"), OAuthTokenError),
    (httpx.Response(200, json={"access_token": "nur"}), OAuthTokenError),
    (httpx.Response(503), ExternalUnavailable),
])
def test_failed_renewals_keep_the_saved_grant_and_never_show_tokens(tmp_path, answer, error):
    tokens, tokens_provider = provider(tmp_path, lambda request: answer)
    tokens_provider.access_token()
    tokens_provider.invalidate()
    with pytest.raises(error) as raised:
        tokens_provider.access_token()
    assert "geheim" not in str(raised.value) and raised.value.__cause__ is None
    assert tokens.load().refresh_token == "r1"


def test_without_a_sign_in_the_message_names_the_way(tmp_path):
    tokens = NotionTokenFile(tmp_path / "fehlt.json")
    with pytest.raises(OAuthTokenError, match="Notion verbinden"):
        NotionTokenProvider("c", "s", tokens).access_token()
    (tmp_path / "kaputt.json").write_text("{")
    assert NotionTokenFile(tmp_path / "kaputt.json").load() is None
    assert token_path(tmp_path, 1).name == "notion-token.json" and token_path(tmp_path, 4).name == "notion-token-4.json"


def test_exchange_sends_the_code_with_basic_credentials(tmp_path):
    seen = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: seen.append(request) or
                                                        httpx.Response(200, json=GRANT)))
    assert exchange(client, "id", "secret", {"grant_type": "authorization_code", "code": "c"}).bot_id == "b1"
    assert json.loads(seen[0].content)["code"] == "c" and seen[0].url == "https://api.notion.com/v1/oauth/token"
