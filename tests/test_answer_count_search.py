import unittest
import numpy as np

from tools.answer_count_search import needs_search, reconcile, reread_image
from tools.classify_grid_stages import required_answer_count, question_review
from tests import test_stage_classification as stage_tests


class CountSearchTest(unittest.TestCase):
    def setUp(self):
        self.crop = stage_tests.StageClassificationTest().crop
        self.alignment = dict(matrix=[[1]], inliers=31, median_error=2)

    def test_instruction_count_not_passage_option_or_key(self):
        for text,n in [('1. 알맞은 것은? (정답 2\n개)1) ① 설명',2),
                       ('정답 2개',2),('12개를 고르시오.',None),
                       ('두 개를 고르시오. ① 하나',2),('정답은 세 개를 고르세요.',3),
                       ('옳은 것을 모두 고르면? ① 정답 2개',None),
                       ('다음 두 문장을 연결한 것은? ① 답',None),
                       ('옳은 것은? 지문에는 정답 2개라는 말이 있다.',None),
                       ('정답 2개 또는 정답 3개를 고르시오.',None)]:
            self.assertEqual(required_answer_count(text),n,text)

    def test_search_is_bounded_and_does_not_merge(self):
        a=self.crop()
        self.assertTrue(needs_search([a],2,self.alignment))
        self.assertFalse(needs_search([self.crop(text='1,3')],2,self.alignment))
        self.assertFalse(needs_search([self.crop(text='1,2,3')],2,self.alignment))
        self.assertFalse(needs_search([a,self.crop(id='b',text='1')],2,self.alignment))
        self.assertFalse(needs_search([a],None,self.alignment))
        self.assertFalse(needs_search([dict(a,count_search={'attempts':1})],2,self.alignment))
        self.assertFalse(needs_search([a],2,dict(self.alignment,inliers=0)))
        self.assertFalse(needs_search([dict(a,semantic_annotation={'meaning':'unknown'})],2,self.alignment))

    def test_reread_recovery_and_conflict_not_best_score(self):
        old=self.crop(text='1',score=.95)
        new=self.crop(text='1,3',score=.99,input='retry.png',input_sha256='test')
        merged=reconcile(old,new)
        self.assertEqual(merged['text'],'1')
        self.assertEqual(merged['reread_conflict'],[[1],[1,3]])
        review=question_review([merged],'1,3',self.alignment,expected_count=2)
        self.assertIsNone(review['selection'])
        self.assertEqual({r['code'] for r in review['reasons']},{'10','14'})
        recovered=reconcile(self.crop(text='?',score=.3),new)
        self.assertEqual(recovered['text'],'1,3')
        self.assertNotIn('reread_conflict',recovered)

    def test_count_gate_preserves_extra_answer_and_other_failures(self):
        for text in ('1','1,2,3'):
            result=question_review([self.crop(text=text)],text,self.alignment,expected_count=2)
            self.assertEqual(result['reasons'][0]['code'],'14')
            self.assertIsNone(result['selection'])
        pair=self.crop(text='1,3')
        self.assertEqual(question_review([pair],'1,3',self.alignment,expected_count=2)['selection'],[1,3])
        result=question_review([pair,self.crop(id='third',text='5')],'1,3',self.alignment,expected_count=2)
        self.assertIsNone(result['selection'])
        self.assertEqual(result['reasons'][0]['code'],'10')

    def test_transform_keeps_every_nonwhite_pixel(self):
        gray=np.full((20,20),255,np.uint8);gray[5,6]=0;gray[10,12]=220
        transformed=reread_image(gray)
        self.assertEqual(np.sum(transformed==0),4)
        self.assertEqual(np.sum(transformed==220),4)
        self.assertIsNone(reread_image(np.full((20,20),255,np.uint8)))
