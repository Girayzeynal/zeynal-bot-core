from typing import Dict, Any, Tuple

import cv2
import numpy as np
from PIL import Image, ImageEnhance


def _pil_to_cv(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _cv_to_pil(img: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def faz15_preprocess_image(
    pil_img: Image.Image,
    target_width: int = 1400,
) -> Tuple[Image.Image, Dict[str, Any]]:
    """
    OCR öncesi görseli hazırlar:

    - Resize (uzun kenar target_width olacak şekilde)
    - Grayscale + CLAHE (kontrast)
    - Hafif sharpen
    - Orta alan için ek bir zoom crop (barem ve oranların olduğu tipik bölgeye iyi gelir)

    Çıktı:
        processed_pil, meta
    """

    meta: Dict[str, Any] = {"steps": []}

    # 1) Boyutlandırma
    w, h = pil_img.size
    scale = target_width / max(w, h)
    if scale != 1:
        new_size = (int(w * scale), int(h * scale))
        pil_img = pil_img.resize(new_size, Image.LANCZOS)
        meta["steps"].append(f"resize_{new_size[0]}x{new_size[1]}")

    # 2) Kontrast & parlaklık
    contrast_enh = ImageEnhance.Contrast(pil_img)
    pil_img = contrast_enh.enhance(1.25)
    meta["steps"].append("contrast+25%")

    bright_enh = ImageEnhance.Brightness(pil_img)
    pil_img = bright_enh.enhance(1.05)
    meta["steps"].append("brightness+5%")

    # 3) OpenCV tarafı: grayscale + CLAHE + sharpen
    cv_img = _pil_to_cv(pil_img)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    meta["steps"].append("clahe")

    # Sharpen kernel
    kernel = np.array([[0, -1, 0],
                       [-1, 5, -1],
                       [0, -1, 0]], dtype=np.float32)
    sharp = cv2.filter2D(gray, -1, kernel)
    meta["steps"].append("sharpen")

    # 4) OCR için orta alanı biraz daha büyütülmüş ikinci bir versiyon oluştur
    h2, w2 = sharp.shape
    y1 = int(h2 * 0.20)
    y2 = int(h2 * 0.80)
    x1 = int(w2 * 0.05)
    x2 = int(w2 * 0.95)
    crop = sharp[y1:y2, x1:x2]
    meta["steps"].append("center_crop_zoom")

    # Zoom'u biraz büyüt
    zoomed = cv2.resize(
        crop,
        None,
        fx=1.25,
        fy=1.25,
        interpolation=cv2.INTER_CUBIC,
    )
    meta["steps"].append("zoom_1.25x")

    # Son çıktıyı tekrar 3 kanala çevir (OCR motorları RGB isteyebilir)
    final = cv2.cvtColor(zoomed, cv2.COLOR_GRAY2BGR)
    out_pil = _cv_to_pil(final)

    meta["final_size"] = out_pil.size
    return out_pil, meta
