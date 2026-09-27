import unittest
import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np

from tools.circle_inner_search import eligible, inner_image, reconcile, run
from tests import test_stage_classification as stage_tests


class CircleInnerSearchTest(unittest.TestCase):
    def test_page_reread_once_before_ownership_preserves_legacy_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';batch=root/'batch'
            (source/'pages').mkdir(parents=True);batch.mkdir()
            save=lambda p,v:p.write_text(json.dumps(v),encoding='utf-8')
            load=lambda p:json.loads(p.read_text(encoding='utf-8'))
            cv2.imwrite(str(source/'pages/C-01-original.png'),np.full((200,200),255,np.uint8))
            save(source/'pages.json',[dict(id='C-01',page=1,matrix=[[1]],inliers=31,median_error=2)])
            save(source/'questions.json',[dict(id='q1',set='C',page=1,zone=[0,0,200,100],key={'answer':'3'},context='context.jpg')])
            image=batch/'crop.png';cv2.imwrite(str(image),np.full((40,40),255,np.uint8))
            digest=hashlib.sha256(image.read_bytes()).hexdigest()
            crop=stage_tests.StageClassificationTest().crop
            row=crop(text='0',score=.2,page=1,page_id='C-01',box=[20,120,60,160],ink_box=[24,124,56,156],
                     input=str(image),input_sha256=digest,source_input=str(image),source_input_sha256=digest)
            save(batch/'results.json',[row,dict(row,id='outside',box=[20,190,60,210])])
            save(batch/'timing.json',{'inputs':str(batch)})
            save(batch/'provenance.json',{'pages':[1]})
            def recognize(command,check):
                prepared=load(Path(command[3])/'regions.json')
                self.assertEqual(len(prepared),1)
                output=Path(command[5]);output.mkdir()
                save(output/'results.json',[dict(prepared[0],text='3',score=.9,ocr_executed=True)])
            with patch('tools.circle_inner_search.inner_image',return_value=(np.full((40,40),255,np.uint8),dict(status='prepared'))), patch('tools.circle_inner_search.subprocess.run',side_effect=recognize) as ocr:
                run(batch,source,root/'page',root/'model')
                self.assertEqual(ocr.call_count,1)
                shared=root/'page/shared-batch';result=load(shared/'results.json')[0]
                self.assertNotIn('question_id',result)
                self.assertEqual(result['text'],'3')
                self.assertEqual(result['circle_search']['attempts'],1)
                outside=load(shared/'results.json')[1]['circle_search']
                self.assertEqual(outside,dict(status='alignment_or_bounds',attempts=0))
                self.assertEqual(load(shared/'timing.json'),load(batch/'timing.json'))
                with self.assertRaises(ValueError):run(shared,source,root/'repeat',root/'model')
                self.assertFalse((root/'repeat').exists())
                from tools.page_first_ocr import assign
                assign(source,shared,root/'assigned',minimum_overlap=.7)
                assigned=load(root/'assigned/results.json')[0]
                self.assertEqual(assigned['question_id'],'q1')
                self.assertTrue(assigned['circle_search']['adopted'])
                # Old question-crop calls still enforce their original zone.
                save(batch/'results.json',[dict(row,question_id='q1')]);save(batch/'evaluation.json',[])
                run(batch,source,root/'legacy',root/'model')
                self.assertEqual(ocr.call_count,1)
                self.assertEqual(load(root/'legacy/plan.json')['crops']['a']['status'],'alignment_or_bounds')

    def test_trigger_keeps_existing_gates_and_threshold(self):
        crop = stage_tests.StageClassificationTest().crop
        for text in ('0', '０', '①', '⑧', '①③', '1', 'O', 'ⓐ', '?', '10'):
            self.assertTrue(eligible(crop(text=text, score=.79)), text)
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
        self.assertEqual(reconcile(crop(text='0',score=.2),dict(extra,score=.8),{})['text'],'1')
        self.assertEqual(reconcile(crop(text='0',score=.2),dict(extra,text='@',score=.99),{})['text'],'0')
        conflict = reconcile(crop(text='③',score=.2),extra,{})
        self.assertEqual(conflict['text'],'③')
        self.assertEqual(conflict['reread_conflict'],[[3],[1]])
        self.assertFalse(conflict['circle_search']['adopted'])

    def test_e_relaxes_only_low_original_with_fixed_consensus_and_preserves_other_conflicts(self):
        crop = stage_tests.StageClassificationTest().crop
        old = crop(text='③', score=.4)
        extra = crop(text='2', score=.95, input='inner.png', input_sha256='hash')
        reads = [dict(pad_y=p, text='②', score=.8) for p in (16, 24)]
        evidence = dict(method='circle_strip_D-1', reads=reads, previous_retry={'status':'answer_conflict'})
        apply = lambda row=old, proof=evidence: reconcile(row, extra, proof, allow_low_confidence_consensus=True)
        self.assertEqual(reconcile(old, extra, evidence)['text'], '③')  # Opt-in only.
        for method in ('size_stable_C', 'circle_strip_D-1', 'circle_strip_D-2', 'hull_stable', 'enclosure'):
            proof = dict(evidence, method=method)
            if method == 'hull_stable':
                proof['reads'] = [dict(k=k, text='2', score=.8) for k in (2, 2.5, 3)]
            if method == 'enclosure':
                proof['confirmation_reads'] = reads
            result = apply(proof=proof)
            self.assertEqual(result['text'], '2', method)
            self.assertTrue(result['circle_search']['low_confidence_consensus'])
            self.assertEqual(result['circle_search']['previous_retry'], evidence['previous_retry'])
            self.assertNotIn('reread_conflict', result)
        for score in (.8, .99, None, float('nan'), float('inf')):
            result = apply(row=dict(old, score=score))
            self.assertEqual(result['text'], '③')
            self.assertEqual(result['reread_conflict'], [[3], [2]])
        for proof in (
                dict(evidence, reads=[]), dict(evidence, reads=reads[:1]),
                dict(evidence, method='unknown'), dict(evidence, method='enclosure'),
                dict(evidence, reads=[reads[0], dict(reads[1], pad_y=16)]),
                dict(evidence, reads=[reads[0], dict(reads[1], text='3', score=.99)]),
                dict(evidence, reads=[reads[0], dict(reads[1], text='6')]),
                dict(evidence, reads=[reads[0], dict(reads[1], score=.79)]),
                dict(evidence, reads=[reads[0], dict(reads[1], score=float('nan'))]),
                dict(evidence, reads=[reads[0], dict(reads[1], score=None)])):
            self.assertEqual(apply(proof=proof)['text'], '③', proof)
        self.assertNotIn('reread_conflict', apply(row=dict(old, reread_conflict=[[3], [2]])))
        self.assertEqual(apply(row=dict(old, reread_conflict=[[3], [1]]))['reread_conflict'], [[3], [1]])
        accepted = crop(**apply())  # Reclassify the updated OCR as the pipeline does.
        from tools.classify_grid_stages import question_review
        review = question_review([accepted, crop(id='other', text='4')], '2',
                                 dict(matrix=[[1]], inliers=31, median_error=2))
        self.assertIsNone(review['selection'])
        self.assertTrue(any(r['rule'] == 'F06' for r in review['reasons']))
        self.assertEqual(old['text'], '③')
        self.assertNotIn('reread_conflict', old)

    def test_e_keeps_multiple_original_digits_held_after_single_digit_consensus(self):
        crop = stage_tests.StageClassificationTest().crop
        extra = crop(text='4', score=.984, input='inner.png', input_sha256='hash')
        proof = dict(method='hull_stable',
                     reads=[dict(k=k, text='4', score=.984) for k in (2, 2.5, 3)])
        from tools.classify_grid_stages import question_review
        for text in ('①④', '①②③', '1,4', '1 4', '(1)', '1.'):
            result = reconcile(crop(text=text, score=.633), extra, proof,
                               allow_low_confidence_consensus=True)
            self.assertEqual(result['text'], text)
            self.assertIn('reread_conflict', result)
            self.assertFalse(result['circle_search']['adopted'])
            self.assertFalse(result['circle_search'].get('low_confidence_consensus', False))
            review = question_review([crop(**result)], '4',
                                     dict(matrix=[[1]], inliers=31, median_error=2))
            self.assertIsNone(review['selection'])
            self.assertTrue(any(r['rule'] == 'F06(re-read)' for r in review['reasons']))

    def test_rectangles_nested_frames_and_digit_holes(self):
        gray = np.full((180,180),255,np.uint8)
        cv2.rectangle(gray,(15,15),(165,165),0,3)
        cv2.line(gray,(80,65),(80,115),0,3)
        image, evidence = inner_image(gray)
        self.assertIsNotNone(image)
        self.assertIn('rectangle', {s['kind'] for s in evidence['shapes']})
        # Separate nested circle and square are both frames, not extra answers.
        cv2.circle(gray,(90,90),50,0,2)
        nested, evidence = inner_image(gray)
        self.assertIsNotNone(nested)
        self.assertEqual(evidence['components'],1)
        np.testing.assert_array_equal(nested,image)
        # A plain digit's own closed space is never erased as an enclosing frame.
        for digit in ('0','6','8','9'):
            bare=np.full((180,180),255,np.uint8)
            cv2.putText(bare,digit,(35,140),cv2.FONT_HERSHEY_SIMPLEX,4,0,5)
            self.assertIsNone(inner_image(bare)[0],digit)
        # Ink connected to the square must not be cut free and reinterpreted.
        touching=np.full((180,180),255,np.uint8)
        cv2.rectangle(touching,(15,15),(165,165),0,3)
        cv2.line(touching,(80,15),(80,115),0,3)
        self.assertIsNone(inner_image(touching)[0])
        tilted=np.full((180,180),255,np.uint8)
        cv2.polylines(tilted,[np.array([[20,80],[90,20],[160,100],[90,160]])],True,0,3)
        cv2.line(tilted,(80,65),(80,115),0,3)
        self.assertIsNotNone(inner_image(tilted)[0])

    def test_new_candidate_still_passes_through_question_conflicts_and_count(self):
        crop=stage_tests.StageClassificationTest().crop
        answer=crop(text='3',score=.8)
        alignment=dict(matrix=[[1]],inliers=31,median_error=2)
        from tools.classify_grid_stages import question_review
        result=question_review([answer,crop(id='other',text='5')],'3',alignment)
        self.assertIsNone(result['selection'])
        self.assertTrue(any(r['code']=='10' for r in result['reasons']))
        result=question_review([answer],'3,5',alignment,expected_count=2)
        self.assertIsNone(result['selection'])
        self.assertTrue(any(r['code']=='14' for r in result['reasons']))
        result=question_review([answer,crop(id='mark',text='?',score=.2)],'3',alignment)
        self.assertIsNone(result['selection'])
        self.assertTrue(any(r['rule']=='F08(b)' for r in result['reasons']))
