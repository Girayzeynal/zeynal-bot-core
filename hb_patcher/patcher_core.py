import base64
import requests
import json
from datetime import datetime
from hb_patcher.github_api import github_get_file, github_commit
from hb_patcher.patterns import PATCH_RULES


def apply_patch():
    REPO = "Girayzeynal/zeynal-bot-core"
    BRANCH = "main"
    FILE_PATH = "main.py"

    # 1) main.py indir
    content, sha = github_get_file(REPO, FILE_PATH, BRANCH)
    lines = content.split("\n")

    original = lines[:]

    # 2) Kurallar sırayla uygulanıyor
    for rule in PATCH_RULES:
        action = rule["action"]
        pattern = rule["pattern"]
        payload = rule.get("payload")

        if action == "insert_after":
            for i, line in enumerate(lines):
                if pattern in line:
                    lines.insert(i+1, payload)

        elif action == "insert_before":
            for i, line in enumerate(lines):
                if pattern in line:
                    lines.insert(i, payload)

        elif action == "replace_block":
            start = rule["start"]
            end = rule["end"]
            new_block = payload.split("\n")

            for i in range(len(lines)):
                if start in lines[i]:
                    for j in range(i, len(lines)):
                        if end in lines[j]:
                            lines[i:j+1] = new_block
                            break
                    break

    # Değişiklik yoksa geri dön
    if lines == original:
        return "⚠ Dosya zaten güncel – değişiklik yapılmadı."

    # 3) Commit için encode et
    new_content = "\n".join(lines)
    encoded = base64.b64encode(new_content.encode()).decode()

    commit_msg = f"Auto-Patch {datetime.utcnow().isoformat()}"

    github_commit(
        REPO,
        FILE_PATH,
        encoded,
        sha,
        commit_msg,
        BRANCH
    )

    return f"📌 main.py güncellendi.\n🕒 Commit: {commit_msg}"
