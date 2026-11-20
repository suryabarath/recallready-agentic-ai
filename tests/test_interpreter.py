"""Real SDK + fake HTTP transport; no external calls or model accuracy claims."""
from copy import deepcopy
import json
from dataclasses import replace
from pathlib import Path

import httpx
from openai import OpenAI
import pytest

from interpreter import Budget, InterpretationError, interpret, main
from source import GROUP_A, Source
from reviews import load_reviews


EXAMPLES = json.loads((Path(__file__).resolve().parents[1] / 'docs/task02b_group_a_review_examples.json').read_text())


def proposal(index=0):
    facts = EXAMPLES[index]['facts']
    return dict(identifiers=[{k: i[k] for k in ('kind', 'value', 'evidence_ids')}
                             for i in facts['identifiers']], uncertainties=facts['uncertainties'])


def client_for(outputs, seen):
    def respond(request):
        seen.append(json.loads(request.content))
        item = outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        text, status = item
        return httpx.Response(200, json=dict(id='resp_test', object='response', created_at=1,
            model='gpt-6-luna', status=status,
            output=[dict(type='message', id='msg_test', role='assistant', status='completed',
                         content=[dict(type='output_text', text=text, annotations=[])])],
            usage=dict(input_tokens=4000, output_tokens=2000, total_tokens=6000,
                       input_tokens_details=dict(cached_tokens=0),
                       output_tokens_details=dict(reasoning_tokens=1500))))
    return OpenAI(api_key='offline-test-key', max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(respond)))


def run(client, budget, index=0):
    source = Source()
    return interpret(source, client, budget, recall_number=GROUP_A[index], snapshot_id=source.snapshot_id)


@pytest.mark.parametrize('index', range(6), ids=GROUP_A)
def test_six_end_to_end_offline_sdk_flows(tmp_path, index):
    seen = []
    budget = Budget(tmp_path/'usage.sqlite')
    with client_for([(json.dumps(proposal(index)), 'completed')], seen) as client:
        assert run(client, budget, index).model_dump() == EXAMPLES[index]
    request = seen[0]
    assert request['store'] is False
    assert request['reasoning'] == {'effort': 'low'}
    assert request['service_tier'] == 'default'
    assert 'tools' not in request
    assert len(json.loads(request['input'])) == 4
    assert 'product_label_derived' not in request['input']
    assert budget.summary()[0]['accounted_usd'] == 0.0014
    assert budget.summary()[0]['reasoning_tokens'] == 1500


def test_one_structural_repair_accounts_both_calls(tmp_path):
    seen=[]; budget=Budget(tmp_path/'usage.sqlite')
    with client_for([('{}', 'completed'), (json.dumps(proposal()), 'completed')], seen) as client:
        run(client, budget)
    assert len(seen) == 2
    assert len(budget.summary()) == 2
    assert sum(r['accounted_usd'] for r in budget.summary()) == 0.0028


def test_second_bad_shape_stops(tmp_path):
    seen=[]; budget=Budget(tmp_path/'usage.sqlite')
    with client_for([('{}', 'completed'), ('{}', 'completed')], seen) as client:
        with pytest.raises(InterpretationError, match='one repair'):
            run(client, budget)
    assert len(seen) == 2


@pytest.mark.parametrize('alter', ['zero', 'citation', 'kind'])
def test_semantic_failures_never_retry(tmp_path, alter):
    seen=[]; payload=deepcopy(proposal(1))
    if alter == 'zero':
        payload['identifiers'][0]['value'] = '60723'
    elif alter == 'citation':
        payload['identifiers'][0]['evidence_ids'] = ['EV-INVENTED']
    else:
        payload['identifiers'][0]['kind'] = 'expiry_date'
    with client_for([(json.dumps(payload), 'completed')], seen) as client:
        with pytest.raises(InterpretationError):
            run(client, Budget(tmp_path/'usage.sqlite'), 1)
    assert len(seen) == 1


@pytest.mark.parametrize("index,value", [
    (2, "06-04-24 08/04/2024"), (4, "04162026 BC 6937218914734")
])
def test_ambiguous_model_lot_stops_without_paid_repair(tmp_path, index, value):
    seen=[]; payload=deepcopy(proposal(index))
    payload['identifiers'][0]['kind'] = 'lot'
    payload['identifiers'][0]['value'] = value
    with client_for([(json.dumps(payload), 'completed')], seen) as client:
        with pytest.raises(InterpretationError, match='human review'):
            run(client, Budget(tmp_path/'usage.sqlite'), index)
    assert len(seen) == 1


def test_incomplete_usage_is_charged_without_retry(tmp_path):
    seen=[]; budget=Budget(tmp_path/'usage.sqlite')
    with client_for([('', 'incomplete')], seen) as client:
        with pytest.raises(InterpretationError, match='Incomplete'):
            run(client, budget)
    assert len(seen) == 1
    assert budget.summary()[0]['accounted_usd'] == 0.0014


def test_timeout_keeps_reservation_and_stops(tmp_path):
    seen=[]; budget=Budget(tmp_path/'usage.sqlite')
    with client_for([httpx.ReadTimeout('offline timeout')], seen) as client:
        with pytest.raises(InterpretationError, match='reservation retained'):
            run(client, budget)
    assert len(seen) == 1
    assert budget.summary()[0]['state'] == 'reserved'


