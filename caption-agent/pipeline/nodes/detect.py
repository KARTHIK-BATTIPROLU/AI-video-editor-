"""detect_regions — sample frames at 2 fps, detect faces/people, normalize 0..1.

Detector tiers (best first):
  1. YOLO face weight (yolov8n-face.pt) if you drop one in the project root.
  2. OpenCV Haar frontal-face detector — BUNDLED with opencv-python, offline, no
     torch. Gives true FACE boxes so captions can sit clear of the face.
  3. YOLO person class (yolov8n.pt, auto-downloaded) — full-body boxes; captions
     can only avoid the whole person. Logged as person so checks can say so.
Degrades to no detections (lower-third default) if none are available.
"""

import os

from ..state import CaptionState, Box, FrameDet
from ._log import log

# Optional YOLO face weights, checked in order.
_FACE_WEIGHTS = ["yolov8n-face.pt", "weights/yolov8n-face.pt", "models/yolov8n-face.pt"]
_SAMPLE_FPS = 2.0
_MIN_AREA = 0.01        # discard boxes smaller than 1% of the frame
_FACE_AR = (0.6, 1.5)   # face-shaped PIXEL aspect ratio (w/h)
_HOLD_SEC = 0.5         # carry the last face forward across brief misses


def _dominant_face(boxes, kind, width, height):
    """Collapse a frame's raw detections to the single dominant face.

    Haar can fire on patterned clothing/background (this clip throws up to 5
    boxes near t~24.5s/38.7s). Keep only face-shaped detections (sane PIXEL
    aspect ratio) covering >=1% of the frame, then return the single largest,
    so a spurious box can't corrupt the safe-zone union. Person boxes (YOLO
    fallback) are tall, so the aspect gate is skipped for them.
    """
    cand = []
    for b in boxes:
        if b.w * b.h < _MIN_AREA:
            continue
        if kind != "yolo-person":
            ph = b.h * height
            ar = (b.w * width) / ph if ph > 0 else 0.0
            if not (_FACE_AR[0] <= ar <= _FACE_AR[1]):
                continue
        cand.append(b)
    if not cand:
        return []
    return [max(cand, key=lambda b: b.w * b.h)]


def _choose_detector(cv2):
    """Return (kind, model). kind in {yolo-face, haar-face, yolo-person} or (None, None)."""
    try:
        from ultralytics import YOLO
        have_yolo = True
    except Exception as exc:  # noqa: BLE001 - missing ultralytics/torch
        have_yolo = False
        log("detect", f"ultralytics unavailable ({exc}); trying OpenCV face detector")

    # Tier 1: YOLO face weight
    if have_yolo:
        for cand in _FACE_WEIGHTS:
            if os.path.exists(cand):
                log("detect", f"using YOLO face weight {cand}")
                return "yolo-face", YOLO(cand)

    # Tier 2: OpenCV Haar frontal face (bundled with opencv-python, offline)
    try:
        cascade_path = os.path.join(cv2.data.haarcascades,
                                    "haarcascade_frontalface_default.xml")
        if os.path.exists(cascade_path):
            cascade = cv2.CascadeClassifier(cascade_path)
            if not cascade.empty():
                log("detect", "using OpenCV Haar frontal-face detector (bundled, offline)")
                return "haar-face", cascade
    except Exception as exc:  # noqa: BLE001
        log("detect", f"Haar face detector unavailable ({exc})")

    # Tier 3: YOLO person
    if have_yolo:
        log("detect", "no face detector; falling back to YOLO person class (yolov8n.pt)")
        return "yolo-person", YOLO("yolov8n.pt")

    return None, None


def _detect_frame(kind, model, frame, cv2, width, height):
    boxes: list[Box] = []
    if kind == "haar-face":
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = model.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=6,
            minSize=(max(24, int(width * 0.06)), max(24, int(height * 0.06))),
        )
        for (fx, fy, fw, fh) in faces:
            # detectMultiScale yields numpy int32; cast to native float so the
            # Box (and the FrameDet holding it) stays msgpack-serializable for
            # the LangGraph checkpointer.
            boxes.append(Box(x=float(fx) / width, y=float(fy) / height,
                             w=float(fw) / width, h=float(fh) / height))
    else:  # yolo-face / yolo-person
        res = model(frame, verbose=False)[0]
        for b in res.boxes:
            cls = int(b.cls[0]) if b.cls is not None else -1
            if kind == "yolo-person" and cls != 0:  # keep only people
                continue
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            boxes.append(Box(x=x1 / width, y=y1 / height,
                             w=(x2 - x1) / width, h=(y2 - y1) / height))
    return boxes


def detect_regions(state: CaptionState) -> dict:
    # Graceful degrade: with CAPTION_AGENT_NO_YOLO=1 or no OpenCV, emit no
    # detections -> compute_safe_zones defaults every window to lower-third.
    if os.environ.get("CAPTION_AGENT_NO_YOLO") == "1":
        log("detect", "CAPTION_AGENT_NO_YOLO=1 -> skipping detection (no face dodging)")
        return {"detections": []}
    try:
        import cv2
    except ImportError as exc:
        log("detect", f"OpenCV unavailable ({exc}); skipping detection (no face dodging)")
        return {"detections": []}

    kind, model = _choose_detector(cv2)
    if model is None:
        log("detect", "no detector available; skipping detection (no face dodging)")
        return {"detections": []}

    video = state["video_path"]
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or float(state.get("fps") or 30.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or int(state.get("width") or 1)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or int(state.get("height") or 1)
    sample_every = max(1, int(round(fps / _SAMPLE_FPS)))

    detections: list[FrameDet] = []
    last_box, last_t = None, -1e9
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % sample_every == 0:
            t = idx / fps
            raw = _detect_frame(kind, model, frame, cv2, width, height)
            boxes = _dominant_face(raw, kind, width, height)
            if boxes:
                last_box, last_t = boxes[0], t
            elif last_box is not None and (t - last_t) <= _HOLD_SEC:
                boxes = [last_box]   # persist last known face across a miss
            detections.append(FrameDet(t=t, boxes=boxes))
        idx += 1
    cap.release()

    n_boxes = sum(len(d.boxes) for d in detections)
    log("detect", f"[{kind}] sampled {len(detections)} frames, {n_boxes} dominant box(es)")
    return {"detections": detections}
