"""Caption validation, measured layout, ASS payload and PNG fallback rendering."""
import math
import re

from .core import binary, run

def validate_cues(cues,total):
    previous=0
    if not cues: raise ValueError('需要与主音轨对齐的字幕')
    for cue in cues:
        start,end=float(cue['start']),float(cue['end'])
        if not math.isfinite(start+end) or start<previous-.001 or end<=start or end>total+.02 or not str(cue['text']).strip():
            raise ValueError('字幕重叠、越界或为空')
        previous=end

def caption_size(width,height):
    # Use the short edge so portrait frames do not get landscape-sized type.
    return max(20,round(min(width,height)*.05))

def _wrap_cjk(line,face,max_width):
    lines=[];current=''
    for ch in line:
        proposed=current+ch
        # Keep the legacy 18-character rhythm, then fit real pixel width (stroke included).
        if current and (len(proposed)>18 or face.getlength(proposed)+4>max_width):
            lines.append(current);current=ch
        else:current=proposed
    if current:lines.append(current)
    if len(lines)==2 and len(lines[1])*2<len(lines[0]):
        joined=''.join(lines);mid=(len(joined)+1)//2
        balanced=(joined[:mid],joined[mid:])
        if all(face.getlength(x)+4<=max_width for x in balanced):lines=list(balanced)
    return lines

def caption_lines(text,face,max_width,language='zh'):
    wrapped=[]
    for line in str(text).splitlines():
        if language=='en':
            current=''
            for word in line.split():
                box=face.getbbox(word,stroke_width=2)
                if box[2]-box[0]>max_width:raise ValueError('A subtitle word exceeds the safe width; split the cue or adjust its layout')
                proposed=(current+' '+word).strip();box=face.getbbox(proposed,stroke_width=2)
                if current and box[2]-box[0]>max_width:wrapped.append(current);current=word
                else:current=proposed
            if current:wrapped.append(current)
        else:
            wrapped.extend(_wrap_cjk(line,face,max_width))
    if len(wrapped)>2:raise ValueError('Subtitle exceeds two lines; split it into shorter timed cues' if language=='en' else '字幕过长，请按实际语义拆成更短时间段')
    return wrapped

def layout_captions(cues,width,height,font,language='zh'):
    try: from PIL import Image, ImageDraw, ImageFont
    except ImportError:raise ValueError('字幕渲染缺少 Pillow；运行 python3 -m pip install Pillow 后继续')
    face=ImageFont.truetype(font,caption_size(width,height))
    canvas=Image.new('RGBA',(width,height),(0,0,0,0));draw=ImageDraw.Draw(canvas)
    layouts=[]
    for cue in cues:
        wrapped=caption_lines(cue['text'],face,width*.88,language)
        text='\n'.join(wrapped)
        box=draw.multiline_textbbox((0,0),text,font=face,stroke_width=2,spacing=6)
        tw,th=box[2]-box[0],box[3]-box[1]
        if tw>width*.88:raise ValueError('字幕超出安全区，缩短字幕或调整版式' if language!='en' else 'Subtitle exceeds the safe width; shorten the cue or adjust its layout')
        layouts.append((wrapped,text,box,tw,th))
    return face,layouts

def captions(cues,width,height,folder,font,language='zh',layout=None):
    try: from PIL import Image, ImageDraw
    except ImportError:raise ValueError('字幕渲染缺少 Pillow；运行 python3 -m pip install Pillow 后继续')
    face,items=layout if layout is not None else layout_captions(cues,width,height,font,language)
    for i,(wrapped,text,box,tw,th) in enumerate(items):
        im=Image.new('RGBA',(width,height),(0,0,0,0));d=ImageDraw.Draw(im)
        d.multiline_text(((width-tw)/2-box[0],height-height*.08-th-box[1]),text,font=face,fill=(255,249,240,255),stroke_width=2,stroke_fill=(20,20,20,240),spacing=6,align='center')
        im.save(folder/f'cue-{i:03}.png')

def has_filter(name):
    try:listing=run([binary('ffmpeg'),'-hide_banner','-filters'])
    except ValueError:return False
    return bool(re.search(r'^\s*\S+\s+'+re.escape(name)+r'\s',listing,re.M))

def ass_time(t):
    cs=max(0,round(float(t)*100));h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f'{h}:{m:02}:{s:02}.{cs:02}'

def ass_text(lines):
    return r'\N'.join(str(x).replace('\\','\\\\').replace('{','\\{').replace('}','\\}') for x in lines)

def build_ass(cues,width,height,face,items):
    """One ASS payload from the same wrapped layout used by the PNG fallback."""
    family=(face.getname()[0] or 'Sans').replace(',',' ')
    size=caption_size(width,height);margin=max(8,round(height*.08))
    head=(f'[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n'
          '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
          f'Style: Default,{family},{size},&H00F0F9FF,&H00F0F9FF,&H00202020,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,{margin},1\n\n'
          '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
    body=''.join(f'Dialogue: 0,{ass_time(c["start"])},{ass_time(c["end"])},Default,,0,0,0,,{ass_text(wrapped)}\n' for c,(wrapped,_t,_b,_w,_h) in zip(cues,items))
    return head+body
