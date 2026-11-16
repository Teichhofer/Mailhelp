"""Repeated hints reuse unchanged records and refresh after local or external edits."""
from mailhelp.domain.mail import DisplayHeaders
from mailhelp.persistence.storage import JsonStore
from mailhelp.review.proposal_evaluation import collect_decided_proposals
from tests.fakes.factories import build_proposal
from tests.fakes.processing_retry import terminal


def test_evaluation_reads_unchanged_state_once_and_invalidates_changes(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        mail = terminal()
        proposal = build_proposal(source_mail_id=mail.id, id='p1', kind='task', status='rejected')
        mail_name, proposal_name = 'mail-' + mail.id, 'proposal-' + mail.id + '-p1'
        store.save(mail_name, mail.model_dump(mode='json'))
        store.save(proposal_name, proposal.model_dump(mode='json'))
        read = store._read
        reads = []
        def counted(name, *args, **kwargs):
            reads.append(name)
            return read(name, *args, **kwargs)
        monkeypatch.setattr(store, '_read', counted)
        assert collect_decided_proposals(store)[0].is_rejected
        assert proposal_name in reads and mail_name in reads
        reads.clear()
        assert collect_decided_proposals(store)[0].is_rejected
        assert reads == []
        proposal.reject_reason = 'not_for_me'
        store.save(proposal_name, proposal.model_dump(mode='json'))
        assert collect_decided_proposals(store)[0].reject_reason == 'not_for_me'
        assert reads == [proposal_name]
        reads.clear()
        mail.display_headers = DisplayHeaders(sender='Changed <changed@example.test>', subject='Synthetic')
        # An editor outside this process also changes the filesystem signature.
        (tmp_path / (mail_name + '.json')).write_text(mail.model_dump_json(), encoding='utf-8')
        assert collect_decided_proposals(store)[0].sender == 'Changed <changed@example.test>'
        assert reads == [mail_name]


def test_sender_hints_share_only_the_current_request_snapshot(tmp_path, monkeypatch):
    from mailhelp.review import proposal_evaluation as evaluation
    with JsonStore(tmp_path) as store:
        original = evaluation.sender_hints
        calls = []
        def measured(*args, **kwargs):
            calls.append(kwargs['min_proposals'])
            return original(*args, **kwargs)
        monkeypatch.setattr(evaluation, 'sender_hints', measured)
        cache = {}
        assert evaluation.sender_hint_for_sender(store, 'a@example.test', request_cache=cache) is None
        assert evaluation.sender_hint_for_sender(store, 'b@example.test', request_cache=cache) is None
        assert calls == [5]
        assert evaluation.sender_hint_for_sender(store, 'a@example.test', request_cache=cache,
                                                 min_proposals=6) is None
        assert calls == [5, 6]
        assert evaluation.sender_hint_for_sender(store, 'a@example.test', request_cache={}) is None
        assert calls == [5, 6, 5]
