import unittest
import cv2
import numpy as np
from tools.ocr_retry_preprocess import should_reread, peel_enclosures, whole_ink, normalise


class OtsuRetryTest(unittest.TestCase):
    def test_user_triggers_topology_and_exact_normalisation(self):
        self.assertTrue(should_reread('0',.99))
        for value in ('①','②③','O','D','ⓞ','@'):
            self.assertTrue(should_reread(value,.79))
            self.assertFalse(should_reread(value,.8))
        for value in ('','1','_','/','\\','①1','① ②'):
            self.assertFalse(should_reread(value,.2))
        gray=np.full((100,100),255,np.uint8)
        cv2.rectangle(gray,(8,8),(92,92),80,2)
        self.assertIsNone(peel_enclosures(gray))
        cv2.line(gray,(40,30),(40,70),80,2)
        mask=peel_enclosures(gray)
        self.assertIsNotNone(mask);self.assertEqual(mask[8,8],0)
        self.assertEqual(mask[50,40],255)
        image=normalise(mask)
        self.assertEqual(image.shape[0],88)
        self.assertTrue(np.all(image[:24]==255))
        self.assertTrue(np.all(image[-24:]==255))
        self.assertTrue(np.all(image[:,:24]==255))
        self.assertTrue(np.all(image[:,-24:]==255))
        self.assertGreater(np.count_nonzero(whole_ink(gray)),np.count_nonzero(mask))


if __name__=='__main__':unittest.main()
