"""Simulated analyzer, engine and mailbox for re-analysis tests (5.1); synthetic data only."""
from __future__ import annotations

from mailhelp.domain.extraction import ActionRoute, ExtractedTask, TaskExtraction
from mailhelp.domain.proposal import ProposalStatus
from mailhelp.proposals.proposal_reconciliation import ProposalReconciliationService
from tests.scenarios.web_scenario import proposal

DONE_STEPS = dict(preparation="completed", relevance="completed", summary="completed",
                  action_detection="completed", action_router="completed", task_extraction="completed",
                  event_extraction="skipped", normalization="completed", proposal_building="completed",
                  duplicate_precheck="completed", completion="completed")


def task(title: str) -> ExtractedTask:
    return ExtractedTask(title=title, description="", evidence=f"Bitte {title} bis Freitag.",
                         responsibility="user", certainty="certain", classification="new")


class ReanalysisAnalyzer:
    """Finds the given task titles; every call is recorded."""

    def __init__(self, *titles: str):
        self.titles, self.calls = titles, []

    def action_route(self, mail):
        self.calls.append("route")
        state = "task" if self.titles else "none"
        return "route", ActionRoute(action_state=state, task_count=len(self.titles), event_count=0, reason="x")

    def extract_tasks(self, mail, *, expected_count):
        self.calls.append("tasks")
        return "tasks", TaskExtraction(tasks=[task(title) for title in self.titles])


class Precheck:
    def check_proposal(self, item, mail_context=None):
        return item


class ReanalysisEngine:
    """The orchestrator parts a re-analysis uses, with real proposal reconciliation."""

    max_bytes, user_timezone = 1_000_000, "Europe/Berlin"

    def __init__(self, store, analyzer, number: int):
        self.analyzer, self.number = analyzer, number
        self.precheck, self.reconciliation = Precheck(), ProposalReconciliationService(store)

    def own_addresses(self, account_id):
        return frozenset()

    def build_proposals(self, state):
        tasks = state.task_extraction.tasks if state.task_extraction else []
        return [proposal(self.number, f"neu{index}", title=item.title, evidence=item.evidence,
                         status=ProposalStatus.PENDING_CONFIRMATION) for index, item in enumerate(tasks)]
