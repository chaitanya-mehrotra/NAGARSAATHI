"""Do not equate a similar-looking road background with the same defect."""
import unittest

from PIL import Image
from backend.evaluate_matching import controlled_pairs, passes
from backend.visual_matching import compare_defects


class VisualMatchingTests(unittest.TestCase):
    def test_known_transform_matches_and_unrelated_source_does_not(self):
        pairs = iter(controlled_pairs())
        a,b,da,db,_ = next(pairs)
        self.assertTrue(passes(compare_defects(a,da,b,db)))
        a,b,da,db,_ = next(pairs)
        self.assertFalse(passes(compare_defects(a,da,b,db)))

    def test_blank_images_no_detections_and_multiple_defects_do_not_auto_match(self):
        image = Image.new('RGB',(200,200),'grey')
        detection = {'label':'pothole','confidence':.9,'bbox_xyxy':[0,0,200,200]}
        for first,second in [([],[]),([detection],[detection]),([detection,detection],[detection])]:
            self.assertFalse(passes(compare_defects(image,first,image,second)))
