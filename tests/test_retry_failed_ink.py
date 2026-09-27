import unittest
from unittest.mock import patch

import cv2
import numpy as np

from tools.answer_count_search import has_retry_history, needs_search
from tools.circle_inner_search import eligible
from tools.retry_failed_ink import connected_frame, reconcile, size_image
from tests.test_stage_classification import StageClassificationTest


class RetryFailedInkTest(unittest.TestCase):
    def test_height_units_padding_and_history_across_searches(self):
        gray=np.full((40,30),255,np.uint8);gray[5:21,10:14]=0
        self.assertIsNone(size_image(gray,20)[0])  # actual grading ink height ==8
        image,height=size_image(gray,21)
        self.assertEqual(height,8.4);self.assertEqual(image.shape,(88,58))
        self.assertTrue(np.all(image[:24]==255));self.assertTrue(np.all(image[-24:]==255))
        crop=StageClassificationTest().crop(text='0',score=.2)
        alignment=dict(matrix=[[1]],inliers=31,median_error=1)
        for key in ('circle_search','count_search','retry_search'):
            row=dict(crop,**{key:dict(attempts=0)})
            self.assertTrue(has_retry_history(row))
            self.assertFalse(eligible(row))
            self.assertFalse(needs_search([row],2,alignment))

    def test_frame_can_touch_inner_ink_and_numeric_conflict_survives(self):
        gray=np.full((120,120),255,np.uint8)
        cv2.rectangle(gray,(10,10),(110,110),0,3)
        cv2.line(gray,(60,10),(60,85),0,3)
        inside=np.zeros_like(gray,dtype=bool);inside[15:106,15:106]=True
        boundary=np.zeros_like(gray,dtype=np.uint8)
        cv2.rectangle(boundary,(10,10),(110,110),1,5)
        with patch('tools.retry_failed_ink.enclosures',return_value=[(inside,boundary.astype(bool),dict(kind='rectangle'))]):
            result,trace=connected_frame(gray,gray,[5,5,115,18])
        self.assertEqual(trace['status'],'frame_removed')
        self.assertEqual(result[80,60],0);self.assertEqual(result[10,60],255)
        crop=StageClassificationTest().crop
        old=crop(text='1',score=.2);new=crop(text='3',score=.8,input='x.png',input_sha256='hash')
        result=reconcile(old,new,dict(method='resize'))
        self.assertEqual(result['reread_conflict'],[[1],[3]])
        self.assertFalse(result['retry_search']['adopted'])
        self.assertNotIn('circle_search',result)
        result=reconcile(crop(text='0',score=.99),new,{})
        self.assertEqual(result['text'],'3');self.assertEqual(result['retry_search']['attempts'],1)
        self.assertEqual(reconcile(old,dict(new,score=.79),{})['text'],'1')


if __name__=='__main__':unittest.main()
