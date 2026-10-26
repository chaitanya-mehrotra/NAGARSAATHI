"""Evaluate geometric matching; controlled tests are NOT field accuracy estimates."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from backend.visual_matching import compare_defects


def passes(evidence):
    return evidence['inliers'] >= 20 and evidence['inlier_ratio'] >= .8 and evidence['coverage'] >= .25


def controlled_pairs():
    rng = np.random.default_rng(20261026)
    box = [{'label':'pothole','confidence':.9,'bbox_xyxy':[0,0,512,512]}]
    for index in range(24):
        data = rng.integers(0,256,(512,512,3),dtype=np.uint8)
        data = cv2.GaussianBlur(data,(3,3),0)
        source = Image.fromarray(data)
        warped = cv2.warpPerspective(data,np.float32([[1,.01,5],[.005,1,4],[.00001,.00001,1]]),(512,512))
        yield source,Image.fromarray(warped),box,box,True
        unrelated = cv2.GaussianBlur(rng.integers(0,256,(512,512,3),dtype=np.uint8),(3,3),0)
        yield source,Image.fromarray(unrelated),box,box,False


def evaluate(pairs, scope):
    counts = {'true_positive':0,'false_positive':0,'true_negative':0,'false_negative':0}
    for a,b,da,db,same in pairs:
        matched = passes(compare_defects(a,da,b,db))
        name = ('true_positive' if same else 'false_positive') if matched else ('false_negative' if same else 'true_negative')
        counts[name] += 1
    tp,fp,fn = counts['true_positive'],counts['false_positive'],counts['false_negative']
    return {'policy':'orb-defect-v1','runtime':{'opencv':cv2.__version__,'numpy':np.__version__},'scope':scope,'counts':counts,
            'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
            'limitations':'Controlled image transforms establish implementation behavior only. No field-labelled road matching set is available; arbitrary-angle same-issue reliability is unmeasured.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,help='JSON list of first/second image paths, detections and same_issue labels')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    cv2.setRNGSeed(42)
    if args.manifest:
        records = json.loads(args.manifest.read_text(encoding='utf-8'))
        def pairs():
            for record in records:
                with Image.open(args.manifest.parent/record['first']) as first, Image.open(args.manifest.parent/record['second']) as second:
                    yield ImageOps.exif_transpose(first).convert('RGB'), ImageOps.exif_transpose(second).convert('RGB'), record['first_detections'],record['second_detections'],record['same_issue']
        report = evaluate(pairs(),'labelled manifest: '+args.manifest.name)
    else:
        report = evaluate(controlled_pairs(),'48 synthetic textured-image pairs: 24 known transforms, 24 unrelated sources')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
