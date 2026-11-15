"""Durable first-open events; device activation never replays the existing backlog."""
from datetime import UTC, datetime

from ..models import MailState
from ..review.archive import HistorySnapshot
from ..storage import CorruptState


class PushDecisionEvents:
    def __init__(self, store, clock, current):
        self.store, self.clock = store, clock
        saved = store.load('push-decision-events')
        self.records = saved if saved is not None else {
            reference: {'version': version, 'source': 'system',
                        'appeared_at': datetime.min.replace(tzinfo=UTC).isoformat()}
            for reference, version in current}
        if saved is None:
            store.save('push-decision-events', self.records)

    def observe(self, reference, version):
        with self.store.locked():
            old = self.records.get(reference)
            if old is not None and old['version'] >= version:
                return old
            mail_id, proposal_id = reference.split(':', 1)
            try:
                history = self.store.peek_model('history-' + mail_id, HistorySnapshot, HistorySnapshot())
            except CorruptState:
                history = HistorySnapshot()
            events = [event for event in history.events if event.version == version
                      and event.proposal_id == proposal_id and event.kind == 'state']
            appeared = events[0].at if events else self.clock()
            if proposal_id == 'relevance':
                mail = self.store.peek_model('mail-' + mail_id, MailState)
                if mail is not None:
                    appeared = mail.updated_at
            record = {'version': version, 'source': events[0].source if events else 'system',
                      'appeared_at': appeared.isoformat()}
            self.records[reference] = record
            self.store.save('push-decision-events', self.records)
            return record

    def eligible(self, reference, version, push, device):
        record = self.observe(reference, version)
        activated = push.status(device.partition(':')[0])['activated_at']
        return (record['version'] == version and record['source'] == 'system' and activated is not None
                and datetime.fromisoformat(record['appeared_at']) > datetime.fromisoformat(activated))
