"""Doubao speech adapter: unidirectional TTS with injectable transport."""
import base64
import json
import os
import uuid

from ..audit import record
from ..core import new_outputs, stage, voice_selection, write_new
from ..runtime import w
from . import base

ENDPOINT='https://openspeech.bytedance.com/api/v3/tts/unidirectional'

def decode_tts(events):
    chunks=[]; ended=False; metadata=[]
    for e in events:
        if not isinstance(e,dict):raise ValueError('语音服务返回了非对象事件')
        code=e.get('code',0)
        if code not in (0,20000000): raise ValueError('语音服务返回错误码 '+str(code))
        if e.get('data'): chunks.append(base64.b64decode(e['data'],validate=True))
        if e.get('sentence'): metadata.append(e['sentence'])
        if code==20000000: ended=True
    data=b''.join(chunks)
    if not ended or not data: raise ValueError('语音流不完整或为空；不标记生成完成')
    return data,metadata

class DoubaoTTS:
    """One Doubao speech endpoint; both credential modes; injectable transport."""

    def __init__(self,api_key=None,app_id=None,access_key=None,resource_id=None,transport=None):
        self.api_key=api_key if api_key is not None else os.environ.get('DOUBAO_API_KEY')
        self.app_id=app_id if app_id is not None else os.environ.get('DOUBAO_APP_ID')
        self.access_key=access_key if access_key is not None else os.environ.get('DOUBAO_ACCESS_KEY')
        self.resource_id=resource_id or os.environ.get('DOUBAO_RESOURCE_ID','seed-tts-2.0')
        self.transport=transport or base.request

    def headers(self):
        h={'X-Api-Resource-Id':self.resource_id,'X-Api-Request-Id':str(uuid.uuid4())}
        if self.api_key:h['X-Api-Key']=self.api_key
        elif self.app_id and self.access_key:h.update({'X-Api-App-Id':self.app_id,'X-Api-Access-Key':self.access_key})
        else: raise ValueError('豆包配置缺失；本地配置密钥，不要贴到对话或仓库')
        return h

    def synthesize(self,text,context,voice,rate):
        payload={'user':{'uid':'wedding-video-wizard'},'req_params':{'text':text,'speaker':voice,
          'audio_params':{'format':'mp3','sample_rate':48000,'speech_rate':rate},
          'additions':json.dumps({'context_texts':[context],'enable_timestamp':True},ensure_ascii=False)}}
        with self.transport(ENDPOINT,self.headers(),payload) as r:
            events=[json.loads(line) for line in r if line.strip()]
        return decode_tts(events)

def tts(project,text_path,instructions,voice,rate,out,authorized,selection='VOICE_SELECTION.json',_request=None):
    state=stage(project,{4,5}); dest=new_outputs(project,out,['.timing.json'])
    if state['current_step']==5:voice_selection(project,state,text_path,instructions,voice,rate,selection)
    if dest.suffix.lower()!='.mp3': raise ValueError('此适配输出 MP3，请使用 .mp3 文件名')
    if not authorized: raise ValueError('需当前任务明确授权豆包 API 调用')
    text=w.inside(project,text_path).read_text(encoding='utf-8').strip()
    context=w.inside(project,instructions).read_text(encoding='utf-8').strip()
    if not text or not context or not -50<=rate<=100: raise ValueError('正文、情绪指导或语速无效')
    client=DoubaoTTS(transport=_request)
    audio,metadata=client.synthesize(text,context,voice,rate)
    dest.write_bytes(audio)
    write_new(dest.with_suffix('.timing.json'),json.dumps(metadata,ensure_ascii=False,indent=2))
    record(project,'tts',voice=voice,rate=rate,resource=client.resource_id,chars=len(text),out=dest.name)
    # Do not claim perceptual quality from provider status.
    return dest