def test_persisted_budget_prevents_request(tmp_path):
    path=tmp_path/'usage.sqlite'
    first=Budget(path, 100)
    first.reserve(100)
    seen=[]
    with client_for([], seen) as client:
        with pytest.raises(InterpretationError, match='budget exhausted'):
            run(client, Budget(path, 100))
    assert seen == []


@pytest.mark.parametrize('amount', [0, -1, 1_000_001, True])
def test_invalid_budget_rejected(tmp_path, amount):
    with pytest.raises(ValueError):
        Budget(tmp_path/'usage.sqlite', amount)


def test_cli_requires_explicit_paid_flag():
    with pytest.raises(SystemExit) as exc:
        main(['--recall', GROUP_A[0]])
    assert exc.value.code == 2


def test_missing_key_blocks_cli(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with pytest.raises(SystemExit) as exc:
        main(['--recall', GROUP_A[0], '--allow-paid-call'])
    assert exc.value.code == 2


REVIEW_PATH = Path(__file__).resolve().parents[1] / 'docs/a1_member1_lot_approval.json'


@pytest.mark.parametrize('kind', ['other', 'lot'])
def test_human_review_applied_after_model_with_original_observations(tmp_path, kind):
    seen = []; s = Source(); payload = deepcopy(proposal(4))
    payload['identifiers'][0]['kind'] = kind
    before = deepcopy(payload)
    approvals = load_reviews(REVIEW_PATH)
    with client_for([(json.dumps(payload), 'completed')], seen) as client:
        result = interpret(s, client, Budget(tmp_path/'usage.sqlite'), recall_number=GROUP_A[4],
                           snapshot_id=s.snapshot_id, approved_lots=approvals)
    assert result.facts.identifiers[0].kind == 'lot'
    assert result.facts.identifiers[0].value == approvals[0].value
    assert result.source_fields.code_info.original_text == approvals[0].original_text
    assert result.facts.uncertainties[0] == 'Model observation before human review: ' + before['uncertainties'][0]
    assert 'Human review by Member 1' in result.facts.uncertainties[-1]
    assert 'Member 1' not in json.dumps(seen)
    assert 'Human review' not in json.dumps(seen)
    assert payload == before
    assert len(seen) == 1


@pytest.mark.parametrize('field,value', [
    ('recall_number', GROUP_A[2]), ('event_id', 'OTHER'), ('snapshot_id', 'OTHER'),
    ('evidence_id', 'EV-INVENTED'), ('original_text', 'altered source'),
    ('value', '04162026'), ('reviewer', ''),
])
def test_stale_or_altered_review_blocks_before_request(tmp_path, field, value):
    seen = []; s = Source(); budget = Budget(tmp_path/'usage.sqlite')
    approval = replace(load_reviews(REVIEW_PATH)[0], **{field:value})
    with client_for([], seen) as client:
        with pytest.raises(InterpretationError, match='Invalid human review; no request sent'):
            interpret(s, client, budget, recall_number=GROUP_A[4], snapshot_id=s.snapshot_id,
                      approved_lots=(approval,))
    assert seen == []
    assert budget.summary() == []


@pytest.mark.parametrize('alter', ['missing', 'partial', 'citation', 'expiry'])
def test_review_cannot_insert_codes_or_bypass_model_source_errors(tmp_path, alter):
    seen=[]; s=Source(); payload=deepcopy(proposal(4))
    if alter == 'missing':
        payload['identifiers'] = []
    elif alter == 'partial':
        payload['identifiers'][0]['value'] = '04162026'
    elif alter == 'citation':
        payload['identifiers'][0]['evidence_ids'] = ['EV-INVENTED']
    else:
        payload['identifiers'][0]['kind'] = 'expiry_date'
    budget=Budget(tmp_path/'usage.sqlite')
    with client_for([(json.dumps(payload), 'completed')], seen) as client:
        with pytest.raises(InterpretationError):
            interpret(s, client, budget, recall_number=GROUP_A[4], snapshot_id=s.snapshot_id,
                      approved_lots=load_reviews(REVIEW_PATH))
    assert len(seen) == 1
    assert len(budget.summary()) == 1


def test_live_cli_reads_explicit_review_file_offline(tmp_path, monkeypatch, capsys):
    seen=[]; client=client_for([(json.dumps(proposal(4)), 'completed')], seen)
    monkeypatch.setenv('OPENAI_API_KEY','offline-test-key')
    monkeypatch.setattr('interpreter.OpenAI', lambda **kwargs: client)
    assert main(['--recall', GROUP_A[4], '--allow-paid-call', '--human-review-file', str(REVIEW_PATH),
                 '--ledger', str(tmp_path/'usage.sqlite')]) == 0
    output=capsys.readouterr().out
    result,_ = json.JSONDecoder().raw_decode(output)
    assert result['facts']['identifiers'][0]['kind'] == 'lot'
    assert len(seen) == 1


@pytest.mark.parametrize('content', ['not json', '{"approved_lots": [{"value": "x"}]}'])
def test_invalid_review_cli_fails_before_ledger_creation(tmp_path, monkeypatch, content):
    path=tmp_path/'review.json'; path.write_text(content)
    ledger=tmp_path/'usage.sqlite'
    monkeypatch.setenv('OPENAI_API_KEY','offline-test-key')
    with pytest.raises(SystemExit) as exc:
        main(['--recall',GROUP_A[4], '--allow-paid-call', '--human-review-file',str(path),
              '--ledger',str(ledger)])
    assert exc.value.code == 2
    assert not ledger.exists()
