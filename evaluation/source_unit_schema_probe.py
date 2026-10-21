"""One-call, synthetic-only strict schema compatibility diagnostic.

Default mode reads no report or labels. Optional context uses only the fixed
Codex-authored DEV-04 synthetic case and a frozen instruction plan. Production admission is retained. Error-body
inspection is bounded and explicitly scoped to this dummy-schema request only;
the normal provider transport still discards provider error bodies.
"""
from hashlib import sha256
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError

from app.llm import hosted
from app.llm.metrics import capture_provider_metrics
from app.settings import get_settings
from evaluation.repeated_development import TrialBudget, write


def run(schema_path, output, synthetic_context_plan=None):
    settings = get_settings()
    key = settings.groq_api_key_2
    if not key:
        raise ValueError('Slot 2 unavailable')
    schema = json.loads(schema_path.read_text())
    secrets = [item.get_secret_value() for name in ('groq_api_key','groq_api_key_1','groq_api_key_2','openrouter_api_key','ollama_api_key')
               if (item := getattr(settings,name))]
    payload = dict(model='openai/gpt-oss-20b',messages=[
        dict(role='system',content='Compatibility probe. Return {"units":[{"unit_id":"u1","observations":[]}]}. No report facts are supplied.'),
        dict(role='user',content='Return one empty unit u1.')],
        temperature=0, max_completion_tokens=256, reasoning_effort='low', stream=False,
        response_format=dict(type='json_schema',json_schema=dict(name='response',strict=True,schema=schema)))
    assert not any(secret in json.dumps(payload) for secret in secrets)
    if synthetic_context_plan:
        from evaluation.source_units import source_units
        frozen=json.loads((synthetic_context_plan/'plan.json').read_text())
        if frozen['model'] != payload['model'] or frozen['key_slot'] != 2:
            raise ValueError('Unsupported diagnostic configuration')
        cases=json.loads(Path('evaluation/fixtures/paired-development-v2/inputs.json').read_text())
        case=next(c for c in cases if c['case_id']=='DEV-20261020-04')
        context=f"Trusted report date: {case['report_date']}\n[{case['case_id']} | synthetic:1]\n{case['text']}"
        payload['messages']=[dict(role='system',content=frozen['prompts']['source-units']),
            dict(role='user',content=json.dumps({'fragment_context':context,'source_units':source_units(case['text'])}))]
        payload['max_completion_tokens']=1536
        assert not any(secret in json.dumps(payload) for secret in secrets)
    limits=dict(calls=1,reserved_tokens=30000,list_price_usd=.005,wall_seconds=240,
                request_seconds=180,output_tokens_per_call=payload['max_completion_tokens'])
    budget=TrialBudget(limits,{'input':.075,'output':.30})
    timeout=budget.reserve(payload)
    output.mkdir(parents=True,exist_ok=False)
    write(output/'plan.json',dict(scope=__doc__,budget=limits,schema_sha256=sha256(schema_path.read_bytes()).hexdigest(),
          payload_sha256=sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),key_slot=2,retries=0))
    original=hosted.urlopen
    error_fields={}
    def inspected(request,**kwargs):
        try:
            return original(request,**kwargs)
        except HTTPError as error:
            try:
                value=json.loads(error.read(16384)).get('error',{})
                for name in ('type','code','param','message'):
                    text=value.get(name)
                    if isinstance(text,str):
                        for secret in secrets:
                            text=text.replace(secret,'[REDACTED]')
                        error_fields[name]=text[:1200]
            except (ValueError,AttributeError):
                error_fields['inspection']='non-JSON or oversized error; body not retained'
            raise
    metrics={}
    status=None
    response_checks={}
    error_type=None
    hosted.urlopen=inspected
    try:
        with capture_provider_metrics() as metrics:
            status,body=hosted.request('groq','POST','https://api.groq.com/openai/v1/chat/completions',
                payload,timeout,{'Authorization':'Bearer '+key.get_secret_value()})
            response_checks=dict(returned_expected_model=body.get('model')==payload['model'],
                                 completion_returned=bool(body.get('choices')))
            if status==200:
                try:
                    value=json.loads(body['choices'][0]['message']['content'])
                    from app.llm.openrouter import _matches_schema
                    response_checks['native_schema_valid']=_matches_schema(value,schema)
                except (ValueError,KeyError,IndexError,TypeError):
                    response_checks['native_schema_valid']=False
    except Exception as error:
        error_type=type(error).__name__
    finally:
        hosted.urlopen=original
    result=dict(status=status,sanitized_error=error_fields,response_checks=response_checks,
                error_type=error_type,provider_metrics=metrics,**budget.snapshot(),
                scope='One compatibility probe; no report quality score or automatic retry')
    write(output/'result.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--synthetic-context-plan',type=Path)
    args=parser.parse_args()
    run(args.schema,args.output,args.synthetic_context_plan)
