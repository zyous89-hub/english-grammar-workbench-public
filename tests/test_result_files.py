from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.result_files import (ResultFileError, atomic_json, load_result, load_state,
                              save_correction, validate_result, write_result)
from tools.export_result import export
from tools.serve_result_review import make_server
from tools.package_result_review import package


class ResultFilesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        shutil.copytree(Path(__file__).parent/'fixtures/result-demo',self.root,dirs_exist_ok=True)
        self.path=self.root/'result.json';self.initial=load_result(self.path)

    def correction(self, state=None, answer='2,3', judgement='정답'):
        state=state or load_state(self.path)
        return save_correction(self.path,'demo-q1',answer,judgement,'확인함',state['revision'],state['result']['result_id'])

    def test_portable_screen_embeds_exact_images_and_keeps_input_files(self):
        import base64
        self.correction()
        saved=(self.root/'teacher-corrections.json').read_bytes()
        result=deepcopy(self.initial)
        result['questions'][0]['reasons'][0]['message']='</script><script>unsafe()</script>'
        atomic_json(self.path,result)
        output=self.root/'portable.html'
        meta=package(self.path,output)
        page=output.read_text(encoding='utf-8')
        self.assertEqual(meta['images'],1)
        self.assertNotIn('</script><script>unsafe()',page)
        payload=json.loads(page.split('const portableData=',1)[1].split(';\n',1)[0])
        self.assertEqual(base64.b64decode(payload['images']['evidence/demo.png'].split(',')[1]),(self.root/'evidence/demo.png').read_bytes())
        self.assertEqual((self.root/'teacher-corrections.json').read_bytes(),saved)
        self.assertIn("connect-src 'none'",page)
        with self.assertRaises(FileExistsError):package(self.path,output)

    def test_unknown_reason_is_data_and_duplicate_ids_paths_are_rejected(self):
        result=deepcopy(self.initial)
        result['questions'][0]['reasons'].append(dict(code='FAKE-999',message='<script>가짜 사유</script>',stage=2))
        validate_result(result,self.root)
        self.assertEqual(result['questions'][0]['reasons'][-1]['message'],'<script>가짜 사유</script>')
        for path in ('../secret.png','/secret.png','C:/secret.png','https://example.com/a.png','evidence/../secret.png','evidence\\x.png'):
            broken=deepcopy(result);broken['questions'][0]['evidence_images'][0]['path']=path
            with self.assertRaises(ResultFileError): validate_result(broken,self.root)
        broken=deepcopy(result);broken['questions']*=2
        with self.assertRaises(ResultFileError): validate_result(broken,self.root)
        self.path.write_text('{"schema_version":1,"schema_version":1}',encoding='utf-8')
        with self.assertRaises(ResultFileError): load_result(self.path)

    def test_teacher_survives_regrade_and_only_difference_is_displayed(self):
        state=self.correction();self.assertTrue(state['rows'][0]['differs'])
        saved=(self.root/'teacher-corrections.json').read_bytes()
        new=deepcopy(self.initial);new['result_id']='new-run';q=new['questions'][0]
        q.update(read_answer='4',judgement='오답',rules_version='new-rules',review_stage=None,reasons=[])
        write_result(self.path,new)
        self.assertEqual((self.root/'teacher-corrections.json').read_bytes(),saved)
        row=load_state(self.path)['rows'][0]
        self.assertEqual(row['effective'],dict(read_answer='2,3',judgement='정답'))
        self.assertEqual(row['automatic']['read_answer'],'4');self.assertTrue(row['differs'])
        new['result_id']='matching-run';q.update(read_answer='2,3',judgement='정답')
        write_result(self.path,new)
        self.assertFalse(load_state(self.path)['rows'][0]['differs'])
        new['result_id']='removed-question';new['questions']=[];write_result(self.path,new)
        self.assertEqual(load_state(self.path)['orphaned'],['demo-q1'])
        self.assertEqual((self.root/'teacher-corrections.json').read_bytes(),saved)

    def test_stale_editor_wrong_assessment_and_corrupt_corrections_preserve_files(self):
        old=load_state(self.path);self.correction();saved=(self.root/'teacher-corrections.json').read_bytes()
        with self.assertRaises(ResultFileError): self.correction(old,answer='5')
        self.assertEqual((self.root/'teacher-corrections.json').read_bytes(),saved)
        state=load_state(self.path);new=deepcopy(self.initial);new['result_id']='new-run';write_result(self.path,new)
        with self.assertRaises(ResultFileError): self.correction(state)
        wrong=deepcopy(new);wrong.update(assessment_id='different-student',result_id='wrong-run')
        with self.assertRaises(ResultFileError): write_result(self.path,wrong)
        correction_path=self.root/'teacher-corrections.json';correction_path.write_text('{broken',encoding='utf-8')
        with self.assertRaises(ResultFileError): self.correction(state)
        self.assertEqual(correction_path.read_text(encoding='utf-8'),'{broken')
        correction_path.write_bytes(saved);bad=json.loads(saved);bad['assessment_id']='other';atomic_json(correction_path,bad)
        with self.assertRaises(ResultFileError): load_state(self.path)

    def test_engine_export_excludes_transcription_and_does_not_write_teacher_file(self):
        comparison=self.root/'comparison.json';classification=self.root/'classification.json'
        payload={'rows':[dict(id='demo-q1',page=1,expected='NEVER_EXPORT_TRANSCRIPTION',context='evidence/demo.png',
            review=dict(status='보류',proposed_selection=[2],key=[2,3],stage=4,candidates=[],
                        reasons=[dict(code='14',stage=4,crop_ids=[])]))]}
        atomic_json(comparison,payload);atomic_json(classification,{'runs':[{'questions':[{'id':'demo-q1'}],'regions':[]}]})
        self.correction();saved=(self.root/'teacher-corrections.json').read_bytes()
        export(comparison,classification,self.root,self.initial['assessment_id'],'engine-rules-2')
        output=self.path.read_text(encoding='utf-8')
        self.assertNotIn('NEVER_EXPORT_TRANSCRIPTION',output)
        self.assertEqual((self.root/'teacher-corrections.json').read_bytes(),saved)
        self.assertEqual(load_result(self.path)['questions'][0]['reasons'][0]['message'],'선택 개수 불일치')

    def test_http_unknown_reason_and_protected_save(self):
        result=deepcopy(self.initial);result['questions'][0]['reasons'].append(dict(code='FAKE-999',message='앱을 바꾸지 않은 새 사유',stage=3))
        atomic_json(self.path,result)
        server=make_server(self.path,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join()))
        url=f'http://127.0.0.1:{server.server_port}'
        page=urlopen(url).read().decode('utf-8');token=re.search('nonce="([^"]+)"',page)[1]
        state=json.loads(urlopen(url+'/api/state').read())
        self.assertEqual(state['rows'][0]['automatic']['reasons'][-1]['code'],'FAKE-999')
        data=json.dumps(dict(question_id='demo-q1',read_answer='2,3',judgement='정답',note='웹 저장',
                             revision=state['revision'],result_id=result['result_id'])).encode()
        with self.assertRaises(HTTPError):urlopen(Request(url+'/api/correction',data=data))
        response=urlopen(Request(url+'/api/correction',data=data,headers={'Origin':url,'X-Review-Token':token,'Content-Type':'application/json'}))
        self.assertEqual(json.loads(response.read())['rows'][0]['effective']['read_answer'],'2,3')
        self.assertTrue((self.root/'teacher-corrections.json').exists())
