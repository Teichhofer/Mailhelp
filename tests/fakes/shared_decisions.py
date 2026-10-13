"""Shared synthetic fixtures and doubles; no test-module dependencies."""


from pathlib import Path

from mailhelp.decisions import load_decision_prompts

ROOT = Path(__file__).resolve().parents[2]

def prompts():
    return load_decision_prompts(ROOT / "decisions_prompts.yaml")

def answer(question, choice=None):
    if question["type"] == "noul":
        return {"type": "noul", "noul": 0.9}
    keys = (list(question["criteria"]) if question["type"] == "choice"
            else [str(index) for index in range(len(question["criteria"]))])
    selected = choice or keys[0]
    value = {"type": question["type"], "confidence": 1.0,
             "probabilities": {key: float(key == selected) for key in keys}}
    value["choice" if question["type"] == "choice" else "score"] = (
        selected if question["type"] == "choice" else float(selected))
    return value

def envelope(questions, choices=None):
    return {"id": "synthetic-decision", "model": "typesafe/jev-1.13-test",
            "provider": "TypeSafe", "usage": {"input_tokens": 20, "output_tokens": 0, "cost": 0.001},
            "answers": {name: answer(question, (choices or {}).get(name))
                        for name, question in questions.items()}}

def all_questions():
    return {"yes": {"type": "noul", "instructions": "I", "criteria": {"true": "T", "false": "F"}},
            "pick": {"type": "choice", "instructions": "I", "criteria": {"a": "A", "b": "B"}},
            "rate": {"type": "score", "instructions": "I", "criteria": ["Low", "High"]}}
