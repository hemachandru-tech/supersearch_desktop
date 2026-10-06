import cv2
import numpy as np
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from datetime import datetime
from .config import get_face_app, get_classifier, get_label_encoder
import asyncio
import os

# Enable HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    print("✓ HEIC support enabled")
except ImportError:
    print("⚠️ pillow-heif not installed. HEIC files will fail. Install: pip install pillow-heif")

# ---- Face-recognition tuning (all overridable dynamically in settings) -------

def safe_load_image(image_path):
    """Load image with HEIC support and convert to RGB"""
    try:
        img = Image.open(image_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return img
    except Exception as e:
        raise ValueError(f"Cannot load image {image_path}: {e}")

def compute_sharpness(face_img):
    """Calculate sharpness score of a face crop"""
    if face_img is None or face_img.size == 0:
        return 0
    gray = cv2.cvtColor(face_img, cv2.COLOR_RGB2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()

def get_face_size(bbox):
    """Calculate face size (width and height)"""
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1
    return width, height

def detect_orientation(image_shape):
    """
    Detect image orientation based on dimensions
    Returns: 'Landscape', 'Portrait', or 'Square'
    """
    height, width = image_shape[:2]
    aspect_ratio = width / height
    
    if 0.95 <= aspect_ratio <= 1.05:
        return "Square"
    elif aspect_ratio > 1.05:
        return "Landscape"
    else:
        return "Portrait"

def detect_faces_with_rotation(face_app, image_rgb, orientation):
    """
    Detect faces with multiple rotation attempts if needed
    Ensures faces are found regardless of orientation
    """
    # Try 1: Original orientation
    faces = face_app.get(image_rgb)
    if len(faces) > 0:
        return faces, 0
    
    # Try 2: Rotate 90° clockwise
    rotated_90 = cv2.rotate(image_rgb, cv2.ROTATE_90_CLOCKWISE)
    faces = face_app.get(rotated_90)
    if len(faces) > 0:
        return faces, 90
    
    # Try 3: Rotate 90° counter-clockwise
    rotated_270 = cv2.rotate(image_rgb, cv2.ROTATE_90_COUNTERCLOCKWISE)
    faces = face_app.get(rotated_270)
    if len(faces) > 0:
        return faces, 270
    
    # Try 4: Rotate 180°
    rotated_180 = cv2.rotate(image_rgb, cv2.ROTATE_180)
    faces = face_app.get(rotated_180)
    if len(faces) > 0:
        return faces, 180
    
    return [], 0

def adjust_bbox_for_rotation(bbox, rotation_angle, image_shape):
    """Adjust bounding box coordinates based on rotation angle"""
    x1, y1, x2, y2 = bbox
    height, width = image_shape[:2]
    
    if rotation_angle == 0:
        return [x1, y1, x2, y2]
    
    elif rotation_angle == 90:
        new_x1 = y1
        new_y1 = width - x2
        new_x2 = y2
        new_y2 = width - x1
        return [new_x1, new_y1, new_x2, new_y2]
    
    elif rotation_angle == 270:
        new_x1 = height - y2
        new_y1 = x1
        new_x2 = height - y1
        new_y2 = x2
        return [new_x1, new_y1, new_x2, new_y2]
    
    elif rotation_angle == 180:
        new_x1 = width - x2
        new_y1 = height - y2
        new_x2 = width - x1
        new_y2 = height - y1
        return [new_x1, new_y1, new_x2, new_y2]
    
    return [x1, y1, x2, y2]

_cached_class_embeddings = None
_cached_class_labels = None


def clear_embedding_caches():
    global _cached_class_embeddings, _cached_class_labels
    global _cached_norm_embs, _cached_norm_lbls
    _cached_class_embeddings = None
    _cached_class_labels = None
    _cached_norm_embs = None
    _cached_norm_lbls = None

def get_class_embeddings_and_labels():
    """Extract training embeddings and labels from the model or SVC support vectors."""
    global _cached_class_embeddings, _cached_class_labels
    if _cached_class_embeddings is not None and _cached_class_labels is not None:
        return _cached_class_embeddings, _cached_class_labels
        
    embeddings = None
    labels = None
    
    try:
        from modules.config import FACE_MODEL_PATH
        from local_db import LocalDB
        import joblib
        
        db = LocalDB()
        active_path = db.get_active_model_path()
        target_path = active_path if (active_path and os.path.exists(active_path)) else FACE_MODEL_PATH
        
        model_data = joblib.load(target_path)
        if isinstance(model_data, dict):
            if "embeddings" in model_data and "labels" in model_data:
                embeddings = np.array(model_data["embeddings"])
                labels = np.array(model_data["labels"])
    except Exception:
        pass
        
    if embeddings is None:
        try:
            clf = get_classifier()
            label_encoder = get_label_encoder()
            if hasattr(clf, "support_vectors_") and hasattr(clf, "n_support_"):
                embeddings = clf.support_vectors_
                classes = clf.classes_
                n_support = clf.n_support_
                
                labels_list = []
                for idx, count in enumerate(n_support):
                    class_name = label_encoder.inverse_transform([classes[idx]])[0]
                    labels_list.extend([class_name] * count)
                labels = np.array(labels_list)
        except Exception as e:
            print(f"[image_processing] Error extracting SVC support vectors: {e}")
            
    _cached_class_embeddings = embeddings
    _cached_class_labels = labels
    return embeddings, labels

_cached_norm_embs = None
_cached_norm_lbls = None

def _get_normalized_class_embeddings():
    """Return (L2-normalized class embeddings, labels) for cosine-based open-set checks.
    Cached. The SVC's support vectors ARE ArcFace embeddings, so we can use them as
    per-player reference templates without needing the original training images."""
    global _cached_norm_embs, _cached_norm_lbls
    if _cached_norm_embs is not None:
        return _cached_norm_embs, _cached_norm_lbls
    E, L = get_class_embeddings_and_labels()
    if E is None or L is None:
        return None, None
    # float64 avoids a spurious "divide by zero in matmul" FP warning from the float32
    # BLAS path on some platforms (e.g. macOS Accelerate); results are identical.
    E = np.asarray(E, dtype=np.float64)
    _cached_norm_embs = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-8)
    _cached_norm_lbls = np.asarray(L)
    return _cached_norm_embs, _cached_norm_lbls

def cosine_to_class(embedding_norm, class_name, topk=3):
    """How well a (normalized) face embedding matches a player's reference templates:
    the mean of the top-k cosine similarities to that class's support vectors. This is a
    robust, open-set 'do the facial features actually match this player?' measure."""
    En, L = _get_normalized_class_embeddings()
    if En is None:
        return None
    with np.errstate(all="ignore"):
        sims = En @ np.asarray(embedding_norm, dtype=np.float64)
    cls = sims[L == class_name]
    if cls.size == 0:
        return 0.0
    k = int(min(topk, cls.size))
    return float(np.sort(cls)[::-1][:k].mean())

def nearest_class_by_cosine(embedding_norm, topk=3):
    """Search ALL players and return (best_player, score) where score is the top-k mean
    cosine similarity to that player's reference templates. Naturally open-set: a face
    that isn't any known player scores low against everyone, so it stays Unknown."""
    En, L = _get_normalized_class_embeddings()
    if En is None:
        return None, None
    with np.errstate(all="ignore"):
        sims = En @ np.asarray(embedding_norm, dtype=np.float64)
    best_label, best_score = None, -1.0
    for lbl in np.unique(L):
        cls = sims[L == lbl]
        if cls.size == 0:
            continue
        k = int(min(topk, cls.size))
        v = float(np.sort(cls)[::-1][:k].mean())
        if v > best_score:
            best_score, best_label = v, lbl
    return best_label, best_score

def confidence_from_cosine(cos_sim, midpoint=0.36, steepness=11.0):
    """Map an embedding cosine similarity to a 0-100 'facial certainty' score via a
    calibrated logistic. This is the ONLY thing behind the accuracy score the user sees:
    it reflects how sure we are about the player's FACE, not metadata completeness or any
    other factor. cos≈0.42→50%, 0.50→72%, 0.55→83%, 0.60→89%."""
    if cos_sim is None:
        return 0.0
    score = 100.0 / (1.0 + np.exp(-steepness * (float(cos_sim) - midpoint)))
    return float(max(1.0, min(99.0, score)))

def verify_knn_consensus(embedding, predicted_name, k=5, threshold=0.48):
    """
    Verify the classification using a K-Nearest Neighbors consensus over support vectors/training embeddings.
    Returns True if consensus is met, False otherwise.
    """
    class_embs, class_lbls = get_class_embeddings_and_labels()
    if class_embs is None or class_lbls is None:
        return True # Fallback to True if no training data
        
    # Normalize query embedding
    emb_norm = np.asarray(embedding, dtype=np.float64) / (np.linalg.norm(embedding) + 1e-8)
    # Normalize support vectors
    class_embs = np.asarray(class_embs, dtype=np.float64)
    class_embs_norm = class_embs / (np.linalg.norm(class_embs, axis=1, keepdims=True) + 1e-8)

    # Compute cosine similarities
    with np.errstate(all="ignore"):
        similarities = np.dot(class_embs_norm, emb_norm)
    
    # Find top K neighbors
    top_indices = np.argsort(similarities)[::-1][:k]
    top_labels = class_lbls[top_indices]
    top_sims = similarities[top_indices]
    
    # Check if the predicted name is among the top labels
    predicted_count = np.sum(top_labels == predicted_name)
    
    # Average similarity of the predicted class in the top K
    predicted_sims = top_sims[top_labels == predicted_name]
    avg_pred_sim = np.mean(predicted_sims) if len(predicted_sims) > 0 else 0.0
    
    # Consensus Rule:
    # 1. The predicted name must be the majority class among top K or at least appear in the top 2.
    # 2. The average similarity of the predicted class in the top K must be >= threshold.
    is_majority = (predicted_count >= (k // 2 + 1)) or (len(top_labels) > 0 and top_labels[0] == predicted_name)
    has_high_sim = (avg_pred_sim >= threshold)
    
    return is_majority and has_high_sim

def recognize_face(embedding, clf, label_encoder, cosine_threshold):
    """
    Given a raw facial embedding from InsightFace, normalizes it and applies
    the closed-set SVM + open-set cosine verification gate.
    Returns: (name, confidence)
    """
    import numpy as np
    embedding = np.asarray(embedding, dtype=np.float32)
    # The model was trained on L2-normalized ArcFace vectors (its support vectors have
    # unit norm). Feed it the normalized embedding too - this removes a train/serve
    # representation skew that on its own degraded recognition accuracy.
    emb_norm = embedding / (np.linalg.norm(embedding) + 1e-8)
    name = "Unknown"
    confidence = 0.0

    try:
        if hasattr(clf, "predict_proba"):
            # Consider BOTH the SVC's pick and the overall cosine-nearest player, and
            # trust whichever the facial features actually support more. This recovers
            # genuine players that a strict single-gate was dropping to Unknown.
            proba = clf.predict_proba([emb_norm])[0]
            svc_name = label_encoder.inverse_transform([int(np.argmax(proba))])[0]
            svc_cos = cosine_to_class(emb_norm, svc_name) or 0.0
            nn_name, nn_cos = nearest_class_by_cosine(emb_norm)
            if nn_cos is not None and nn_cos >= svc_cos:
                cand_name, best_cos = nn_name, nn_cos
            else:
                cand_name, best_cos = svc_name, svc_cos

            # Displayed confidence reflects ONLY this facial-feature match quality.
            confidence = confidence_from_cosine(best_cos)

            # Lenient open-set gate: tag the player when the face is similar enough to
            # their reference templates (tunable via FACE_COSINE_THRESHOLD). Lower =
            # more players tagged at lower confidence; higher = stricter. We do NOT gate
            # on the SVC probability (an over-confident SVC prob on an out-of-distribution
            # crop is what caused the original "one name everywhere" leak). Faces that
            # resemble NO known player stay Unknown.
            if best_cos is not None and best_cos >= cosine_threshold:
                name = cand_name
        else:
            pred = clf.predict([emb_norm])[0]
            name = label_encoder.inverse_transform([pred])[0]
            confidence = 100.0
    except Exception:
        pass

    return name, confidence


def process_image(image_np):
    """
    Process image with Streamlit's face detection logic
    Returns: (results, face_count, skip_reason, orientation, rotation_applied)
    """
    # FROZEN recognition parameters (single source of truth: modules/frozen_config.py).
    # These are no longer read from .env or any UI control — see Phase 1 freeze.
    from modules import frozen_config as FROZEN
    SHARPNESS_THRESHOLD = FROZEN.FACE_MIN_SHARPNESS
    MIN_FACE_SIZE = FROZEN.FACE_MIN_SIZE
    PRIMARY_ONLY = FROZEN.FACE_PRIMARY_ONLY
    PRIMARY_AREA_RATIO = FROZEN.FACE_PRIMARY_AREA_RATIO
    MAX_FACES_LIMIT = FROZEN.FACE_MAX_FACES
    # Open-set gate (stops one name leaking onto everything, but kept lenient so genuine
    # players are recognised even on harder angles — lower = more lenient).
    COSINE_THRESHOLD = FROZEN.FACE_COSINE_THRESHOLD
    KNN_THRESHOLD = FROZEN.FACE_KNN_THRESHOLD

    app = get_face_app()
    clf = get_classifier()
    label_encoder = get_label_encoder()

    image_rgb = image_np.copy()
    
    # Detect orientation
    orientation = detect_orientation(image_rgb.shape)
    
    # Use rotation-aware face detection
    faces, rotation_angle = detect_faces_with_rotation(app, image_rgb, orientation)
    
    # Check if too many faces (crowded scene)
    if len(faces) > MAX_FACES_LIMIT:
        return [], len(faces), f"crowd_detected_{len(faces)}_faces", orientation, rotation_angle
    
    if not faces:
        return [], 0, None, orientation, rotation_angle
    
    total_faces_detected = len(faces)

    # ---- PASS 1: keep only geometrically-valid, IN-FOCUS faces ----
    candidates = []  # each: dict(box, area, embedding)
    for face in faces:
        x1, y1, x2, y2 = face.bbox.astype(int)

        if rotation_angle != 0:
            if rotation_angle in [90, 270]:
                rotated_shape = (image_rgb.shape[1], image_rgb.shape[0], image_rgb.shape[2])
            else:
                rotated_shape = image_rgb.shape
            x1, y1, x2, y2 = adjust_bbox_for_rotation([x1, y1, x2, y2], rotation_angle, rotated_shape)

        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image_rgb.shape[1], x2), min(image_rgb.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            continue

        face_width, face_height = get_face_size([x1, y1, x2, y2])
        if face_width < MIN_FACE_SIZE or face_height < MIN_FACE_SIZE:
            continue

        # Blur check - skip out-of-focus / background faces
        face_crop = image_rgb[y1:y2, x1:x2]
        if compute_sharpness(face_crop) < SHARPNESS_THRESHOLD:
            continue

        candidates.append({
            "box": (x1, y1, x2, y2),
            "area": face_width * face_height,
            "embedding": face.embedding,
        })

    if not candidates:
        return [], total_faces_detected, None, orientation, rotation_angle

    # ---- Focus on the MAIN SUBJECT(s): drop small background faces ----
    if PRIMARY_ONLY:
        max_area = max(c["area"] for c in candidates)
        candidates = [c for c in candidates if c["area"] >= PRIMARY_AREA_RATIO * max_area]

    # ---- PASS 2: identify each kept face (closed-set classifier + open-set gate) ----
    results = []
    for c in candidates:
        x1, y1, x2, y2 = c["box"]
        embedding = c["embedding"]
        name, confidence = recognize_face(embedding, clf, label_encoder, COSINE_THRESHOLD)
        
        # NOTE: Continuous-learning override removed in Phase 1 freeze. Recognition now
        # relies solely on the frozen faces_custom.joblib model (read-only inference).

        results.append((x1, y1, x2, y2, name, confidence))

    return results, total_faces_detected, None, orientation, rotation_angle

async def load_image_for_face_recognition(image_path):
    """Async wrapper for face recognition"""
    image = safe_load_image(image_path)
    image_np = np.array(image)
    results, face_count, skip_reason, orientation, rotation = process_image(image_np)
    return results, face_count, skip_reason, orientation, rotation

def categorize_time_of_day(datetime_str):
    """Categorize time into morning/afternoon/evening/night"""
    try:
        datetime_obj = datetime.strptime(datetime_str, "%Y:%m:%d %H:%M:%S")
        hour = datetime_obj.hour
        if 6 <= hour < 12: return "Morning"
        elif 12 <= hour < 16: return "Afternoon"
        elif 16 <= hour < 19: return "Evening"
        else: return "Night"
    except ValueError:
        return "Invalid DateTime"

def detect_shot_type(image_np, identified_faces):
    """
    Heuristic shot type detection based on number of faces and face size.
    Returns one of: 'Close Shot', 'Medium Shot', 'Wide Shot'.
    """
    if image_np is None or image_np.size == 0:
        return "Unknown"

    total_faces = len(identified_faces)
    if total_faces == 0:
        return "Wide Shot"

    height, width = image_np.shape[:2]
    image_area = width * height

    face_areas = []
    for (x1, y1, x2, y2, _, _) in identified_faces:
        face_area = max(1, (x2 - x1) * (y2 - y1))
        face_areas.append(face_area / image_area)

    avg_face_ratio = np.mean(face_areas) if face_areas else 0

    if total_faces == 1:
        if avg_face_ratio > 0.12:
            return "Close Shot"
        elif avg_face_ratio > 0.035:
            return "Medium Shot"
        else:
            return "Wide Shot"
    elif 2 <= total_faces <= 3:
        if avg_face_ratio > 0.06:
            return "Medium Shot"
        else:
            return "Wide Shot"
    else:
        return "Wide Shot"

def extract_exif_details(image_path):
    """Extract metadata from image EXIF with crowd detection"""
    file_extension = os.path.splitext(image_path)[1].lower()
    is_heic = file_extension in ['.heic', '.heif']
    
    try:
        image = safe_load_image(image_path)
        exif_data = getattr(image, "_getexif", lambda: None)() or {}
    except Exception as e:
        return {
            "File Name": os.path.basename(image_path),
            "Error": f"Cannot read image: {str(e)}",
            "NoOfFaces": 0,
            "Focus": "null",
            "Shot Type": "Unknown",
            "Player Name": "Unknown",
            "Skip Reason": None
        }

    metadata = {
        "File Name": os.path.basename(image_path),
        "Photographer": None,
        "Copyright": None,
        "DateTimeOriginal": None,
        "Date": "Unknown",
        "Camera Make": None,
        "Camera Model": None
    }

    for tag, value in exif_data.items():
        tag_name = TAGS.get(tag, tag)
        if tag_name == "Artist":
            metadata["Photographer"] = value
        elif tag_name == "Copyright":
            metadata["Copyright"] = value
        elif tag_name == "DateTimeOriginal":
            metadata["DateTimeOriginal"] = value
            try:
                metadata["Date"] = value.split()[0].replace(":", "/")
            except (IndexError, AttributeError):
                pass
        elif tag_name == "Make":
            metadata["Camera Make"] = value
        elif tag_name == "Model":
            metadata["Camera Model"] = value

    if metadata["DateTimeOriginal"]:
        metadata["TimeOfDay"] = categorize_time_of_day(metadata["DateTimeOriginal"])

    # Process face detection with new logic
    identified_faces = []
    total_faces_detected = 0
    skip_reason = None
    orientation = "Unknown"
    rotation_applied = 0
    
    try:
        image_np = np.array(image)
        identified_faces, total_faces_detected, skip_reason, orientation, rotation_applied = process_image(image_np)
    except Exception as e:
        print(f"  ⚠️ Face detection failed for {os.path.basename(image_path)}: {str(e)[:100]}")
        identified_faces = []
        total_faces_detected = 0

    # Handle crowd detection
    if skip_reason and skip_reason.startswith("crowd_detected"):
        metadata.update({
            "NoOfFaces": total_faces_detected,
            "Focus": "crowd",
            "Shot Type": "Wide Shot",
            "Player Name": "crowd",
            "Skip Reason": skip_reason,
            "Orientation": orientation,
            "Rotation Applied": rotation_applied
        })
        return metadata

    # Recognized player names (exclude Unknown)
    recognized_players = [face[4] for face in identified_faces if face[4] != "Unknown"]
    player_names = list(set(recognized_players))
    
    all_detected_names = [face[4] for face in identified_faces]
    unknown_count = all_detected_names.count("Unknown")

    # Focus logic
    if len(player_names) == 1:
        focus_value = "solo"
    elif len(player_names) > 1:
        focus_value = "group"
    else:
        focus_value = "null"

    # Player Name with Unknown handling
    if is_heic and not player_names and total_faces_detected > 0:
        player_name_str = f"{unknown_count} Unknown" if unknown_count > 1 else "Unknown"
    elif player_names and unknown_count > 0:
        player_name_str = ", ".join(player_names) + f" + {unknown_count} Unknown"
    elif player_names:
        player_name_str = ", ".join(player_names)
    elif unknown_count > 0:
        player_name_str = f"{unknown_count} Unknown" if unknown_count > 1 else "Unknown"
    else:
        player_name_str = "Unknown"

    metadata.update({
        "NoOfFaces": total_faces_detected,
        "Focus": focus_value,
        "Shot Type": detect_shot_type(image_np, identified_faces),
        "Player Name": player_name_str,
        "Skip Reason": skip_reason,
        "Orientation": orientation,
        "Rotation Applied": rotation_applied,
        "faces": identified_faces
    })

    return metadata

async def process_image_for_metadata(image_info):
    """Main processing pipeline for an image"""
    image_path = image_info["file_path"]
    metadata = extract_exif_details(image_path)
    
    if "url" in image_info:
        metadata["URL"] = image_info["url"]
    
    return metadata

# -------------------------------------------------------------------------
# Drawing and annotation functions
# -------------------------------------------------------------------------

def _format_label_text(name, confidence):
    """Build label text for a face result"""
    if confidence is None:
        return f"{name}"
    try:
        return f"{name} {confidence:.1f}%"
    except Exception:
        return f"{name}"

def draw_bounding_boxes_on_image(image_np, results, box_thickness=2, font_scale=0.6):
    """Draw bounding boxes + labels on an RGB image"""
    annotated = image_np.copy()

    for (x1, y1, x2, y2, name, confidence) in results:
        cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), box_thickness)
        
        label = _format_label_text(name, confidence)
        font = cv2.FONT_HERSHEY_SIMPLEX
        (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, max(1, box_thickness))
        text_x, text_y = int(x1), max(int(y1) - 5, text_h + 5)

        cv2.rectangle(
            annotated,
            (text_x, text_y - text_h - baseline),
            (text_x + text_w + 4, text_y + baseline),
            (0, 255, 0),
            thickness=-1
        )
        cv2.putText(
            annotated,
            label,
            (text_x + 2, text_y - baseline),
            font,
            font_scale,
            (0, 0, 0),
            thickness=max(1, box_thickness // 2),
            lineType=cv2.LINE_AA
        )

    return annotated

def save_annotated_image(image_path, results, out_dir="results/annotated"):
    """Save image with drawn boxes + labels"""
    try:
        pil_img = safe_load_image(image_path)
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as e:
        print(f"Error loading image for annotation: {e}")
        return None

    if img is None:
        return None

    os.makedirs(out_dir, exist_ok=True)
    h, w = img.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX

    for (x1, y1, x2, y2, name, conf) in results:
        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        pad = max(6, int(0.20 * max(bw, bh)))
        thick = max(2, int(round(max(h, w) / 500)))

        x1p = max(0, x1 - pad)
        y1p = max(0, y1 - pad)
        x2p = min(w - 1, x2 + pad)
        y2p = min(h - 1, y2 + pad)
        cv2.rectangle(img, (x1p, y1p), (x2p, y2p), (0, 255, 0), thick)

        label = name if conf is None else f"{name} {conf:.1f}%"
        max_label_width = int(0.65 * w)

        scale = max(0.5, min(1.8, h / 900.0))
        text_thick = max(1, int(round(thick * 0.8)))

        (tw, th), base = cv2.getTextSize(label, font, scale, text_thick)
        while tw > max_label_width and scale > 0.35:
            scale -= 0.05
            (tw, th), base = cv2.getTextSize(label, font, scale, text_thick)

        lines = []
        if tw <= max_label_width:
            lines = [label]
            line_w = tw
            line_h = th + base
        else:
            words = label.split()
            cur = ""
            line_w = 0
            for word in words:
                test = (cur + " " + word).strip()
                (ttw, tth), tbase = cv2.getTextSize(test, font, scale, text_thick)
                if ttw <= max_label_width or not cur:
                    cur = test
                    line_w = max(line_w, ttw)
                else:
                    lines.append(cur)
                    cur = word
                    line_w = max(line_w, cv2.getTextSize(cur, font, scale, text_thick)[0][0])
            if cur:
                lines.append(cur)
            line_h = th + base

        box_w = line_w + 10
        box_h = len(lines) * (line_h) + 8

        y_top = y1p - 6
        draw_above = (y_top - box_h) >= 0
        if draw_above:
            y_bg_top = y_top - box_h
            y_text = y_bg_top + 6 + th
        else:
            y_bg_top = min(h - box_h - 1, y2p + 6)
            y_text = y_bg_top + 6 + th

        x_bg_left = min(max(0, x1p), max(0, w - box_w - 1))

        cv2.rectangle(img, (x_bg_left, y_bg_top),
                      (min(w - 1, x_bg_left + box_w), min(h - 1, y_bg_top + box_h)),
                      (0, 255, 0), -1)

        for line in lines:
            cv2.putText(img, line, (x_bg_left + 5, y_text),
                        font, scale, (0, 0, 0), text_thick, cv2.LINE_AA)
            y_text += line_h

    out_path = os.path.join(out_dir, os.path.basename(image_path))
    cv2.imwrite(out_path, img)
    return out_path

def process_and_save_annotated(image_path, output_path=None, box_thickness=2, font_scale=0.8):
    """
    Convenience wrapper:
      1) Loads image
      2) Runs face detection/recognition
      3) Saves annotated image
    Returns: (output_path, results, face_count, skip_reason)
    """
    image = safe_load_image(image_path)
    image_np = np.array(image)
    results, face_count, skip_reason, orientation, rotation = process_image(image_np)
    
    # Don't save annotation if crowd detected
    if skip_reason and skip_reason.startswith("crowd_detected"):
        return None, results, face_count, skip_reason
    
    out = save_annotated_image(
        image_path, results, out_dir=output_path or "results/annotated"
    )
    return out, results, face_count, skip_reason