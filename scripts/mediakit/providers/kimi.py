"""Kimi (Moonshot) chat adapter: official endpoints only, injectable transport."""
import json
import os

from ..audit import record
from ..core import new_output, stage
from ..runtime import w
from . import base

OFFICIAL_BASES=('https://api.moonshot.ai/v1','https://api.moonshot.cn/v1')

class KimiClient:
    """One official Kimi chat endpoint; transport is injectable for tests."""

    def __init__(self,api_key=None,model=None,base_url=None,transport=None):
        self.api_key=api_key if api_key is not None else os.environ.get('MOONSHOT_API_KEY')
        self.model=model or os.environ.get('MOONSHOT_MODEL','kimi-k3')
        self.base_url=(base_url or os.environ.get('MOONSHOT_BASE_URL','https://api.moonshot.ai/v1')).rstrip('/')
        self.transport=transport or base.request

    def draft(self,text):
        if not self.api_key: raise ValueError('未配置 MOONSHOT_API_KEY；使用写作包复制到 Kimi')
        if self.base_url not in OFFICIAL_BASES:
            raise ValueError('内置适配仅支持官方 Kimi 地址；其他服务按用户确认的接口另行适配')
        payload={'model':self.model,'messages':[{'role':'user','content':text}], 'stream':False}
        with self.transport(self.base_url+'/chat/completions',{'Authorization':'Bearer '+self.api_key},payload) as r: data=json.load(r)
        result=data['choices'][0]
        if result.get('finish_reason') not in ('stop',None): raise ValueError('文案未完整返回，请检查输出限制')
        body=result['content']
        if not body: raise ValueError('未返回旁白正文')
        return body

def kimi(project,prompt,out,authorized,_request=None):
    stage(project,{2}); dest=new_output(project,out)
    source=w.inside(project,prompt)
    text=source.read_text(encoding='utf-8')
    if not authorized: raise ValueError('需当前任务明确授权文字 API 调用')
    client=KimiClient(transport=_request)
    body=client.draft(text)
    dest.write_text(body,encoding='utf-8')
    record(project,'kimi',model=client.model,prompt_sha256=w.sha(source),out=dest.name,chars=len(body))
    return dest
