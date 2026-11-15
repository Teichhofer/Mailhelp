"""Action detection, extraction, proposal building and notification of one mail (7.0, R5)."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..domain.extraction import ActionRoute
from ..domain.mail import MailState
from ..domain.processing import ProcessingStage, ProposalNotification
from ..domain.proposal import Proposal, ProposalStatus
from . import mail_pipeline as mail_pipeline_module

if TYPE_CHECKING:
    from .mail_pipeline import MailPipeline, ProcessingRun


def _detect_actions(pipeline: MailPipeline, run: ProcessingRun) -> None:
    state, name = run.state, run.name
    run.stage = ProcessingStage.ACTION_DETECTION
    if state.steps.action_detection not in {"pending", "failed"}:
        return
    if state.steps.action_router in {"pending", "failed"}:
        run.stage = ProcessingStage.ACTION_ROUTER
        call, route = pipeline.o.analyzer.action_route(mail_pipeline_module._with_perspective(state))
        state.action_route = route
        state.action_router_call_id = call
        state.llm_call_ids.append(call)
        state.steps.action_router = "completed"
        pipeline.o.save(name, state)
    else:
        assert state.action_route is not None
        route = state.action_route
    assert state.action_router_call_id is not None
    # Extraction is read-only. A candidate counted by an unclear
    # route should therefore become a reviewable proposal too.
    wants_tasks = (route.action_state in {"task", "task_and_event"}
                   or route.task_count > 0)
    # An event candidate must not disappear merely because the
    # router is unsure whether the message is an invitation.  The
    # extractor and proposal boundary preserve that uncertainty,
    # while Telegram still receives the detected appointment.
    has_cal_events = bool(mail_pipeline_module._prepared(state).calendar_events)
    wants_llm_events = (route.action_state in {"event", "task_and_event"}
                        or route.event_count > 0)
    wants_events = wants_llm_events or has_cal_events
    pipeline._extract(run, route, wants_tasks, wants_llm_events)
    pipeline._build(run, wants_tasks or wants_events)
    state.proposal_notifications = [
        ProposalNotification(
            proposal_id=item.id,
            proposal_version=item.version,
            status="completed" if item.status == ProposalStatus.ALREADY_EXISTS else "pending",
        )
        for item in state.proposals
    ]
    state.steps.action_detection = "completed"
    pipeline.o.save(name, state)
    pipeline.o.logger.event("INFO", "orchestrator", "actions_completed", mail_id=state.id,
                      action_state=route.action_state,
                      proposal_ids=[item.id for item in state.proposals])


def _extract(pipeline: MailPipeline, run: ProcessingRun, route: ActionRoute, wants_tasks: bool, wants_llm_events: bool) -> None:
    state, name = run.state, run.name
    if wants_tasks and state.steps.task_extraction in {"pending", "failed"}:
        run.stage = ProcessingStage.TASK_EXTRACTION
        call, extraction = pipeline.o.analyzer.extract_tasks(
            mail_pipeline_module._with_perspective(state), expected_count=route.task_count)
        state.task_extraction = extraction
        state.llm_call_ids.append(call)
        state.steps.task_extraction = "completed"
        pipeline.o.save(name, state)
        pipeline.o.record_count_conflict(name, state, "task", route.task_count,
                                    len(extraction.tasks),
                                    state.action_router_call_id, call)
    if not wants_tasks:
        state.steps.task_extraction = "skipped"
        pipeline.o.save(name, state)
    if wants_llm_events and state.steps.event_extraction in {"pending", "failed"}:
        run.stage = ProcessingStage.EVENT_EXTRACTION
        call, events = pipeline.o.analyzer.extract_events(
            mail_pipeline_module._with_perspective(state), expected_count=route.event_count)
        state.event_extraction = events
        state.llm_call_ids.append(call)
        state.steps.event_extraction = "completed"
        pipeline.o.save(name, state)
        pipeline.o.record_count_conflict(name, state, "event", route.event_count,
                                    len(events.events),
                                    state.action_router_call_id, call)
    elif not wants_llm_events:
        state.steps.event_extraction = "skipped"
        pipeline.o.save(name, state)


def _build(pipeline: MailPipeline, run: ProcessingRun, wanted: bool) -> None:
    state, name = run.state, run.name
    run.stage = ProcessingStage.NORMALIZATION
    if state.steps.normalization in {"pending", "failed"}:
        state.normalized_proposals = pipeline.o.build_proposals(state) if wanted else []
        state.steps.normalization = "completed"
        pipeline.o.save(name, state)
    run.stage = ProcessingStage.PROPOSAL_BUILDING
    if state.steps.proposal_building in {"pending", "failed"}:
        state.proposals = [Proposal.model_validate(item.model_dump(mode="json"))
                           for item in state.normalized_proposals]
        state.steps.proposal_building = "completed"
        pipeline.o.save(name, state)
    pipeline.o.questions.resolve(name, state)
    run.stage = ProcessingStage.DUPLICATE_PRECHECK
    if state.steps.duplicate_precheck in {"pending", "failed"}:
        state.proposals = [
            pipeline.o.precheck.check_proposal(p, mail_context=state.mail)
            for p in state.proposals
        ]
        state.steps.duplicate_precheck = "completed"
        pipeline.o.save(name, state)
    limit = (state.proposal_policy["max_semantic_candidates"] if state.proposal_policy is not None else None)
    state.proposals = [pipeline.o.reconciliation.reconcile(p, limit) for p in state.proposals]
    state.proposals = [pipeline.o.reconciliation.required(p.source_mail_id, p.id)
                       for p in state.proposals]
    pipeline.o.save(name, state)
    events = [p for p in state.proposals if p.kind == "event"]
    for task in (p for p in state.proposals if p.kind == "task"):
        if len(events) == 1 and re.search(r"teilnahme|zurückmeld|anmeld|zusag|absag", task.title.casefold()):
            pipeline.o.reconciliation.relate(task, events[0])


def _notify_proposals(pipeline: MailPipeline, run: ProcessingRun) -> None:
    name = run.name
    run.stage = ProcessingStage.PROPOSAL_NOTIFICATION
    if run.state.steps.proposal_notification not in {"pending", "sending"}:
        return
    state = run.state
    first_attempt = state.steps.proposal_notification == "pending"
    if first_attempt:
        state.steps.proposal_notification = "sending"
        pipeline.o.save(name, state)
    if (first_attempt and state.action_route is not None
            and state.action_route.action_state == "unclear"):
        pipeline.o.notifier.send(
            pipeline.o.chat_id,
            "Mögliche Aufgabe oder möglicher Termin benötigt fachliche Klärung: "
            + state.action_route.reason,
        )
    for conflict in state.extraction_count_conflicts:
        if conflict.notification_marked_at is not None or conflict.actual_count > 0:
            continue
        # Mark before delivery: an uncertain Telegram result must
        # never lead to an automatic duplicate after restart.
        conflict.notification_marked_at = datetime.now(UTC)
        pipeline.o.save(name, state)
        pipeline.o.notifier.send(
            pipeline.o.chat_id,
            "Die Mail enthält möglicherweise Handlungsbedarf, aber es konnte "
            "kein Vorschlag gewonnen werden. Bitte die Mail manuell prüfen.",
        )
    for proposal, notification in zip(state.proposals, state.proposal_notifications, strict=True):
        if notification.status != "pending":
            continue
        if proposal.status == ProposalStatus.MERGED:
            # The alias belongs to this mail; delivery belongs to the canonical
            # revision. Mark first so an uncertain delivery is never repeated.
            notification.status = "sending"
            pipeline.o.save(name, state)
            assert proposal.canonical_ref is not None
            canonical = pipeline.o.reconciliation.resolve(proposal.canonical_ref)
            if canonical is None:
                raise ValueError("Zusammengeführter Vorschlag fehlt")
            pipeline.o.notifier.send_proposal(canonical)
            notification.status = "completed"
            pipeline.o.save(name, state)
            continue
        dedicated_delivery = bool(getattr(
            pipeline.o.notifier, "manages_proposal_delivery", False))
        if not dedicated_delivery:
            notification.status = "sending"
            pipeline.o.save(name, state)
        pipeline.o.notifier.send_proposal(proposal)
        # ProposalDeliveryService owns the sending/completed
        # transition.  Reload its authoritative projection so a
        # later orchestrator save cannot overwrite that state.
        state = run.state = MailState.model_validate(pipeline.o.store.load(name))
        current = next(item for item in state.proposal_notifications
                       if (item.proposal_id, item.proposal_version) ==
                       (proposal.id, proposal.version))
        # Compatibility for simple notifier ports: the
        # dedicated delivery service has already completed its
        # own transition, while a synchronous legacy notifier
        # reports success by returning normally.
        if current.status == "pending" or (
                not dedicated_delivery and current.status == "sending"):
            current.status = "completed"
            pipeline.o.save(name, state)
    state.steps.proposal_notification = "completed"
    pipeline.o.save(name, state)
