import unittest
from unittest.mock import patch
import cv2
import numpy as np

from tools.circle_inner_search import eligible, inner_image, reconcile
from tests import test_stage_classification as stage_tests


class CircleInnerSearchTest(unittest.TestCase):
    def test_trigger_keeps_existing_gates_and_threshold(self):
        crop = stage_tests.StageClassificationTest().crop
        for text in ('0', '０', '①', '⑧', '①③'):
            self.assertTrue(eligible(crop(text=text, score=.79)), text)
        for text in ('O', '1', 'ⓐ', '?', '10'):
            self.assertFalse(eligible(crop(text=text, score=.2)), text)
        for change in (dict(score=.8), dict(score=.9), dict(score=None), dict(score=float('nan')),
                       dict(empty=True), dict(answer_excluded=True), dict(route='choice_mark_review'),
                       dict(preserved_choices=[{'symbol':'①'}]), dict(semantic_annotation={'unknown':True}),
                       dict(circle_search={'attempts':1})):
            self.assertFalse(eligible(crop(text='①', score=.2) | change))

    def test_keep_all_inside_strokes_and_reject_contact_or_alternative_rings(self):
        gray = np.full((140,140),255,np.uint8)
        cv2.circle(gray,(70,70),45,0,2)
        cv2.line(gray,(65,50),(65,85),0,3)
        with patch('tools.circle_inner_search.connected_circles', return_value=[{'ellipse':((70,70),(90,90),0)}]):
            image, evidence = inner_image(gray)
            self.assertIsNotNone(image)
            self.assertEqual(evidence['components'],1)
            # A second disconnected internal stroke is retained, never chosen away.
            cv2.line(gray,(78,50),(78,85),0,3)
            image, evidence = inner_image(gray)
            self.assertEqual(evidence['components'],2)
            cv2.line(gray,(65,50),(65,25),0,3)
            self.assertIsNone(inner_image(gray)[0])
        self.assertIsNone(inner_image(np.full((140,140),255,np.uint8))[0])
        # Two separate enclosed answers must not yield one selected inner answer.
        gray = np.full((160,280),255,np.uint8)
        rings=[]
        for x in (70,210):
            cv2.circle(gray,(x,80),40,0,2); cv2.line(gray,(x,60),(x,95),0,3)
            rings.append({'ellipse':((x,80),(80,80),0)})
        with patch('tools.circle_inner_search.connected_circles', return_value=rings):
            self.assertIsNone(inner_image(gray)[0])

    def test_reread_is_not_forced_and_conflicts_hold_even_if_new_score_is_high(self):
        crop = stage_tests.StageClassificationTest().crop
        extra = crop(text='1',score=.95,input='inner.png',input_sha256='hash')
        result = reconcile(crop(text='0',score=.2), extra, {})
        self.assertEqual(result['text'],'1')
        self.assertEqual(result['input'] if 'input' in result else None,None)
        self.assertTrue(result['circle_search']['adopted'])
        self.assertEqual(reconcile(crop(text='0',score=.2),dict(extra,score=.79),{})['text'],'0')
        conflict = reconcile(crop(text='③',score=.2),extra,{})
        self.assertEqual(conflict['text'],'③')
        self.assertEqual(conflict['reread_conflict'],[[3],[1]])
        self.assertFalse(conflict['circle_search']['adopted'])
