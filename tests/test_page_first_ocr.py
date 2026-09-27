import unittest
import json
import tempfile
from pathlib import Path
import cv2
import numpy as np

from tools.page_first_ocr import page_regions, associate, assign
from tests import test_stage_classification as stage_tests


class PageFirstTests(unittest.TestCase):
    def test_area_thresholds_keep_ties_and_unmatched_ink_for_review(self):
        questions=[dict(id='upper',zone=[0,0,100,60]),dict(id='lower',zone=[0,60,100,100])]
        for threshold in (.5,.6):
            result=associate([0,0,100,100],questions,threshold)
            self.assertEqual(result['status'],'assigned')
            self.assertEqual([c['question_id'] for c in result['candidates']],['upper'])
            self.assertEqual(len(result['intersections']),2)
        self.assertEqual(associate([0,0,100,100],questions,.7)['status'],'ambiguous')
        self.assertEqual(associate([0,20,100,100],questions,.5)['status'],'ambiguous')
        self.assertEqual(associate([110,0,120,20],questions,.5)['status'],'unassigned')
        self.assertEqual(associate([-10,0,10,20],questions,.5)['status'],'assigned')
        self.assertEqual(associate([-10,0,10,20],questions,.6)['status'],'outside_zone')
        for threshold in (0,.49,1.1,float('nan')):
            with self.assertRaises(ValueError):associate([0,0,10,10],questions,threshold)

    def test_crossing_ink_is_not_cut_and_assignment_never_picks_a_winner(self):
        blank=np.full((160,160),255,np.uint8);student=blank.copy()
        cv2.rectangle(student,(40,60),(75,115),0,2)
        crops=page_regions(student,blank)
        self.assertTrue(any(c['box'][1]<80<c['box'][3] for c in crops))
        questions=[dict(id='upper',zone=[0,0,160,80]),dict(id='lower',zone=[0,80,160,160])]
        crossing=next(c for c in crops if c['box'][1]<80<c['box'][3])
        result=associate(crossing['ink_box'],questions)
        self.assertEqual(result['status'],'ambiguous')
        self.assertEqual({c['question_id'] for c in result['candidates']},{'upper','lower'})
        self.assertEqual(associate([20,20,30,30],questions)['status'],'assigned')
        self.assertEqual(associate([-5,20,10,30],questions)['status'],'outside_zone')
        self.assertEqual(associate([170,20,180,30],questions)['status'],'unassigned')

    def test_unknown_ownership_stops_both_even_with_another_valid_answer(self):
        helper=stage_tests.StageClassificationTest()
        for text,score,reason in [('3',.99,(3,'15')),('',0,(2,'5')),('2',.2,(2,'6'))]:
            uncertain=helper.crop(id='crossing',text=text,score=score,ownership_review=True)
            self.assertEqual((uncertain['stage'],uncertain['reason']),reason)
            for order in [[uncertain,helper.crop(id='inside')],[helper.crop(id='inside'),uncertain]]:
                result=helper.review(order)
                self.assertEqual(result['status'],'보류')
                self.assertTrue(any(r['code']=='15' for r in result['reasons']))
        ignored=helper.crop(ownership_review=True,answer_excluded=True)
        self.assertEqual(ignored['stage'],1)

    def test_page_without_any_crops_keeps_its_questions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';recognized=root/'ocr';inputs=root/'inputs'
            for path in (source,recognized,inputs):path.mkdir()
            def save(path,data):path.write_text(json.dumps(data),encoding='utf-8')
            save(recognized/'results.json',[])
            save(recognized/'timing.json',{'inputs':str(inputs)})
            save(inputs/'provenance.json',{'pages':[5]})
            save(source/'questions.json',[dict(id='q1',page=5,zone=[0,0,20,20],key={'answer':'①'},context='context.jpg')])
            assign(source,recognized,root/'assigned')
            result=json.loads((root/'assigned/evaluation.json').read_text(encoding='utf-8'))
            self.assertEqual([q['id'] for q in result],['q1'])
            self.assertEqual(result[0]['status'],'보류')


if __name__=='__main__':
    unittest.main()
