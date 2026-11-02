import importlib.util
import unittest
from pathlib import Path
import base64
import json
import tempfile
from unittest.mock import patch

class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('media',Path(__file__).resolve().parents[1]/'scripts/media.py')
        cls.m=importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.m)
    def test_audio_stream_requires_end_and_payload(self):
        chunk={'code':0,'data':base64.b64encode(b'abc').decode()}
        with self.assertRaises(ValueError):self.m.decode_tts([chunk])
        with self.assertRaises(ValueError):self.m.decode_tts([{'code':20000000}])
        data,events=self.m.decode_tts([chunk,{'code':20000000}]);self.assertEqual(data,b'abc')
    def test_provider_error_is_not_success(self):
        with self.assertRaises(ValueError):self.m.decode_tts([{'code':55000000,'message':'secret details'}])
    def test_cues_cannot_overlap_or_overrun(self):
        self.m.validate_cues([{'start':0,'end':1,'text':'测试'}],2)
        for cues in [[{'start':0,'end':3,'text':'超时'}],[{'start':0,'end':1,'text':'一'},{'start':.5,'end':2,'text':'二'}]]:
            with self.assertRaises(ValueError):self.m.validate_cues(cues,2)
    def test_timeline_contiguous_and_speed_bounded(self):
        self.m.validate_timeline([{'start':0,'end':2,'in':0,'out':2}],2)
        with self.assertRaises(ValueError):self.m.validate_timeline([{'start':1,'end':2,'in':0,'out':1}],2)
        with self.assertRaises(ValueError):self.m.validate_timeline([{'start':0,'end':2,'in':0,'out':10}],2)
    def test_full_voice_rejects_unapproved_script_and_settings(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);m=self.m;w=m.w;w.init(p)
            script=p/'SCRIPT.txt';script.write_text('已确认的真实故事')
            direction=p/'direction.txt';direction.write_text('自然含笑')
            selected=p/'VOICE_SELECTION.json';selected.write_text(json.dumps({'voice':'A','rate':0,'instructions':'direction.txt','instructions_sha256':w.sha(direction),'source_script':'SCRIPT.txt','source_script_sha256':w.sha(script)}))
            for n in range(1,5):
                files=[script] if n==3 else [selected,direction] if n==4 else [script]
                w.prepare(p,n,files);w.approve(p,n,'couple' if n==3 else 'producer','合成测试确认')
            other=p/'other.txt';other.write_text('未确认的新情节')
            for text,voice,rate in [(other,'A',0),(script,'B',0),(script,'A',50)]:
                with patch.dict('os.environ',{'DOUBAO_API_KEY':'synthetic-not-a-real-key'}), patch.object(m,'request',side_effect=AssertionError('不应发起付费请求')):
                    with self.assertRaises(ValueError):m.tts(p,text,direction,voice,rate,'out.mp3',True)

    def test_frame_rounding_can_represent_any_audio_length(self):
        self.m.validate_timeline([{'start':0,'end':1,'in':0,'out':1}],1.0205,tolerance=.5/24+.000001)

    def test_sidecar_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'film.srt').write_text('keep old captions')
            with self.assertRaises(ValueError):self.m.new_outputs(p,'film.mp4',['.srt','.qc.json'])
            self.assertEqual((p/'film.srt').read_text(),'keep old captions')

    def test_mix_cannot_use_unapproved_voice(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);m=self.m;w=m.w;w.init(p);a=p/'a.txt';a.write_text('approved')
            for n in range(1,11):
                w.prepare(p,n,[a]);w.approve(p,n,'couple' if n==3 else 'producer','合成测试确认')
            voice=p/'unapproved.wav';voice.write_text('changed voice')
            with patch.object(m,'duration',side_effect=AssertionError('先校验版本')):
                with self.assertRaises(ValueError):m.mix(p,voice,a,'mixed.wav')

    def test_mix_cannot_use_unapproved_music(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);m=self.m;w=m.w;w.init(p);voice=p/'voice.txt';voice.write_text('approved narration')
            music=p/'approved-music.txt';music.write_text('approved music')
            for n in range(1,11):
                w.prepare(p,n,[music] if n==10 else [voice]);w.approve(p,n,'couple' if n==3 else 'producer','合成测试确认')
            other=p/'other-music.txt';other.write_text('not approved')
            with patch.object(m,'duration',side_effect=AssertionError('先校验音乐版本')):
                with self.assertRaises(ValueError):m.mix(p,voice,other,'mixed.wav')

    def test_tts_stream_rejects_non_object_event(self):
        for events in [['not-an-object'],[{'code':0,'data':base64.b64encode(b'abc').decode()},'bad',{'code':20000000}]]:
            with self.assertRaises(ValueError):self.m.decode_tts(events)

    def test_ass_payload_uses_measured_layout_and_escapes_markup(self):
        font=self.m.font_path() or self.m.font_path('en')
        if not font:self.skipTest('font unavailable')
        cues=[{'start':0,'end':1.5,'text':'测试{字幕}'}]
        face,items=self.m.layout_captions(cues,640,360,font,'zh')
        ass=self.m.build_ass(cues,640,360,face,items)
        self.assertIn('PlayResX: 640',ass)
        self.assertIn('Dialogue: 0,0:00:00.00,0:00:01.50',ass)
        self.assertIn('\\{',ass)
        self.assertEqual(self.m.ass_text(['first','second']),'first\\Nsecond')

    def test_qc_media_strips_absolute_paths(self):
        info={'format':{'filename':'C:/private/final.mp4','duration':'6'},'streams':[{'codec_type':'video','width':640}]}
        clean=self.m.qc_media(info)
        self.assertNotIn('filename',clean['format'])
        self.assertEqual(clean['format']['duration'],'6')

    def test_kimi_adapter_official_endpoint_and_audit(self):
        import contextlib,io
        m=self.m;w=m.w
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);w.init(p)
            f=p/'facts.txt';f.write_text('合成事实')
            w.prepare(p,1,[f]);w.approve(p,1,'producer','合成测试确认')
            prompt=p/'prompt.txt';prompt.write_text('保密提示词正文')
            seen={}
            @contextlib.contextmanager
            def fake(url,headers,payload):
                seen['url']=url;seen['headers']=headers
                yield io.StringIO(json.dumps({'choices':[{'finish_reason':'stop','content':'两句测试文案'}]}))
            with patch.dict('os.environ',{'MOONSHOT_API_KEY':'synthetic-moonshot-key'}),patch.object(m,'request',fake):
                out=m.kimi(p,prompt,'draft.txt',True)
            self.assertEqual(out.read_text(),'两句测试文案')
            self.assertTrue(seen['url'].startswith('https://api.moonshot.'))
            self.assertEqual(seen['headers']['Authorization'],'Bearer synthetic-moonshot-key')
            log=(p/'AUDIT_LOG.jsonl').read_text(encoding='utf-8')
            self.assertIn('"kimi"',log)
            self.assertNotIn('synthetic-moonshot-key',log)
            self.assertNotIn('保密提示词正文',log)

    def test_doubao_adapter_app_key_mode_and_audit(self):
        import contextlib,io
        m=self.m;w=m.w
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);w.init(p)
            script=p/'script.txt';script.write_text('保密旁白正文')
            for n in range(1,4):
                w.prepare(p,n,[script]);w.approve(p,n,'couple' if n==3 else 'producer','合成测试确认')
            direction=p/'direction.txt';direction.write_text('自然')
            audio=b'synthetic-audio'
            events=[{'code':0,'data':base64.b64encode(audio).decode()},{'code':20000000}]
            seen={}
            @contextlib.contextmanager
            def fake(url,headers,payload):
                seen['headers']=headers
                yield io.StringIO('\n'.join(json.dumps(e,ensure_ascii=False) for e in events))
            env={'DOUBAO_API_KEY':'','DOUBAO_APP_ID':'synthetic-app','DOUBAO_ACCESS_KEY':'synthetic-access'}
            with patch.dict('os.environ',env),patch.object(m,'request',fake):
                out=m.tts(p,script,direction,'zh_female_test',0,'voice.mp3',True)
            self.assertEqual(out.read_bytes(),audio)
            self.assertTrue(out.with_suffix('.timing.json').is_file())
            self.assertEqual(seen['headers']['X-Api-App-Id'],'synthetic-app')
            log=(p/'AUDIT_LOG.jsonl').read_text(encoding='utf-8')
            self.assertIn('"tts"',log)
            self.assertNotIn('synthetic-access',log)
            self.assertNotIn('保密旁白正文',log)

    def test_audit_log_appends_jsonl_without_secrets(self):
        m=self.m
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            m.audit.record(p,'kimi',model='kimi-k3',chars=12)
            m.audit.record(p,'mix',out='full.wav',gain=.16)
            lines=(p/'AUDIT_LOG.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines),2)
            self.assertEqual([json.loads(x)['action'] for x in lines],['kimi','mix'])
            self.assertIn('at',json.loads(lines[0]))

if __name__=='__main__':unittest.main()
