"""Compare Groq and Ollama extraction on synthetic text (six live API calls)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import json
import time
from app.settings import get_settings
from app.llm.provider import create_adapter
from app.llm.extract import BatchInput, FragmentInput, extract_batch
s=get_settings()
b=BatchInput('latency-test',(FragmentInput('f1','synthetic:1','Activity CIV-101: concrete placement in Area A reached 50% on 2026-10-12.'),))
for provider in ('groq','ollama'):
    adapter=create_adapter(s,provider=provider,timeout=45)
    for i in range(3):
        start=time.monotonic()
        try:
            result=extract_batch(b,adapter.chat)
            print(json.dumps({'provider':provider,'model':result.metadata.model,'trial':i+1,'elapsed_ms':round((time.monotonic()-start)*1000),'observations':len(result.observations),'errors':result.errors}),flush=True)
        except Exception as e:
            print(json.dumps({'provider':provider,'trial':i+1,'elapsed_ms':round((time.monotonic()-start)*1000),'error_type':type(e).__name__}),flush=True)
            break
