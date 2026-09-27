import copy
import unittest

from tools.page_first_ocr import enclosing_assignments


class EnclosingOwnershipTest(unittest.TestCase):
    def test_containment_uses_fixed_valid_candidates_and_never_breaks_owner_ties(self):
        def row(ident, box, **overrides):
            return dict(id=ident, box=box, page_id='page', empty=False, answer_excluded=False,
                        ocr_executed=True, text='3', score=.98, route='student_candidate', **overrides)

        def association(ident, owner=None):
            return dict(crop_id=ident, status='assigned' if owner else 'ambiguous',
                        candidates=[dict(question_id=owner, overlap_fraction=1)] if owner else [])

        for outer_box, inner_box, fraction in [([645,458,717,540],[669,482,694,515],1),
                                               ([559,1235,669,1340],[575,1267,669,1350],73/83)]:
            rows=[row('outer',outer_box),row('answer',inner_box)]
            rows[0].update(text='O',score=.2,route='choice_mark_review')
            associations=[association('outer'),association('answer','q')]
            changes=enclosing_assignments(rows,associations)
            self.assertEqual(changes[0]['question_id'],'q')
            self.assertAlmostEqual(changes[0]['anchors'][0]['covered_fraction'],fraction)
            self.assertEqual(associations[0]['status'],'assigned')
            for rejected in [dict(score=.79),dict(semantic_annotation={'meaning':'unknown'}),
                             dict(reread_conflict=[[2],[3]]),dict(retry_ownership_review=True),
                             dict(text='word3'),dict(route='choice_mark_review')]:
                invalid=copy.deepcopy(rows);invalid[1].update(rejected)
                self.assertEqual(enclosing_assignments(invalid,[association('outer'),association('answer','q')]),[])

        rows=[row('outer',[0,0,100,100]),row('a',[10,10,20,20]),row('b',[30,30,40,40])]
        self.assertEqual(enclosing_assignments(rows,[association('outer'),association('a','q1'),association('b','q2')]),[])
        same=[association('outer'),association('a','q1'),association('b','q1')]
        self.assertEqual(len(enclosing_assignments(rows,same)),1)
        rows[0]['empty']=True
        self.assertEqual(enclosing_assignments(rows,[association('outer'),association('a','q1'),association('b','q1')]),[])
        for width, expected in [(80,1),(79,0)]:
            rows=[row('outer',[0,0,width,100]),row('answer',[0,0,100,100])]
            self.assertEqual(len(enclosing_assignments(rows,[association('outer'),association('answer','q')])),expected)
        rows[0]['page_id']='other-page'
        self.assertEqual(enclosing_assignments(rows,[association('outer'),association('answer','q')]),[])

        # The newly assigned middle box must not become an anchor for the last box.
        rows=[row('middle',[0,0,100,100]),row('answer',[0,0,10,10]),row('last',[20,0,120,100])]
        associations=[association('middle'),association('answer','q'),association('last')]
        self.assertEqual([r['crop_id'] for r in enclosing_assignments(rows,associations)],['middle'])
        self.assertEqual(associations[2]['status'],'ambiguous')


if __name__=='__main__':
    unittest.main()
