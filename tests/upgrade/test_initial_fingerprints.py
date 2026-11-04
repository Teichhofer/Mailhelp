"""Adding the persisted backend selection must not invalidate existing cloud analyses."""
import hashlib
import json

from shared_application import settings
from shared_core import prompt_config

from mailhelp.llm.fingerprints import analysis_prompts, analysis_settings, config_fingerprint


def test_default_openrouter_keeps_the_pre_37_analysis_fingerprint(tmp_path):
    cfg,prompts=settings(tmp_path),prompt_config()
    previous=analysis_settings(cfg)
    previous.pop('llm',None)
    expected=hashlib.sha256(json.dumps([previous,analysis_prompts(prompts),[]],sort_keys=True).encode()).hexdigest()
    assert config_fingerprint(cfg,prompts,[])==expected
    cfg.llm.ollama_address='other-localhost:11434'
    assert config_fingerprint(cfg,prompts,[])==expected
    cfg.llm.provider='ollama'
    assert config_fingerprint(cfg,prompts,[])!=expected
