import numpy as np
from modules.config import clf, label_encoder
from modules import frozen_config as FROZEN
from modules.image_processing import cosine_to_class, nearest_class_by_cosine, confidence_from_cosine

def recognize_face(embedding):
    COSINE_THRESHOLD = FROZEN.FACE_COSINE_THRESHOLD
    
    embedding = np.asarray(embedding, dtype=np.float32)
    emb_norm = embedding / (np.linalg.norm(embedding) + 1e-8)
    name = "Unknown"
    confidence = 0.0

    try:
        if hasattr(clf, "predict_proba"):
            proba = clf.predict_proba([emb_norm])[0]
            svc_name = label_encoder.inverse_transform([int(np.argmax(proba))])[0]
            svc_cos = cosine_to_class(emb_norm, svc_name) or 0.0
            nn_name, nn_cos = nearest_class_by_cosine(emb_norm)
            if nn_cos is not None and nn_cos >= svc_cos:
                cand_name, best_cos = nn_name, nn_cos
            else:
                cand_name, best_cos = svc_name, svc_cos

            confidence = confidence_from_cosine(best_cos)

            if best_cos is not None and best_cos >= COSINE_THRESHOLD:
                name = cand_name
        else:
            pred = clf.predict([emb_norm])[0]
            name = label_encoder.inverse_transform([pred])[0]
            confidence = 100.0
    except Exception:
        pass

    return name, confidence
