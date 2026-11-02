"""Stage-gated local mixing with approved voice/music versions."""
import json
import math
from pathlib import Path

from .audit import record
from .core import binary, duration, hashes, new_outputs, run, stage, write_new
from .runtime import w

def mix(project,voice,music,out,gain=.16,start=0,length=None,_duration=None):
    probe_duration=_duration or duration
    state=stage(project,{11,12}); dest=new_outputs(project,out,['.mix.json'])
    voice=w.inside(project,voice); music=w.inside(project,music)
    if w.sha(voice) not in hashes(state,5):raise ValueError('旁白不是第5步确认版本')
    if w.sha(music) not in hashes(state,10):raise ValueError('音乐不是第10步确认版本，先试听并确认')
    settings={'kind':'wedding-mix-settings-v1','voice_sha256':w.sha(voice),'music_sha256':w.sha(music),'gain':gain}
    if state['current_step']==12:
        approved=[]
        for a in state['steps']['11']['artifacts']:
            if a['path'].endswith('.mix.json'):
                d=json.loads(w.inside(project,a['path']).read_text(encoding='utf-8'))
                approved.append({k:d.get(k) for k in settings})
        if settings not in approved:raise ValueError('声轨或音量不是第11步试听确认设置，先登记 .mix.json 或重听片段')
    total=probe_duration(voice); music_total=probe_duration(music)
    length=total-start if length is None else length
    if not all(math.isfinite(x) for x in (gain,start,length)) or not 0<gain<=1 or start<0 or length<=0 or start+length>total+.02:raise ValueError('音量或试听区间无效')
    if state['current_step']==12 and (start!=0 or abs(length-total)>.001):raise ValueError('第12步必须生成完整混音')
    if music_total+.02<start+length: raise ValueError('音乐长度不足，先安排延展或自然剪接；不能只补静音冒充完成')
    # Music arrangement supplies story dynamics; sidechain handles voice masking only.
    graph=f'[0:a]asplit=2[vo][side];[1:a]volume={gain},afade=t=out:st={max(0,length-1)}:d=1[bg];[bg][side]sidechaincompress=threshold=0.025:ratio=6:attack=20:release=350[duck];[vo][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]'
    run([binary('ffmpeg'),'-v','error','-n','-ss',start,'-t',length,'-i',voice,'-ss',start,'-t',length,'-i',music,'-filter_complex',graph,'-map','[a]','-ar','48000','-ac','2',dest])
    write_new(dest.with_suffix('.mix.json'),json.dumps({**settings,'start':start,'length':length,'voice':voice.relative_to(Path(project).resolve()).as_posix(),'music':music.relative_to(Path(project).resolve()).as_posix()},ensure_ascii=False,indent=2))
    record(project,'mix',voice=voice.name,music=music.name,gain=gain,start=start,length=round(length,3),out=dest.name)
    return dest
