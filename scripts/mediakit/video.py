"""Timeline validation, final assembly and QC assertions."""
import json
import math
from pathlib import Path
import tempfile

from .audit import record
from .captions import build_ass, captions, has_filter, layout_captions, validate_cues
from .core import binary, duration, font_path, hashes, new_outputs, probe, run, stage, write_new
from .runtime import w

def validate_timeline(shots,total,tolerance=.02):
    previous=0
    if not shots or not math.isfinite(total) or total<=0:raise ValueError('时间表为空或时长无效')
    for s in shots:
        start,end,src_in,src_out=map(float,[s['start'],s['end'],s['in'],s['out']])
        if not all(math.isfinite(x) for x in (start,end,src_in,src_out)):raise ValueError('非有限时间')
        if abs(start-previous)>.002 or end<=start or src_in<0 or src_out<=src_in:raise ValueError('时间表有空隙、重叠或无效区间')
        speed=(src_out-src_in)/(end-start)
        if not .5<=speed<=2:raise ValueError('变速过大，请重新安排镜头')
        previous=end
    if abs(previous-total)>tolerance:raise ValueError('时间表总长与主音轨不一致')

def stamp(t):
    ms=round(t*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def qc_media(info):
    data=json.loads(json.dumps(info))
    data.get('format',{}).pop('filename',None)
    for stream in data.get('streams',[]):stream.pop('filename',None)
    return data

def assemble(project,plan_path,out):
    state=stage(project,{13,14}); dest=new_outputs(project,out,['.srt','.qc.json'])
    plan=w.read_json(w.inside(project,plan_path),'剪辑计划');w.validate_edit_plan(plan)
    audio=w.inside(project,plan['audio']);total=duration(audio)
    if w.sha(audio) not in {a['sha256'] for a in state['steps']['12']['artifacts']}:raise ValueError('主混音不是第12步确认版本')
    shots=plan['shots'];cues=plan['cues']
    storyboard=w.inside(project,plan['storyboard'])
    if w.sha(storyboard) not in hashes(state,6):raise ValueError('剪辑引用的分镜表不是第6步确认版本')
    expected=[s['id'] for s in json.loads(storyboard.read_text(encoding='utf-8'))['shots']]
    if not expected or len(expected)!=len(set(expected)) or [s.get('id') for s in shots]!=expected:
        raise ValueError('剪辑镜号缺失、重复或顺序与确认分镜不一致；改叙事先重新确认分镜')
    width,height,fps=plan.get('width',1920),plan.get('height',1080),plan.get('fps',24)
    if any(not isinstance(x,int) or x<=0 for x in (width,height,fps)) or width%2 or height%2:raise ValueError('画幅或帧率无效')
    validate_timeline(shots,total,tolerance=.5/fps+.000001);validate_cues(cues,total)
    if any(abs(t*fps-round(t*fps))>.01 for s in shots for t in (s['start'],s['end'])):raise ValueError('镜头切点必须对齐目标帧率')
    subtitle_language=plan.get('subtitle_language',state.get('content_language','zh'))
    if subtitle_language not in ('zh','en'):raise ValueError('Supported subtitle languages: zh, en')
    font=font_path(subtitle_language)
    if not font:raise ValueError('Set WEDDING_FONT to a readable font file for the subtitle language')
    # Wrap and measure before any encoding so an over-wide cue fails fast.
    layout=layout_captions(cues,width,height,font,subtitle_language)
    allowed={a['sha256'] for a in state['steps']['9']['artifacts']}
    paths=[]
    for s in shots:
        v=w.inside(project,s['file']);paths.append(v)
        if w.sha(v) not in allowed:raise ValueError('视频不是第9步确认版本：'+v.name)
        if float(s['out'])>duration(v)+.02:raise ValueError('素材入出点超过实际视频')
    work=Path(project).resolve()/'work';work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='edit-',dir=work) as td:
        td=Path(td);parts=[]
        for i,(s,v) in enumerate(zip(shots,paths)):
            target=s['end']-s['start'];speed=(s['out']-s['in'])/target;part=td/f'{i:03}.mp4'
            vf=f'trim=start={s["in"]}:end={s["out"]},setpts=(PTS-STARTPTS)/{speed},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p'
            run([binary('ffmpeg'),'-v','error','-n','-i',v,'-an','-vf',vf,'-t',target,'-c:v','libx264','-crf','18',part]);parts.append(part)
        (td/'concat.txt').write_text(''.join(f"file '{x.name}'\n" for x in parts))
        run([binary('ffmpeg'),'-v','error','-n','-f','concat','-safe','1','-i',td/'concat.txt','-c','copy',td/'picture.mp4'])
        subtitled=td/'subtitled.mp4'
        # Prefer one libass pass; fall back to measured PNG overlays when unavailable.
        if has_filter('ass'):
            (td/'subtitles.ass').write_text(build_ass(cues,width,height,layout[0],layout[1]),encoding='utf-8')
            run([binary('ffmpeg'),'-v','error','-n','-i',td/'picture.mp4','-vf','ass=subtitles.ass','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',subtitled],cwd=td)
        else:
            captions(cues,width,height,td,font,subtitle_language,layout)
            # Bound inputs per render so long scripts do not exhaust file descriptors.
            previous=td/'picture.mp4'
            for batch in range(0,len(cues),12):
                selected=cues[batch:batch+12];args=[binary('ffmpeg'),'-v','error','-n','-i',previous]
                for j in range(len(selected)):args+=['-i',td/f'cue-{batch+j:03}.png']
                chain=[];last='0:v'
                for j,cue in enumerate(selected,1):
                    nxt=f'v{j}';chain.append(f'[{last}][{j}:v]overlay=0:0:enable=\'gte(t,{cue["start"]})*lt(t,{cue["end"]})\'[{nxt}]');last=nxt
                target=td/f'sub-{batch}.mp4'
                run(args+['-filter_complex',';'.join(chain),'-map',f'[{last}]','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',target]);previous=target
            subtitled=previous
        run([binary('ffmpeg'),'-v','error','-n','-i',subtitled,'-i',audio,'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','256k','-ar','48000','-ac','2','-t',total,'-movflags','+faststart',dest])
        info=probe(dest);video=[s for s in info.get('streams',[]) if s.get('codec_type')=='video'];sound=[s for s in info.get('streams',[]) if s.get('codec_type')=='audio']
        if not video or not sound:raise ValueError('成片缺少视频或音频流')
        if abs(float(info['format']['duration'])-total)>max(.05,2/fps):raise ValueError('成片时长与主音轨不一致')
        if (video[0].get('width'),video[0].get('height'))!=(width,height):raise ValueError('成片画幅与计划不一致')
        num,den=(video[0].get('r_frame_rate','0/1').split('/')+['1'])[:2]
        if not den or abs(float(num)/float(den)-fps)>.01:raise ValueError('成片帧率与计划不一致')
    run([binary('ffmpeg'),'-v','error','-i',dest,'-f','null','-'])
    write_new(dest.with_suffix('.srt'),'\n\n'.join(f'{i}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues,1))+'\n')
    write_new(dest.with_suffix('.qc.json'),json.dumps({'technical':'decoded',
        'checks':{'video_stream':True,'audio_stream':True,'duration_seconds':round(total,3),'resolution':[width,height],'fps':fps,'subtitles_burned':True},
        'media':qc_media(info),'human_watch':'pending','couple_acceptance':'pending','source_plan_sha256':w.sha(w.inside(project,plan_path))},ensure_ascii=False,indent=2))
    record(project,'assemble',plan_sha256=w.sha(w.inside(project,plan_path)),out=dest.name,width=width,height=height,fps=fps,seconds=round(total,3))
    return dest
