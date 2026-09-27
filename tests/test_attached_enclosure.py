import unittest
from unittest.mock import patch
import cv2
import numpy as np
from tools.ocr_attached_enclosure import stable_reading, hull_strip, to_digit


class AttachedFrameTest(unittest.TestCase):
    def test_three_reads_must_agree_and_keep_middle_evidence(self):
        gray=np.full((100,100),255,np.uint8)
        cv2.rectangle(gray,(10,10),(90,90),0,3)
        cv2.line(gray,(50,10),(50,70),0,3)
        self.assertIsNotNone(hull_strip(gray,2.5))
        mask=np.zeros((50,20),np.uint8);mask[5:45,8:12]=255
        with patch('tools.ocr_attached_enclosure.hull_strip',return_value=mask):
            reads=[('②',.8),('2',.91),('②',.99)]
            calls=[]
            def ocr(image):
                self.assertEqual(image.shape[0],88)
                calls.append(image)
                return reads[len(calls)-1]
            self.assertEqual(stable_reading(gray,ocr),(reads[1],reads))
            self.assertEqual(len(calls),3)
            for values in ([('2',.99),('3',.99),('2',.99)], [('2',.99),('2',.799),('2',.99)], [('2',.99),('2.',.99),('2',.99)]):
                it=iter(values)
                self.assertIsNone(stable_reading(gray,lambda image:next(it)))
        with patch('tools.ocr_attached_enclosure.hull_strip',return_value=None):
            self.assertIsNone(stable_reading(gray,lambda image:self.fail('No content must not call OCR')))
        self.assertEqual(to_digit(' ⑤ '),'5')


if __name__=='__main__':unittest.main()
