import unittest
from unittest.mock import patch

import numpy as np

from tools.ocr_circle_strip import eligible, circle_strip_reading, peeled_circle_strip_reading, size_stable_reading
from tools.ocr_retry_preprocess import normalise


class CircleStripTest(unittest.TestCase):
    def test_C_one_hull_two_sizes_and_fixed_second_read(self):
        mask=np.zeros((50,25),np.uint8);mask[5:45,5:20]=255
        with patch('tools.ocr_circle_strip.hull_strip',return_value=mask) as hull:
            inputs=[];reads=iter([('④',.908),('④',.847)])
            def ocr(image):
                inputs.append(image)
                return next(reads)
            self.assertEqual(size_stable_reading(255-mask,ocr),
                             (('④',.847),[('④',.908),('④',.847)]))
            self.assertEqual(hull.call_count,1)
            self.assertEqual(hull.call_args.args[1],2.5)
            self.assertEqual([x.shape for x in inputs],[(72,63),(88,63)])
            for values in ([('2',.99),('3',.99)],[('3',.799),('3',.99)],[('6',.99),('6',.99)]):
                it=iter(values)
                self.assertIsNone(size_stable_reading(255-mask,lambda image:next(it)))
        with patch('tools.ocr_circle_strip.hull_strip',return_value=None):
            self.assertIsNone(size_stable_reading(255-mask,lambda image:self.fail('No mask')))

    def test_two_padding_benchmark_and_entry_gate(self):
        row=dict(route='student_candidate',empty=False,answer_excluded=False,
                 preserved_choices=[],text='③',score=.7)
        self.assertTrue(eligible(row))
        self.assertTrue(eligible(dict(row,text='0',score=.99)))
        for changes in ({'text':'','score':0.0},{'text':'3'},{'score':.8},
                        {'route':'choice_mark_review'},{'empty':True},{'answer_excluded':True},
                        {'preserved_choices':[{'symbol':'①'}]},
                        {'preserved_choices':[{'symbol':'ⓩ'}]}):
            self.assertFalse(eligible(dict(row,**changes)))
        mask=np.zeros((55,25),np.uint8);mask[6:46,5:20]=255
        gray=255-mask
        for method,argument,calls in [(circle_strip_reading,gray,2),(peeled_circle_strip_reading,mask,1)]:
            with patch('tools.ocr_circle_strip.hull_strip',return_value=mask) as strip:
                sizes=[];reads=iter([('②',.991),('2',.984)])
                def ocr(image):
                    sizes.append(image.shape)
                    if len(sizes)==2:np.testing.assert_array_equal(image,normalise(mask))
                    return next(reads)
                self.assertEqual(method(argument,ocr),(('2',.984),[('②',.991),('2',.984)]))
                self.assertEqual(sizes,[(72,63),(88,63)])
                self.assertEqual(strip.call_count,calls)
                self.assertTrue(all(c.args[1]==2.5 for c in strip.call_args_list))
                for outputs in ([('6',.623),('6',.747)],[('1',.246),('1',.233)],
                                [('2',.99),('3',.99)],[('1',.799),('1',.86)]):
                    it=iter(outputs)
                    self.assertIsNone(method(argument,lambda image:next(it)))
            with patch('tools.ocr_circle_strip.hull_strip',return_value=None):
                self.assertIsNone(method(argument,lambda image:self.fail('No mask must not call OCR')))


if __name__=='__main__':unittest.main()
