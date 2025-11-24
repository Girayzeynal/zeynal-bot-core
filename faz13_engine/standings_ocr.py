import cv2
import pytesseract
import numpy as np
import re

# ================================================================
#   FAZ-13 Standings OCR Engine
#   Takım sıralamaları, W-L, Home/Away, Last 10, PF/PA gibi
#   puan durumu istatistiklerini görselden ayrıştırır.
# ================================================================

def extract_standings(image_bytes: bytes) -> dict:
    """
    Puan durumu, W-L, Home/Away, Son 10, Streak, PF/PA değerlerini
    görselden OCR ile çıkartan motor.
    """

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)[1]

    text = pytesseract.image_to_string(gray, lang="eng")

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    standings = []
    current_team = {}

    for line in lines:

        # ------------------------
        # Takım sırası + isim
        # ------------------------
        m = re.match(r"(\d+)\.?\s+([A-Za-zÇĞÖŞÜİçöğüşı\- ]+)", line)
        if m:
            if current_team:
                standings.append(current_team)
                current_team = {}

            current_team["rank"] = int(m.group(1))
            current_team["team"] = m.group(2).strip().upper()
            continue

        # ------------------------
        # W - L
        # ------------------------
        wl = re.search(r"(\d+)\s*-\s*(\d+)", line)
        if wl:
            current_team["wins"] = int(wl.group(1))
            current_team["losses"] = int(wl.group(2))
            continue

        # ------------------------
        # Home / Away kayıtları
        # ------------------------
        ha = re.search(r"Home[: ]+(\d+-\d+).*Away[: ]+(\d+-\d+)", line, re.IGNORECASE)
        if ha:
            current_team["home"] = ha.group(1)
            current_team["away"] = ha.group(2)
            continue

        # ------------------------
        # Son 10 maç formu
        # ------------------------
        last10 = re.search(r"(Last\s*10|Son\s*10)[: ]+(\d+-\d+)", line, re.IGNORECASE)
        if last10:
            current_team["last10"] = last10.group(2)
            continue

        # ------------------------
        # Streak (W3 / L2)
        # ------------------------
        streak = re.search(r"(W\d+|L\d+)", line)
        if streak:
            current_team["streak"] = streak.group(1)
            continue

        # ------------------------
        # PF / PA
        # ------------------------
        pfpa = re.search(r"PF[: ]+(\d+).*PA[: ]+(\d+)", line, re.IGNORECASE)
        if pfpa:
            current_team["pf"] = int(pfpa.group(1))
            current_team["pa"] = int(pfpa.group(2))
            continue

    if current_team:
        standings.append(current_team)

    return {"standings": standings}
