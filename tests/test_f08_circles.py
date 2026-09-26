import unittest
import cv2
import numpy as np

from tools.compare_f08_circles import circles, connected_circles, duplicate, exemptions
from tools.classify_grid_stages import question_review
from tests import test_stage_classification as stage_tests


class CircleExperimentTest(unittest.TestCase):
    def test_connected_ring_and_non_circle_marks(self):
        for name in ('circle_box','box','number','check','blank'):
            image=np.full((160,160),255,np.uint8)
            if name in ('circle_box','box'):
                cv2.rectangle(image,(25,20),(135,140),0,3)
            if name=='circle_box':
                cv2.ellipse(image,(75,80),(50,50),0,0,315,0,3)
            if name in ('circle_box','box','number'):
                cv2.putText(image,'5',(60,100),cv2.FONT_HERSHEY_SIMPLEX,1.2,0,3)
            if name=='check':
                cv2.polylines(image,[np.array([[30,70],[55,100],[120,25]])],False,0,3)
            self.assertEqual(bool(connected_circles(image)),name=='circle_box',name)

    def test_duplicate_and_extra_inner_ink(self):
        image=np.full((100,100),255,np.uint8)
        cv2.circle(image,(50,50),36,0,2)
        cv2.line(image,(50,40),(50,60),0,3)
        detected=circles(image)
        self.assertTrue(detected)
        blocker={'box':[0,0,100,100]}; candidate={'box':[43,36,57,64]}
        self.assertTrue(duplicate(blocker,candidate,image,detected))
        cv2.line(image,(30,45),(30,55),0,3)
        self.assertFalse(duplicate(blocker,candidate,image,detected))
        self.assertFalse(duplicate(blocker,{'box':[-2,36,57,64]},image,detected))
        self.assertEqual(circles(np.full((100,100),255,np.uint8)),[])

    def test_broad_and_narrow_exemptions_keep_other_stops(self):
        helper=stage_tests.StageClassificationTest()
        good=helper.crop(id='number',box=[40,40,60,60])
        bad=helper.crop(id='ring',box=[0,0,100,100],score=.2)
        evidence={'ring':{'circles':[{'ellipse':((50,50),(72,72),0)}],'duplicates':[]}}
        self.assertEqual(exemptions([good,bad],evidence,'broad'),['ring'])
        self.assertEqual(exemptions([good,bad],evidence,'duplicate'),[])
        aligned=dict(matrix=[[1]],inliers=31,median_error=1)
        self.assertIsNone(question_review([good,bad],'3',aligned)['selection'])
        self.assertEqual(question_review([good,bad],'3',aligned,f08_exemptions=['ring'])['selection'],[3])
        other=helper.crop(id='other',text='2',box=[200,0,210,10])
        self.assertIsNone(question_review([good,bad,other],'3',aligned,f08_exemptions=['ring'])['selection'])
        bad['semantic_annotation']={'meaning':'do_not_know'}
        self.assertIsNone(question_review([good,bad],'3',aligned,f08_exemptions=['ring'])['selection'])
        self.assertIsNone(question_review([good,bad],'?',aligned,f08_exemptions=['ring'])['selection'])

    def test_partial_overlap_cannot_be_duplicate(self):
        # Shape-independent containment guard, including the prior q36 geometry.
        image=np.full((46,38),255,np.uint8)
        self.assertFalse(duplicate({'box':[722,351,741,374]},
                                   {'box':[733,337,754,358]},image,[]))


if __name__=='__main__':
    unittest.main()
