from io import BytesIO
import json
from types import SimpleNamespace
from urllib.error import HTTPError

from pydantic import SecretStr

from app.llm import hosted
from evaluation.source_unit_schema_probe import run


def test_diagnostic_redacts_error_fields_drops_failed_generation_and_restores_transport(tmp_path,monkeypatch):
    import evaluation.source_unit_schema_probe as probe
    settings=SimpleNamespace(groq_api_key=SecretStr('original-secret'),groq_api_key_1=None,
        groq_api_key_2=SecretStr('probe-secret'),openrouter_api_key=None,ollama_api_key=None)
    monkeypatch.setattr(probe,'get_settings',lambda:settings)
    def failed(*args,**kwargs):
        data=json.dumps({'error':{'message':'probe-secret was rejected','code':'json_validate_failed',
                                 'failed_generation':'private generated response must not be exported'}}).encode()
        raise HTTPError('https://api.groq.com',400,'bad',{},BytesIO(data))
    monkeypatch.setattr(hosted,'urlopen',failed)
    calls=[]
    def request(provider,method,url,payload,timeout,headers):
        calls.append(payload)
        assert 'probe-secret' not in json.dumps(payload)
        try:
            hosted.urlopen(None)
        except HTTPError:
            return 400,{}
    monkeypatch.setattr(hosted,'request',request)
    schema=tmp_path/'schema.json'
    schema.write_text('{}')
    output=tmp_path/'capture'
    result=run(schema,output)
    assert len(calls)==1 and result['reserved_calls']==1
    assert result['sanitized_error']['message']=='[REDACTED] was rejected'
    assert 'failed_generation' not in result['sanitized_error']
    assert hosted.urlopen is failed
    rendered=''.join(p.read_text() for p in output.iterdir())
    assert 'probe-secret' not in rendered and 'private generated response' not in rendered
