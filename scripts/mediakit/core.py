"""Shared process, probe, font and project-gate helpers for the media toolkit."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .runtime import w

def binary(name):
    value=os.environ.get(name.upper()+'_BIN') or shutil.which(name)
    if not value: raise ValueError('缺少 '+name+'；请安装或设置 '+name.upper()+'_BIN 后继续当前步骤')
    return value

def run(args,cwd=None):
    result=subprocess.run([str(x) for x in args],capture_output=True,text=True,cwd=cwd)
    if result.returncode: raise ValueError('本地媒体命令失败：'+result.stderr[-1800:])
    return result.stdout

def probe(path):
    return json.loads(run([binary('ffprobe'),'-v','error','-show_format','-show_streams','-of','json',path]))

def duration(path): return float(probe(path)['format']['duration'])

def font_path(language='zh'):
    candidates=[os.environ.get('WEDDING_FONT',''),'/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/STHeiti Medium.ttc',
      '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','C:/Windows/Fonts/msyh.ttc']
    if language=='en':
        candidates=[os.environ.get('WEDDING_FONT',''),'/System/Library/Fonts/Supplemental/Arial.ttf',
                    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','C:/Windows/Fonts/arial.ttf']+candidates[1:]
    return next((x for x in candidates if x and Path(x).is_file()),None)

def doctor(require=False):
    info={'python':sys.version.split()[0], 'ffmpeg':os.environ.get('FFMPEG_BIN') or shutil.which('ffmpeg'),
     'ffprobe':os.environ.get('FFPROBE_BIN') or shutil.which('ffprobe'),
     'pillow':importlib.util.find_spec('PIL') is not None,'chinese_font':font_path(),'english_font':font_path('en'),
     'kimi_configured':bool(os.environ.get('MOONSHOT_API_KEY')),
     'doubao_configured':bool(os.environ.get('DOUBAO_API_KEY') or (os.environ.get('DOUBAO_APP_ID') and os.environ.get('DOUBAO_ACCESS_KEY'))),
     'image_route':'external-gpt-manual-only','note':'配置存在不代表账号权限、余额或已授权付费调用'}
    if require:
        missing=[k for k in ('ffmpeg','ffprobe','pillow','chinese_font') if not info[k]]
        if missing:raise ValueError('缺少运行依赖：'+', '.join(missing))
    return info

def stage(project,allowed):
    s=w.validate(project)
    if s['completed'] or s['current_step'] not in allowed: raise ValueError('当前步骤不允许此操作')
    return s

def new_output(project,path):
    p=w.inside(project,path,False)
    if p.exists(): raise ValueError('输出已存在，请用新的版本名')
    p.parent.mkdir(parents=True,exist_ok=True); return p

def new_outputs(project,path,suffixes):
    p=new_output(project,path)
    for suffix in suffixes:new_output(project,p.with_suffix(suffix))
    return p

def write_new(path,text):
    with Path(path).open('x',encoding='utf-8') as f:f.write(text)

def hashes(state,n):return {a['sha256'] for a in state['steps'][str(n)]['artifacts']}

def voice_selection(project,state,text,instructions,voice,rate,selection):
    p=w.inside(project,selection)
    if w.sha(p) not in hashes(state,4):raise ValueError('音色选择不是第4步确认版本')
    data=json.loads(p.read_text(encoding='utf-8'))
    w.require_fields(data,['source_script_sha256','voice','rate','instructions_sha256'],'音色选择')
    script=w.inside(project,text);direction=w.inside(project,instructions)
    if w.sha(script) not in hashes(state,3) or w.sha(script)!=data['source_script_sha256']:
        raise ValueError('完整配音正文不是当事人确认且试听选用的文案；修改需重新确认')
    if voice!=data['voice'] or rate!=data['rate'] or w.sha(direction)!=data['instructions_sha256']:
        raise ValueError('音色、语速或情绪指导与第4步选择不一致，先重新试听')
