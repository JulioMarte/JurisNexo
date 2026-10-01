from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from PIL import Image

LEGAL_CRITICAL = re.compile(
    r"(?i)\b(?:art(?:í|i)culo|art\.?|ley|sentencia|expediente|resoluci(?:ó|o)n|"
    r"decreto|núm(?:ero)?\.?|no\.?|rd\$|us\$)\b|\b\d[\d.,:/-]*\b"
)

@dataclass(frozen=True, slots=True)
class Region:
    text: str
    polygon: tuple[tuple[float, float], ...]
    confidence: float | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        return min(xs), min(ys), max(xs), max(ys)


def opaque_observation_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "ocr-observation:" + hashlib.sha256(encoded).hexdigest()[:24]


def normalize_polygon(value: Any) -> tuple[tuple[float, float], ...] | None:
    if value is None:
        return None
    try:
        pts = value.tolist() if hasattr(value, "tolist") else value
        if len(pts) == 4 and all(isinstance(v, (int, float)) for v in pts):
            x1, y1, x2, y2 = map(float, pts)
            return ((x1,y1),(x2,y1),(x2,y2),(x1,y2))
        out = tuple((float(p[0]), float(p[1])) for p in pts)
        return out if len(out) >= 4 else None
    except (TypeError, ValueError, IndexError):
        return None


def regions_from_parallel(texts: Any, boxes: Any, scores: Any = None) -> list[Region]:
    texts = list(texts or [])
    boxes = list(boxes or [])
    scores = list(scores or [])
    out: list[Region] = []
    for i, (text, box) in enumerate(zip(texts, boxes, strict=False)):
        if not str(text).strip():
            continue
        poly = normalize_polygon(box)
        if poly is None:
            continue
        score = None
        if i < len(scores):
            try:
                score = float(scores[i])
            except (TypeError, ValueError):
                pass
        out.append(Region(str(text).strip(), poly, score))
    return out


def bbox_iou(a: Region, b: Region) -> float:
    ax1, ay1, ax2, ay2 = a.bbox
    bx1, by1, bx2, by2 = b.bbox
    ix = max(0.0, min(ax2,bx2)-max(ax1,bx1))
    iy = max(0.0, min(ay2,by2)-max(ay1,by1))
    inter = ix*iy
    union = max(0.0,(ax2-ax1)*(ay2-ay1)) + max(0.0,(bx2-bx1)*(by2-by1)) - inter
    return inter/union if union else 0.0


def _center_distance(a: Region, b: Region) -> float:
    ax1,ay1,ax2,ay2=a.bbox; bx1,by1,bx2,by2=b.bbox
    ac=((ax1+ax2)/2,(ay1+ay2)/2); bc=((bx1+bx2)/2,(by1+by2)/2)
    scale=max(1.0, max(ay2-ay1, by2-by1))
    return (((ac[0]-bc[0])**2+(ac[1]-bc[1])**2)**0.5)/scale


def match_regions(anchor: list[Region], other: list[Region]) -> dict[int, int]:
    candidates: list[tuple[float,int,int]]=[]
    for i,a in enumerate(anchor):
        for j,b in enumerate(other):
            iou=bbox_iou(a,b)
            dist=_center_distance(a,b)
            if iou >= 0.10 or dist <= 2.5:
                text=SequenceMatcher(None,a.text.casefold(),b.text.casefold(),autojunk=False).ratio()
                candidates.append((2*iou + text - 0.08*dist, i, j))
    result: dict[int,int]={}; used:set[int]=set()
    for _,i,j in sorted(candidates, reverse=True):
        if i not in result and j not in used:
            result[i]=j; used.add(j)
    return result


def classify_disagreement(texts: list[str]) -> str:
    stripped = [
        re.sub(r"[^\w]+", "", text, flags=re.UNICODE).casefold() for text in texts
    ]
    if len(set(stripped)) == 1:
        return "orthographic"
    if LEGAL_CRITICAL.search(" ".join(texts)):
        return "legal_critical"
    return "content"


def union_bbox(regions: list[Region]) -> tuple[int,int,int,int]:
    boxes=[r.bbox for r in regions]
    return (int(min(b[0] for b in boxes)), int(min(b[1] for b in boxes)),
            int(max(b[2] for b in boxes)), int(max(b[3] for b in boxes)))


def padded_crop(image: Image.Image, bbox: tuple[int,int,int,int], *, detail: bool=False) -> Image.Image:
    x1,y1,x2,y2=bbox
    w=max(1,x2-x1); h=max(1,y2-y1)
    px=int(w*(0.12 if detail else 0.25)); py=int(h*(0.50 if detail else 1.5))
    box=(max(0,x1-px),max(0,y1-py),min(image.width,x2+px),min(image.height,y2+py))
    crop=image.crop(box)
    if detail:
        crop=crop.resize((crop.width*3,crop.height*3))
    return crop


def region_to_json(region: Region) -> dict[str, Any]:
    return {"text":region.text,"polygon":[list(p) for p in region.polygon],"confidence":region.confidence}
