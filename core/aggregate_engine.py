def aggregate(rows):
    if not rows:
        return None

    total_conf = sum(r["confidence"] for r in rows)

    return {
        "pts_for": sum(r["pts_for"] * r["confidence"] for r in rows) / total_conf,
        "pts_against": sum(r["pts_against"] * r["confidence"] for r in rows) / total_conf,
        "confidence": total_conf / len(rows),
        "sources": [r["source"] for r in rows]
    }
