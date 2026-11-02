"""Non-secret call audit: one JSON line per provider or media action.

Never record API keys, full prompt or narration text; only models, versions,
hashes, sizes and output names, so the log can stay with the order files.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

LOG='AUDIT_LOG.jsonl'

def record(project,action,**detail):
    entry={'at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'action':action,**detail}
    p=Path(project).resolve()/LOG
    with p.open('a',encoding='utf-8') as f:f.write(json.dumps(entry,ensure_ascii=False)+'\n')
    return p
