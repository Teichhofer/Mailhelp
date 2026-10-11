"""Vision OCR (1.4): multimodal requests through the shared OpenRouter flow."""
from __future__ import annotations

import json

import httpx

from mailhelp.analysis import Analyzer
from mailhelp.config import PromptConfig
from mailhelp.models import VisionExtractionResult
from mailhelp.openrouter import OpenRouterClient
from test_core import prompt_config

IMAGE = "data:image/jpeg;base64," + "A" * 400


class Recorder:
    def __init__(self): self.events = []
    def event(self, *args, **fields): self.events.append((args[2], fields))
    def llm_event(self, event, **fields): self.events.append((event, fields))


def answer(content):
    return {"id": "c-1", "choices": [{"message": {"content": json.dumps(content)}}]}


def test_openrouter_sends_image_parts_and_logs_only_their_size():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=answer({"legible": True, "text": "Frist 3. März"}), request=request)

    log = Recorder()
    client = OpenRouterClient("secret", 1, 0, 10, httpx.MockTransport(handler), logger=log)
    _, content = client.complete("google/gemini-3.5-flash-lite", {}, "Lies", {"attachment": {}},
                                 stage="vision_ocr", images=[IMAGE])
    client.close()
    assert content == {"legible": True, "text": "Frist 3. März"}
    assert seen[0]["messages"][1]["content"] == [
        {"type": "text", "text": json.dumps({"attachment": {}})},
        {"type": "image_url", "image_url": {"url": IMAGE}}]
    started = dict(log.events)["request_started"]["request"]
    assert started["messages"][1]["content"][1]["image_url"]["url"] == (
        f"data:image/jpeg;base64,<{len(IMAGE)} Zeichen>")
    assert "A" * 100 not in json.dumps(log.events, default=str)


class Completer:
    def __init__(self): self.calls = []

    def complete(self, model, parameters, system, payload, **metadata):
        self.calls.append((model, system, payload, metadata))
        return "vision-call", {"legible": True, "text": "Aushang"}


def with_vision_prompt() -> PromptConfig:
    data = prompt_config().model_dump()
    data["prompts"]["vision_ocr"] = {"model": "google/gemini-3.5-flash-lite",
                                     "system_prompt": "Lies den Text."}
    return PromptConfig.model_validate(data)


def test_analyzer_reads_documents_with_the_vision_step():
    completer = Completer()
    call, result = Analyzer(completer, with_vision_prompt()).read_document(
        "flyer.jpg", "image/jpeg", [IMAGE, IMAGE])
    assert (call, result) == ("vision-call", VisionExtractionResult(legible=True, text="Aushang"))
    model, system, payload, metadata = completer.calls[0]
    assert (model, system, metadata["stage"]) == ("google/gemini-3.5-flash-lite", "Lies den Text.",
                                                  "vision_ocr")
    assert payload == {"attachment": {"filename": "flyer.jpg", "content_type": "image/jpeg", "pages": 2}}
    assert metadata["images"] == [IMAGE, IMAGE]
    assert metadata["response_schema"] is VisionExtractionResult


def test_text_steps_send_no_image_argument():
    completer = Completer()
    analyzer = Analyzer(completer, with_vision_prompt())
    analyzer._classified_run("summary", {"mail": {}}, lambda raw: raw)
    assert "images" not in completer.calls[0][3]


def test_prompts_without_the_vision_step_stay_valid_but_unknown_steps_do_not():
    import pytest
    assert "vision_ocr" not in prompt_config().prompts
    data = with_vision_prompt().model_dump()
    data["prompts"]["unbekannt"] = data["prompts"]["vision_ocr"]
    with pytest.raises(ValueError, match="erforderlichen Schritte"):
        PromptConfig.model_validate(data)
