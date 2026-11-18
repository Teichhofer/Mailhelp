"""Prompts, models and LLM parameters of each step. (7.0: split from models.py)"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from .base import ConfigModel


class PromptStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    system_prompt: str = Field(min_length=1)
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    routes: list[LlmRoute] | None = None
    # Provider routing for the default route; keeps model and parameters from
    # ``defaults``/``parameters`` instead of duplicating them in ``routes``.
    provider_preferences: OpenRouterProviderPreferences | None = None
    provider_retries: int = Field(default=1, ge=0, le=10)
    output_token_retry: OutputTokenRetry | None = None
    # 5.3: use the model and routes of another step (e.g. the help chat uses action_router's),
    # instead of copying a model name; own parameters such as max_tokens still apply.
    model_route: str | None = Field(default=None, pattern=r"^[a-z_]{1,64}$")

    @model_serializer(mode="wrap")
    def _without_unused_route(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # 5.3: an unused route reference is not written, so every earlier fingerprint stays valid.
        data: dict[str, Any] = handler(self)
        if data.get("model_route") is None:
            data.pop("model_route", None)
        return data

    @model_validator(mode="after")
    def valid_routes(self) -> PromptStep:
        if self.model_route is not None and (self.model or self.routes is not None or self.provider_preferences):
            raise ValueError("model_route schließt model, routes und provider_preferences aus")
        if self.routes is not None and self.provider_preferences is not None:
            raise ValueError("provider_preferences gilt nur ohne routes; dort je Route angeben")
        if self.routes is not None:
            if not self.routes:
                raise ValueError("routes darf nicht leer sein")
            identities = [(route.provider, route.model,
                           tuple(route.provider_preferences.order))
                          for route in self.routes]
            if len(identities) != len(set(identities)):
                raise ValueError("LLM-Routen dürfen nicht doppelt vorkommen")
        return self

OPENROUTER_PARAMETER_KEYS = {
    "temperature", "max_tokens", "top_p", "top_k", "frequency_penalty",
    "presence_penalty", "repetition_penalty", "seed", "stop", "logit_bias",
    "min_p", "top_a", "reasoning",
}

REASONING_EFFORTS = {"minimal", "low", "medium", "high"}

def checked_parameters(value: dict[str, Any], message: str) -> dict[str, Any]:
    """Reject unknown request keys and validate the closed ``reasoning`` block.

    ``reasoning`` limits hidden reasoning of capable models with exactly one of
    ``effort`` or ``max_tokens`` and an optional ``exclude``.  Disabling it via
    ``enabled`` is not offered: providers may reject such requests permanently.
    """
    unknown = set(value) - OPENROUTER_PARAMETER_KEYS
    if unknown:
        raise ValueError(f"{message}: {sorted(unknown)}")
    reasoning = value.get("reasoning")
    if reasoning is None:
        return value
    if not isinstance(reasoning, dict) or set(reasoning) - {"effort", "max_tokens", "exclude"}:
        raise ValueError("reasoning erlaubt ausschließlich effort, max_tokens und exclude")
    if ("effort" in reasoning) == ("max_tokens" in reasoning):
        raise ValueError("reasoning benötigt genau eines von effort oder max_tokens")
    if "effort" in reasoning and reasoning["effort"] not in REASONING_EFFORTS:
        raise ValueError(f"reasoning.effort muss einer von {sorted(REASONING_EFFORTS)} sein")
    tokens = reasoning.get("max_tokens")
    if "max_tokens" in reasoning and (type(tokens) is not int or not 1 <= tokens <= 32000):
        raise ValueError("reasoning.max_tokens muss eine Ganzzahl von 1 bis 32000 sein")
    if "exclude" in reasoning and type(reasoning["exclude"]) is not bool:
        raise ValueError("reasoning.exclude muss ein Wahrheitswert sein")
    return value

class OpenRouterProviderPreferences(ConfigModel):
    """The closed subset of OpenRouter provider routing that Mailhelp accepts."""

    order: list[str] = Field(default_factory=list)
    allow_fallbacks: bool = True
    require_parameters: bool = False
    data_collection: Literal["allow", "deny"] | None = None
    sort: Literal["price", "throughput", "latency"] | None = None
    ignore: list[str] = Field(default_factory=list)

    @field_validator("order", "ignore")
    @classmethod
    def provider_names(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("Providernamen müssen nicht leer und eindeutig sein")
        return value

class LlmRoute(ConfigModel):
    provider: Literal["openrouter"]
    model: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    provider_preferences: OpenRouterProviderPreferences = Field(
        default_factory=OpenRouterProviderPreferences
    )
    supports_json_schema: bool = True

    @field_validator("model")
    @classmethod
    def configured_model(cls, value: str) -> str:
        if value.startswith("<"):
            raise ValueError("Modell ist nicht eingerichtet")
        return value

    @field_validator("parameters")
    @classmethod
    def safe_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        return checked_parameters(value, "Unbekannte oder reservierte Request-Schlüssel")

class OutputTokenRetry(ConfigModel):
    """A deliberately smaller, stage-specific request after truncated output."""
    system_prompt: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Only proposal revisions need to select writable fields.  Other stages can
    # use the generic prompt/parameter fallback without inventing revision data.
    change_fields: list[str] | None = Field(default=None, min_length=1)

    @field_validator("parameters")
    @classmethod
    def safe_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        return checked_parameters(value, "Unbekannte Retry-Parameter")

# Context window of the experimental local mode. It matches the instance that
# is preloaded on the Ollama server; any other value makes Ollama reload the
# model, which takes several minutes for large models.
LOCAL_NUM_CTX = 65536

class OllamaPromptSettings(ConfigModel):
    """Model of the experimental local mode; replaces every OpenRouter route."""

    model: str = Field(min_length=1, max_length=200, pattern=r"^[^<>\s]+$")
    num_ctx: int = Field(default=LOCAL_NUM_CTX, ge=2048, le=262144)
    num_thread: int | None = Field(default=None, ge=1, le=1024)
    think: bool | None = None

# Steps a prompts.yaml from an earlier release may lack; the feature is then off.
OPTIONAL_PROMPT_STEPS = frozenset({
    "vision_ocr", "draft_reply", "activity_relevance", "activity_events", "diagnostic_test", "open_proposal_match",
    "settings_help", "decision_rule_learning"})

class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    defaults: dict[str, Any]
    prompts: dict[str, PromptStep]
    # Development-only profiles are applied to the effective prompts before dataset generation.
    # Unused profiles cannot change the fingerprint of a production analysis.
    demo_profiles: dict[str, dict[str, str]] = Field(default_factory=dict, exclude=True)
    ollama: OllamaPromptSettings | None = None
    suspicious_link_hosts: list[Annotated[str, Field(min_length=1, max_length=253)]] = Field(default_factory=list)
    suspicious_link_phrases: list[Annotated[str, Field(min_length=1, max_length=250)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_steps(self) -> PromptConfig:
        required = {"relevance", "summary", "action_router", "task_extraction",
                    "event_extraction", "mail_question_resolution", "telegram_answer_interpretation",
                    "telegram_answer_clarification", "proposal_revision", "learning_classification",
                    "learning_abstraction", "calendar_duplicate"}
        if not required <= set(self.prompts) <= required | OPTIONAL_PROMPT_STEPS:
            raise ValueError("prompts enthält nicht genau die erforderlichen Schritte")
        default_model = self.defaults.get("model")
        for name, step in self.prompts.items():
            if step.model_route is not None:
                target = self.prompts.get(step.model_route)
                if target is None or target.model_route is not None:
                    raise ValueError(f"prompts.{name}.model_route verweist auf keinen Schritt mit eigenem Modell")
            elif step.routes is None and not step.model and not default_model:
                raise ValueError(f"prompts.{name} benötigt ein Primärmodell")
        return self

    def resolved(self, step: str) -> tuple[str, dict[str, Any], str]:
        item = self.prompts[step]
        if item.model_route is not None:
            routed, inherited, _prompt = self.resolved(item.model_route)
            return routed, _deep_merge(inherited, item.parameters), item.system_prompt
        model = item.model or self.defaults.get("model")
        if not isinstance(model, str) or not model or model.startswith("<"):
            raise ValueError(f"prompts.{step}.model ist nicht eingerichtet")
        parameters = _deep_merge(self.defaults.get("parameters", {}), item.parameters)
        forbidden = {"model", "messages", "response_format"} & parameters.keys()
        if forbidden:
            raise ValueError(f"Reservierte OpenRouter-Parameter: {sorted(forbidden)}")
        return model, parameters, item.system_prompt

    def resolved_routes(self, step: str) -> tuple[list[LlmRoute], str, int]:
        """Return an ordered, validated strategy (primary route first)."""
        item = self.prompts[step]
        if item.model_route is not None:
            routes, _prompt, _retries = self.resolved_routes(item.model_route)
            return ([route.model_copy(update={"parameters": _deep_merge(route.parameters, item.parameters)})
                     for route in routes], item.system_prompt, item.provider_retries)
        if item.routes is not None:
            return item.routes, item.system_prompt, item.provider_retries
        model, parameters, prompt = self.resolved(step)
        checked_parameters(parameters, "Unbekannte oder reservierte Request-Schlüssel")
        return [LlmRoute(provider="openrouter", model=model, parameters=parameters,
                         provider_preferences=(item.provider_preferences
                                               or OpenRouterProviderPreferences()))
                ], prompt, item.provider_retries

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        nested = isinstance(value, dict) and isinstance(result.get(key), dict)
        result[key] = _deep_merge(result[key], value) if nested else value
    return result
