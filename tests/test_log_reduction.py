"""Synthetic daily volume, independent failures and first full traceback."""
import json

from mailhelp.log_reduction import LogReduction
from mailhelp.logging import JsonlLogger


def test_routine_changes_heartbeat_verbose_and_slow_errors():
    reducer=LogReduction()
    def select(event, context=None, now=0, verbose=False, level='INFO'):
        return reducer.select(level, 'imap', event, context or {}, now, verbose)
    assert select('poll_started') is None
    assert select('request', {'status':200,'duration_ms':1000}) is None
    assert select('request', {'status':404}) is not None
    assert select('request', {'status':200,'duration_ms':1001}) is not None
    assert select('poll_completed') is not None
    assert select('poll_started', verbose=True) is not None
    assert select('messages_discovered', {'folder':'A','count':1}) is not None
    assert select('messages_discovered', {'folder':'A','count':1}, 3599) is None
    assert select('messages_discovered', {'folder':'A','count':1}, 3600) is not None
    assert select('messages_discovered', {'folder':'A','count':2}, 3601) is not None
    assert select('messages_discovered', {'folder':'B','count':1}) is not None


def test_repeated_errors_keep_first_trace_distinguish_and_bound_memory():
    reducer=LogReduction()
    ctx={'mail_id':'a','error':'failure','stacktrace':'trace A'}
    assert reducer.select('ERROR','module','failed',ctx,0,False)==('failed',ctx)
    for second in range(1,900):
        assert reducer.select('ERROR','module','failed',ctx,second,False) is None
    event, repeated=reducer.select('ERROR','module','failed',ctx,900,False)
    assert event=='repeated' and repeated['count']==901 and 'stacktrace' not in repeated
    assert reducer.select('ERROR','module','failed',{**ctx,'stacktrace':'trace B'},901,False)[0]=='failed'
    for i in range(4100):
        reducer.select('WARNING','module','failed',{'stacktrace':str(i)},0,False)
    assert len(reducer.seen)==4096


def test_idle_day_under_two_mb_and_no_secrets(tmp_path, monkeypatch):
    clock=[0]
    monkeypatch.setattr('mailhelp.logging.time.monotonic', lambda:clock[0])
    logger=JsonlLogger(tmp_path, secrets=['SYNTHETIC-SECRET'])
    for minute in range(24*60):
        clock[0]=minute*60
        logger.event('INFO','telegram','poll_started')
        logger.event('INFO','telegram','poll_completed', count=0)
        logger.event('INFO','web','request',status=200,duration_ms=10)
        for folder in range(20):
            logger.event('INFO','imap','messages_discovered',folder=str(folder),count=0)
        logger.event('ERROR','module','failed',error='SYNTHETIC-SECRET',stacktrace='safe trace')
    text=logger.app.read_text(encoding='utf-8')
    assert len(text.encode())<2_000_000 and 'SYNTHETIC-SECRET' not in text
    rows=[json.loads(line) for line in text.splitlines()]
    assert sum(r['event'] in {'failed','repeated'} for r in rows)<=120
    assert sum(r['event']=='messages_discovered' for r in rows)==20*24
