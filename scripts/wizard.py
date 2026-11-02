#!/usr/bin/env python3
"""Portable project receipts and handoff ZIPs. Never generates images."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import zipfile

# Single source of truth: step id, Chinese name, English name, required roles, artifact kind.
STEP_SPECS=[
    (1,'故事采集','Story intake',('producer',),'plain'),
    (2,'文案写作包与初稿','Writing pack and draft',('producer',),'plain'),
    (3,'当事人确认文案','Story owner script approval',('owner',),'plain'),
    (4,'配音音色试听','Voice auditions',('producer',),'plain'),
    (5,'完整旁白','Full narration',('producer',),'plain'),
    (6,'分镜设计','Storyboard',('producer',),'shots'),
    (7,'三个重点分镜试图','Three pilot images',('producer',),'plain'),
    (8,'剩余分镜生图','Remaining images',('producer',),'plain'),
    (9,'图生视频','Image-to-video',('producer',),'video_pack'),
    (10,'BGM 风格试听','Music style auditions',('producer',),'plain'),
    (11,'配音与 BGM 片段','Voice + BGM excerpts',('producer',),'plain'),
    (12,'完整混音','Full audio mix',('producer',),'plain'),
    (13,'带字幕预览','Subtitled preview',('producer',),'edit_plan'),
    (14,'正式成片交付','Final delivery',('producer','owner'),'edit_plan'),
]
STEPS=[s[1] for s in STEP_SPECS]
STEPS_EN=[s[2] for s in STEP_SPECS]
TOTAL=len(STEP_SPECS)
STATE='PROJECT_STATE.json'
STATE_VERSION=2
LOCK='.state.lock'
STATUSES=('not_started','awaiting_confirmation','needs_review','confirmed')
TRANSITIONS={
    'prepare':{'not_started':'awaiting_confirmation','needs_review':'awaiting_confirmation','awaiting_confirmation':'awaiting_confirmation'},
    'approve':{'awaiting_confirmation':'confirmed'},
    'reopen':{'awaiting_confirmation':'needs_review','needs_review':'needs_review','confirmed':'needs_review'},
}
JSON_ARTIFACTS={6:'SHOT_PLAN.json',9:'VIDEO_PACK.json',13:'EDIT_PLAN.json',14:'EDIT_PLAN.json'}

# English rendering for the gates a beginner is most likely to hit.
ERRORS_EN=[
    ('当前步骤尚未登记实际交付文件','No deliverable is registered for the current step. '),
    ('文件版本已变化，先 reopen 并重新确认：','The file changed. Reopen and approve it again: '),
    ('确认依据不完整：','Approval evidence is incomplete: '),
    ('当前步骤与确认记录不一致','The current step does not match the approval record.'),
    ('完成状态与确认记录不一致','The completion flag does not match the approval record.'),
    ('只能操作当前步骤；修改旧成果先 reopen','Only the current step can be changed; reopen an earlier one first.'),
    ('需要实际交付文件','Actual deliverable files are required.'),
    ('重复文件','The same file was listed twice.'),
    ('状态文件不能作为交付证据','PROJECT_STATE.json cannot be used as deliverable evidence.'),
    ('必须记录实际用户回复，不能空确认','Record the real user reply; blank approval is not allowed.'),
    ('请先 prepare 当前交付文件再确认','Register the current deliverable with prepare before approving.'),
    ('已有项目，请续做，不覆盖状态','A project already exists. Resume it instead of overwriting.'),
    ('文件必须在本单项目目录内：','Files must stay inside this project folder: '),
    ('缺少文件：','Missing file: '),
    ('输出已存在，请使用新版本名','Output already exists; use a new version name.'),
    ('写作包仍为空或包含未填占位符','The writing pack is empty or still contains placeholders.'),
    ('压缩包完整性错误','The ZIP failed its integrity check.'),
    ('镜头计划不是第6步确认版本','The shot plan is not the step-6 approved version.'),
    ('镜号重复、缺失或与确认计划不一致','Shot IDs are duplicated, missing or different from the approved plan.'),
    ('不安全的镜号','Unsafe shot ID.'),
    ('不支持的首帧文件类型','Unsupported first-frame image type.'),
    ('首帧不是已确认的第7/8步图片：','The first frame is not a confirmed step-7/8 image: '),
    ('首帧不是可解码图片，先补回原图：','The first frame cannot be decoded; restore the original image: '),
    ('视频提示词为空或有占位符：','The video prompt is empty or contains placeholders: '),
    ('打包首帧需 Pillow 校验图片，请安装后继续当前步骤','Pillow is required to verify first frames; install it and continue.'),
    ('缺少 Pillow','Pillow is required; install it and continue.'),
    ('分镜表必须包含非空 shots 列表','The storyboard needs a non-empty shots list.'),
    ('分镜缺少有效 id','A storyboard shot has no valid id.'),
    ('分镜 id 重复','Storyboard shot ids are duplicated.'),
    ('剪辑计划缺少字段：','The edit plan is missing fields: '),
    ('剪辑计划镜头字段无效：','Invalid shot fields in the edit plan: '),
    ('剪辑计划字幕字段无效：','Invalid cue fields in the edit plan: '),
    ('视频包缺少 manifest.json','The video ZIP is missing manifest.json.'),
    ('视频包缺少分镜文件夹','The video ZIP has no per-shot folders.'),
    ('未开始的步骤不能 reopen','A step that has not started cannot be reopened.'),
    ('需要有效步骤和修改原因','A valid step and revision reason are required.'),
    ('受影响步骤范围错误','The affected step range is invalid.'),
    ('当前步骤不允许此操作','This action is not allowed at the current step.'),
    ('输出已存在，请用新的版本名','Output already exists; use a new version name.'),
    ('本地媒体命令失败：','Local media command failed: '),
    ('缺少 ffmpeg；请安装或设置 FFMPEG_BIN 后继续当前步骤','ffmpeg is missing; install it or set FFMPEG_BIN and continue.'),
    ('缺少 ffprobe；请安装或设置 FFPROBE_BIN 后继续当前步骤','ffprobe is missing; install it or set FFPROBE_BIN and continue.'),
    ('音色选择不是第4步确认版本','The voice selection is not the step-4 approved version.'),
    ('完整配音正文不是当事人确认且试听选用的文案；修改需重新确认','The narration is not the owner-approved script used in the audition; re-approve any change.'),
    ('音色、语速或情绪指导与第4步选择不一致，先重新试听','Voice, rate or direction differs from the step-4 choice; audition again first.'),
    ('拒绝携带凭据跟随接口重定向','Refused to follow a redirect while carrying credentials.'),
    ('生成请求未取得可验证结果','The generation request produced no verifiable result.'),
    ('需当前任务明确授权文字 API 调用','This task must explicitly authorize a text-API call.'),
    ('未配置 MOONSHOT_API_KEY；使用写作包复制到 Kimi','MOONSHOT_API_KEY is not configured; use the writing pack in Kimi instead.'),
    ('内置适配仅支持官方 Kimi 地址；其他服务按用户确认的接口另行适配','The built-in adapter supports official Kimi endpoints only; adapt other services explicitly.'),
    ('未配置 MOONSHOT_API_KEY','MOONSHOT_API_KEY is not configured.'),
    ('文案未完整返回，请检查输出限制','The draft was truncated; check the output limit.'),
    ('未返回旁白正文','No narration text was returned.'),
    ('语音服务返回错误码 ','The speech service returned error code '),
    ('语音流不完整或为空；不标记生成完成','The speech stream is incomplete or empty; it is not marked complete.'),
    ('语音服务返回了非对象事件','The speech service returned a non-object event.'),
    ('需当前任务明确授权豆包 API 调用','This task must explicitly authorize a Doubao API call.'),
    ('此适配输出 MP3，请使用 .mp3 文件名','This adapter outputs MP3; use an .mp3 filename.'),
    ('正文、情绪指导或语速无效','The text, direction or speaking rate is invalid.'),
    ('豆包配置缺失；本地配置密钥，不要贴到对话或仓库','Doubao credentials are missing; configure them locally and never paste keys into chat or the repo.'),
    ('旁白不是第5步确认版本','The narration is not the step-5 approved version.'),
    ('音乐不是第10步确认版本，先试听并确认','The music is not the step-10 approved version; audition and approve it first.'),
    ('声轨或音量不是第11步试听确认设置，先登记 .mix.json 或重听片段','The tracks or gain differ from the step-11 approved settings; register the .mix.json or re-audition.'),
    ('音量或试听区间无效','The gain or excerpt range is invalid.'),
    ('第12步必须生成完整混音','Step 12 must produce the full mix.'),
    ('音乐长度不足，请安排延展或自然剪接；不能只补静音冒充完成','The music is too short; extend it or edit naturally instead of padding silence.'),
    ('需要与主音轨对齐的字幕','Cues aligned to the master audio are required.'),
    ('字幕重叠、越界或为空','A cue overlaps, exceeds the timeline or is empty.'),
    ('时间表为空或时长无效','The timeline is empty or its duration is invalid.'),
    ('非有限时间','A timeline value is not finite.'),
    ('时间表有空隙、重叠或无效区间','The timeline has a gap, overlap or invalid range.'),
    ('变速过大，请重新安排镜头','Speed change is too large; re-plan the shot.'),
    ('时间表总长与主音轨不一致','Timeline duration does not match the master audio.'),
    ('字幕渲染缺少 Pillow；运行 python3 -m pip install Pillow 后继续','Pillow is required for captions; install it and continue.'),
    ('主混音不是第12步确认版本','The master mix is not the step-12 approved version.'),
    ('剪辑引用的分镜表不是第6步确认版本','The edit plan cites a storyboard that is not the step-6 approved version.'),
    ('剪辑镜号缺失、重复或顺序与确认分镜不一致；改叙事先重新确认分镜','Shot IDs are missing, duplicated or out of approved order; re-approve the storyboard before changing the narrative.'),
    ('画幅或帧率无效','The frame size or rate is invalid.'),
    ('镜头切点必须对齐目标帧率','Shot boundaries must align to the target frame rate.'),
    ('视频不是第9步确认版本：','The video is not a step-9 approved version: '),
    ('素材入出点超过实际视频','The source in/out point exceeds the actual video.'),
    ('成片缺少视频或音频流','The exported film is missing a video or audio stream.'),
    ('成片时长与主音轨不一致','The exported duration does not match the master audio.'),
    ('成片画幅与计划不一致','The exported frame size differs from the plan.'),
    ('成片帧率与计划不一致','The exported frame rate differs from the plan.'),
    ('状态正被另一进程使用，稍后重试','The state file is in use by another process; retry shortly.'),
]

def language(state):return state.get('language','zh')

def translate(text,lang='zh'):
    if lang!='en':return text
    for zh,en in ERRORS_EN:
        if text.startswith(zh):return en+text[len(zh):]
    return text

def step_spec(n):
    if not isinstance(n,int) or not 1<=n<=TOTAL:raise ValueError('步骤编号无效')
    return STEP_SPECS[n-1]

def move(record,action,step):
    table=TRANSITIONS[action]
    if record['status'] not in table:
        raise ValueError('步骤 '+str(step)+' 当前状态 '+record['status']+' 不能执行 '+action)
    record['status']=table[record['status']]
    return record['status']

def _set_language(project,lang):
    if lang not in ('zh','en'):raise ValueError('Supported interface languages: zh, en')
    s=validate(project)
    s.setdefault('content_language',s.get('language','zh'))
    s['history'].append({'at':now(),'action':'interface-language','from':language(s),'to':lang})
    s['language']=lang
    save(project,s);return s

def set_language(project,lang):
    with lock(project):return _set_language(project,lang)

def now(): return datetime.now(timezone.utc).isoformat()
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def stat_of(path):
    st=Path(path).stat();return {'size':st.st_size,'mtime_ns':st.st_mtime_ns}

def inside(project,path,existing=True):
    root=Path(project).resolve(); p=Path(path)
    if not p.is_absolute(): p=root/p
    p=p.resolve()
    try: p.relative_to(root)
    except ValueError: raise ValueError('文件必须在本单项目目录内：'+p.name)
    if existing and not p.is_file(): raise ValueError('缺少文件：'+p.name)
    return p

def save(project,state):
    root=Path(project).resolve()
    state['updated_at']=now()
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=root,delete=False) as f:
        json.dump(state,f,ensure_ascii=False,indent=2); f.write('\n'); tmp=f.name
    os.replace(tmp,root/STATE)

def init(project,lang='zh',content_language=None):
    if lang not in ('zh','en') or content_language not in (None,'zh','en'):raise ValueError('Supported languages: zh, en')
    root=Path(project).resolve()
    skill=Path(__file__).resolve().parents[1]
    if root==skill or skill in root.parents: raise ValueError('订单目录不能在 Skill 源码/安装目录内')
    if (root/STATE).exists(): raise ValueError('已有项目，请续做，不覆盖状态')
    root.mkdir(parents=True,exist_ok=True)
    s={'schema_version':STATE_VERSION,'created_at':now(),'current_step':1,'completed':False,'language':lang,'content_language':content_language or lang,
       'steps':{str(i):{'name':n,'status':'not_started','artifacts':[], 'approvals':[]} for i,n in enumerate(STEPS,1)},'history':[]}
    save(root,s); return s

def migrate(s):
    """Fill fields introduced after schema 1; old orders keep working."""
    if s.get('schema_version',1)==1:
        s.setdefault('language','zh')
        s.setdefault('content_language',s['language'])
        s['schema_version']=STATE_VERSION
    return s

@contextlib.contextmanager
def lock(project,stale_after=60,timeout=10):
    """Advisory lock via exclusive lockfile; stale locks are reclaimed."""
    guard=Path(project).resolve()/LOCK
    deadline=time.monotonic()+timeout
    while True:
        try:
            fd=os.open(guard,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(json.dumps({'pid':os.getpid(),'at':now()}))
            break
        except FileExistsError:
            try:age=time.time()-guard.stat().st_mtime
            except OSError:age=0
            if age>stale_after:guard.unlink(missing_ok=True);continue
            if time.monotonic()>deadline:raise ValueError('状态正被另一进程使用，稍后重试') from None
            time.sleep(.05)
    try:yield
    finally:guard.unlink(missing_ok=True)

def load(project):
    s=migrate(json.loads((Path(project)/STATE).read_text(encoding='utf-8')))
    if s.get('schema_version')!=STATE_VERSION or set(s.get('steps',{}))!={str(n) for n in range(1,TOTAL+1)}:
        raise ValueError('状态结构不支持；不要重新初始化覆盖')
    if not isinstance(s.get('current_step'),int) or not 1<=s['current_step']<=TOTAL:
        raise ValueError('步骤编号无效')
    if s.get('completed') not in (True,False):raise ValueError('完成状态无效')
    return s

def required(n): return set(step_spec(n)[3])

def check_artifacts(project,record,strict=False):
    if not record['artifacts']: raise ValueError('当前步骤尚未登记实际交付文件')
    for a in record['artifacts']:
        p=inside(project,a['path']);current=stat_of(p)
        # Re-hash only when size or mtime changed; --strict always re-hashes.
        cached=a.get('stat')
        if not strict and cached and cached.get('size')==current['size'] and cached.get('mtime_ns')==current['mtime_ns']:
            continue
        if sha(p)!=a['sha256']: raise ValueError('文件版本已变化，先 reopen 并重新确认：'+a['path'])

def validate(project,state=None,strict=False):
    s=state or load(project)
    for k,r in s['steps'].items():
        if r['status']=='confirmed':
            check_artifacts(project,r,strict)
            if not required(int(k))<={a['by'] for a in r['approvals'] if a['evidence'].strip()}:
                raise ValueError('确认依据不完整：'+k)
    expected=next((i for i in range(1,TOTAL+1) if s['steps'][str(i)]['status']!='confirmed'),TOTAL)
    if expected!=s['current_step']: raise ValueError('当前步骤与确认记录不一致')
    if s['completed']!=all(r['status']=='confirmed' for r in s['steps'].values()):
        raise ValueError('完成状态与确认记录不一致')
    return s

def advance(s):
    pending=[n for n in range(1,TOTAL+1) if s['steps'][str(n)]['status']!='confirmed']
    s['current_step']=pending[0] if pending else TOTAL
    s['completed']=not pending

def current(project,n):
    s=validate(project)
    if s['completed'] or n!=s['current_step']: raise ValueError('只能操作当前步骤；修改旧成果先 reopen')
    return s

def read_json(path,label):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (UnicodeDecodeError,json.JSONDecodeError):raise ValueError(label+'不是有效 JSON：'+Path(path).name) from None

def require(condition,message):
    if not condition:raise ValueError(message)

def require_fields(data,fields,label):
    require(isinstance(data,dict),label+'必须是 JSON 对象')
    missing=[f for f in fields if f not in data]
    if missing:raise ValueError(label+'缺少字段：'+', '.join(missing))

def validate_ids(shots,label):
    ids=[]
    for shot in shots:
        require(isinstance(shot,dict),label+'镜头必须是 JSON 对象')
        ident=shot.get('id')
        require(isinstance(ident,(str,int)) and str(ident).strip()!='',label+'缺少有效 id')
        ids.append(str(ident))
    require(len(ids)==len(set(ids)),label+' id 重复')

def validate_shot_plan(data):
    require_fields(data,['shots'],'分镜表')
    require(isinstance(data['shots'],list) and data['shots'],'分镜表必须包含非空 shots 列表')
    validate_ids(data['shots'],'分镜表')

def validate_video_pack_json(data):
    require_fields(data,['plan','shots'],'视频包清单')
    require(isinstance(data['plan'],str) and data['plan'].strip(),'视频包清单缺少 plan 路径')
    require(isinstance(data['shots'],list) and data['shots'],'视频包清单缺少 shots')
    validate_ids(data['shots'],'视频包清单')
    for shot in data['shots']:
        for field in ('image','prompt'):
            require(isinstance(shot.get(field),str) and shot[field].strip(),'视频包清单镜头缺少 '+field)

def validate_edit_plan(data):
    require_fields(data,['storyboard','audio','shots','cues'],'剪辑计划')
    for field in ('storyboard','audio'):
        require(isinstance(data[field],str) and data[field].strip(),'剪辑计划缺少字段：'+field)
    require(isinstance(data['shots'],list) and data['shots'],'剪辑计划镜头为空')
    validate_ids(data['shots'],'剪辑计划')
    for shot in data['shots']:
        for field in ('file','in','out','start','end'):
            require(field in shot,'剪辑计划镜头字段无效：'+str(shot.get('id')))
    require(isinstance(data['cues'],list) and data['cues'],'剪辑计划字幕为空')
    for cue in data['cues']:
        require(isinstance(cue,dict) and all(k in cue for k in ('start','end','text')) and str(cue.get('text','')).strip(),
                '剪辑计划字幕字段无效：'+str(cue))

def validate_video_zip(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if 'manifest.json' not in names:raise ValueError('视频包缺少 manifest.json')
        try:manifest=json.loads(z.read('manifest.json'))
        except json.JSONDecodeError:raise ValueError('视频包 manifest.json 无法解析') from None
        if not isinstance(manifest,list) or not manifest:raise ValueError('视频包 manifest.json 为空')
        if not any('/' in name for name in names):raise ValueError('视频包缺少分镜文件夹')

def validate_structured(n,paths,project=None):
    """Fail before approval when a canonical JSON deliverable is structurally broken."""
    canonical=JSON_ARTIFACTS.get(n)
    for p in paths:
        if canonical and p.name==canonical:
            data=read_json(p,'第 '+str(n)+' 步交付文件')
            if n==6:validate_shot_plan(data)
            elif n==9:validate_video_pack_json(data)
            else:validate_edit_plan(data)
        elif n==9 and p.suffix.lower()=='.zip':
            validate_video_zip(p)

def _prepare(project,n,files):
    s=current(project,n)
    if not files: raise ValueError('需要实际交付文件')
    paths=[inside(project,p) for p in files]
    if len(set(paths))!=len(paths): raise ValueError('重复文件')
    if any(p.name==STATE for p in paths): raise ValueError('状态文件不能作为交付证据')
    validate_structured(n,paths)
    r=s['steps'][str(n)]
    if r['artifacts']: s['history'].append({'at':now(),'action':'replace-deliverable','step':n,'previous':r.copy()})
    r['artifacts']=[]
    for p in paths:
        # Stat first: if the file changes mid-hash, the stale stat forces a later recheck.
        st=stat_of(p);digest=sha(p)
        r['artifacts'].append({'path':p.relative_to(Path(project).resolve()).as_posix(),'sha256':digest,'bytes':st['size'],'stat':st})
    r['approvals']=[];move(r,'prepare',n)
    save(project,s); return s

def prepare(project,n,files):
    with lock(project):return _prepare(project,n,files)

def _approve(project,n,by,evidence):
    # 'couple' 是 v1 角色名，归一为 'owner'；存量记录两种都算同一角色。
    by={'couple':'owner'}.get(by,by)
    seen=lambda role:{'owner':('owner','couple')}.get(role,(role,))
    s=current(project,n); r=s['steps'][str(n)]
    if r['status']!='awaiting_confirmation':raise ValueError('请先 prepare 当前交付文件再确认')
    if by not in required(n): raise ValueError('本步骤需要 '+','.join(sorted(required(n)))+' 的确认')
    if not evidence.strip(): raise ValueError('必须记录实际用户回复，不能空确认')
    check_artifacts(project,r)
    if any(a['by'] in seen(by) for a in r['approvals']): raise ValueError('该角色已经确认；换版请重新 prepare')
    if n==14 and by=='owner' and not any(a['by']=='producer' for a in r['approvals']):
        raise ValueError('正式片先由制作方核对，再记录当事人验收')
    r['approvals'].append({'at':now(),'by':by,'evidence':evidence.strip()})
    if required(n)<={{'couple':'owner'}.get(a['by'],a['by']) for a in r['approvals']}:move(r,'approve',n)
    advance(s); save(project,s); return s

def approve(project,n,by,evidence):
    with lock(project):return _approve(project,n,by,evidence)

def _reopen(project,n,affected,reason):
    s=load(project)
    if not reason.strip(): raise ValueError('需要有效步骤和修改原因')
    step_spec(n)
    if n>s['current_step']: raise ValueError('不能回退尚未开始的步骤')
    if s['steps'][str(n)]['status']=='not_started': raise ValueError('未开始的步骤不能 reopen')
    ns=set(affected or range(n,TOTAL+1))|{n}
    if any(i<n or i>TOTAL for i in ns): raise ValueError('受影响步骤范围错误')
    # Keep files and old receipts in history; only selected approvals become stale.
    for i in sorted(ns):
        r=s['steps'][str(i)]
        if r['status']=='not_started':continue
        old=r.copy()
        move(r,'reopen',i)
        r['approvals']=[]
        s['history'].append({'at':now(),'action':'reopen','step':i,'reason':reason,'previous':old})
    advance(s); save(project,s); return s

def reopen(project,n,affected,reason):
    with lock(project):return _reopen(project,n,affected,reason)

def summary(project):
    s=validate(project); n=s['current_step']; r=s['steps'][str(n)]
    if language(s)=='en':
        names={'not_started':'Not started','awaiting_confirmation':'Awaiting approval','needs_review':'Needs revision','confirmed':'Approved'}
        status='Accepted by the story owner' if s['completed'] else names[r['status']]
        return f'[{n}/{TOTAL} | {STEPS_EN[n-1]} | {status} | {TOTAL-n} steps remaining]'
    names={'not_started':'未开始','awaiting_confirmation':'待确认','needs_review':'需要修改','confirmed':'已确认'}
    status='当事人已验收' if s['completed'] else names[r['status']]
    return f'【{n}/{TOTAL}｜{STEPS[n-1]}｜{status}｜后续还剩 {TOTAL-n} 步】'

def summary_data(project):
    """Machine-readable progress for --json output and external tooling."""
    s=validate(project); n=s['current_step']; r=s['steps'][str(n)]
    return {'schema_version':s['schema_version'],'current_step':n,'total':TOTAL,'step':r['name'],'step_en':STEPS_EN[n-1],
            'status':r['status'],'completed':s['completed'],'remaining':TOTAL-n,
            'language':language(s),'content_language':s.get('content_language',language(s))}

def route(kind,configured=False):
    if kind in ('image','image-edit','character-image'): return 'external-gpt-manual'
    if kind not in ('writing','voice','video','music','editing'): raise ValueError('未知环节')
    return 'api-if-authorized' if configured else 'guided-manual-or-configure'

def zip_new(project,out,entries):
    out=inside(project,out,False)
    if out.exists(): raise ValueError('输出已存在，请使用新版本名')
    out.parent.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for name,data in entries.items():
        if isinstance(data,Path):
            manifest.append({'path':name,'bytes':data.stat().st_size,'sha256':sha(data)})
        else:
            manifest.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    entries=dict(entries)
    entries['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    with tempfile.NamedTemporaryFile(dir=out.parent,delete=False) as f: tmp=Path(f.name)
    try:
        with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,data in entries.items():
                # Stream files straight into the archive instead of loading them into memory.
                if isinstance(data,Path):z.write(data,name)
                else:z.writestr(name,data)
        with zipfile.ZipFile(tmp) as z:
            if z.testzip(): raise ValueError('压缩包完整性错误')
        # Exclusive output creation prevents overwriting even during a race.
        with out.open('xb') as dst,tmp.open('rb') as src:shutil.copyfileobj(src,dst)
    finally: tmp.unlink(missing_ok=True)
    return out

def writing_pack(project,prompt,out):
    s=current(project,2)
    p=inside(project,prompt); text=p.read_text(encoding='utf-8')
    if not text.strip() or re.search(r'\{\{[^}]+\}\}|\[待填\]|TODO',text):
        raise ValueError('写作包仍为空或包含未填占位符')
    if language(s)=='en':
        return zip_new(project,out,{'00-README.txt':('Kimi K3 is strongly recommended. Open 01-Copy-to-Kimi-K3.txt, copy the complete text into a Kimi conversation, and return the full draft to the current production conversation. The creator reviews it first; the story owner must then approve that exact version before production continues.\n').encode(),
                                  '01-Copy-to-Kimi-K3.txt':text.encode()})
    return zip_new(project,out,{'00-使用说明.txt':'建议使用 Kimi K3。打开 01 文件，全选复制到 Kimi 对话，取得完整初稿后发回当前制作对话。先由制作方审稿，再发当事人确认。\n'.encode(),
                              '01-一键复制给Kimi-K3.txt':text.encode()})

def video_pack(project,manifest,out):
    s=current(project,9)
    data=read_json(inside(project,manifest),'视频包清单')
    validate_video_pack_json(data)
    plan_path=inside(project,data['plan'])
    approved_plan={a['sha256'] for a in s['steps']['6']['artifacts']}
    if sha(plan_path) not in approved_plan: raise ValueError('镜头计划不是第6步确认版本')
    plan=read_json(plan_path,'分镜表');validate_shot_plan(plan)
    expected=[str(x['id']) for x in plan['shots']]
    shots=data['shots']; ids=[str(x['id']) for x in shots]
    if not ids or len(set(ids))!=len(ids) or set(ids)!=set(expected) or len(set(expected))!=len(expected):
        raise ValueError('镜号重复、缺失或与确认计划不一致')
    approved={a['sha256'] for n in ('7','8') for a in s['steps'][n]['artifacts']}
    entries={'00-使用说明.txt':'每镜一个文件夹。上传本镜首帧图片，复制视频提示词，按提示词设置时长和画幅。确认模型入口能固定首帧；普通参考槽不一定等价。生成后完整自查，再按镜号发回当前对话。此包不授权自动生图。\n'.encode()}
    en=language(s)=='en'
    if en:entries={'00-README.txt':('Each shot has its own folder. Upload its first-frame image to your video model, paste video-prompt.txt, and set the requested duration and aspect ratio. Verify that the input fixes the first frame; a generic reference slot may not. Watch the whole result, then return the video with its shot ID to the current conversation. This package does not authorize automated image generation.\n').encode()}
    for shot in shots:
        ident=str(shot['id'])
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',ident): raise ValueError('不安全的镜号')
        pic=inside(project,shot['image'])
        if pic.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'): raise ValueError('不支持的首帧文件类型')
        if sha(pic) not in approved: raise ValueError('首帧不是已确认的第7/8步图片：'+ident)
        try:
            from PIL import Image
        except ImportError:raise ValueError('打包首帧需 Pillow 校验图片，请安装后继续当前步骤')
        try:
            with Image.open(pic) as im:im.verify()
            with Image.open(pic) as im:im.load()
        except Exception:raise ValueError('首帧不是可解码图片，先补回原图：'+ident) from None
        prompt=inside(project,shot['prompt']).read_text(encoding='utf-8')
        if not prompt.strip() or re.search(r'\{\{[^}]+\}\}|\[待填\]|TODO',prompt): raise ValueError('视频提示词为空或有占位符：'+ident)
        entries[f'{ident}/'+('first-frame' if en else '首帧参考图')+pic.suffix.lower()]=pic
        entries[f'{ident}/'+('video-prompt.txt' if en else '视频提示词.txt')]=prompt.encode()
    return zip_new(project,out,entries)

def cli_language(args=None):
    candidates=[getattr(args,'project',None)] if args is not None else []
    candidates+= [x for x in sys.argv[1:] if not x.startswith('-')]
    for project in candidates:
        if not project:continue
        try:
            if (Path(project)/STATE).is_file():return language(load(project))
        except (OSError,ValueError,KeyError,TypeError):pass
    return 'zh'

def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='cmd',required=True)
    for name in ('init','summary','validate'):
        q=sub.add_parser(name); q.add_argument('project',type=Path); q.add_argument('--json',action='store_true')
        if name=='init':
            q.add_argument('--lang',choices=['zh','en'],default='zh');q.add_argument('--content-language',choices=['zh','en'])
        if name=='validate':q.add_argument('--strict',action='store_true')
    q=sub.add_parser('language');q.add_argument('project',type=Path);q.add_argument('--lang',choices=['zh','en'],required=True)
    for name in ('prepare','approve','reopen'):
        q=sub.add_parser(name); q.add_argument('project',type=Path); q.add_argument('--step',type=int,required=True); q.add_argument('--json',action='store_true')
        if name=='prepare':q.add_argument('--files',nargs='+',required=True)
        if name=='approve':q.add_argument('--by',choices=['producer','owner','couple'],required=True); q.add_argument('--evidence',required=True)
        if name=='reopen':q.add_argument('--affected',nargs='*',type=int); q.add_argument('--reason',required=True)
    q=sub.add_parser('route'); q.add_argument('kind'); q.add_argument('--configured',action='store_true')
    for name,arg in [('writing-pack','prompt'),('video-pack','manifest')]:
        q=sub.add_parser(name); q.add_argument('project',type=Path); q.add_argument('--'+arg,required=True); q.add_argument('--out',required=True)
    a=p.parse_args()
    def emit(project):
        print(json.dumps(summary_data(project),ensure_ascii=False) if getattr(a,'json',False) else summary(project))
    if a.cmd=='init': init(a.project,a.lang,a.content_language); emit(a.project)
    elif a.cmd=='language':set_language(a.project,a.lang);print(summary(a.project))
    elif a.cmd=='summary': emit(a.project)
    elif a.cmd=='validate':
        validate(a.project,strict=a.strict)
        if a.json:print(json.dumps({'ok':True,'strict':a.strict},ensure_ascii=False))
        else:print('State and approved files match' if language(load(a.project))=='en' else '状态与已确认文件一致')
    elif a.cmd=='prepare': prepare(a.project,a.step,a.files); emit(a.project)
    elif a.cmd=='approve': approve(a.project,a.step,a.by,a.evidence); emit(a.project)
    elif a.cmd=='reopen': reopen(a.project,a.step,a.affected,a.reason); emit(a.project)
    elif a.cmd=='route': print(route(a.kind,a.configured))
    elif a.cmd=='writing-pack': print(writing_pack(a.project,a.prompt,a.out))
    elif a.cmd=='video-pack': print(video_pack(a.project,a.manifest,a.out))

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,KeyError,TypeError) as e:
        lang=cli_language()
        message=translate(str(e),lang)
        if '--json' in sys.argv:
            print(json.dumps({'ok':False,'error':message},ensure_ascii=False),file=sys.stderr); sys.exit(2)
        print(('Not executed: ' if lang=='en' else '未执行：')+message,file=sys.stderr); sys.exit(2)
