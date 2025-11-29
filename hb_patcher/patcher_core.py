import json
from datetime import datetime

from hb_patcher.github_api import github_get_file, github_commit
from hb_patcher.patterns import PATCH_RULES


def apply_patch() -> str:
    """
    main.py dosyasını PATCH_RULES'e göre otomatik günceller.
    GitHub üzerinden çek → satır satır düzenle → geri commit et.
    """
    REPO = "Girayzeynal/zeynal-bot-core"
    BRANCH = "main"
    FILE_PATH = "main.py"

    # 1) main.py içeriğini çek
    content, sha = github_get_file(REPO, FILE_PATH, BRANCH)
    lines = content.split("\n")

    original = list(lines)

    # 2) Kuralları sırayla uygula
    for rule in PATCH_RULES:
        action = rule.get("action")
        pattern = rule.get("pattern")
        payload = rule.get("payload", "")

        if not action or not pattern:
            continue

        # Tek satır payload
        if action == "insert_after":
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if pattern in line:
                    new_lines.append(payload)
            lines = new_lines

        elif action == "insert_before":
            new_lines = []
            for line in lines:
                if pattern in line:
                    new_lines.append(payload)
                new_lines.append(line)
            lines = new_lines

        elif action == "replace_block":
            start = rule.get("start")
            end = rule.get("end")
            if not start or not end:
                continue

            new_block = payload.split("\n")
            replaced = False

            for i in range(len(lines)):
                if start in lines[i]:
                    for j in range(i, len(lines)):
                        if end in lines[j]:
                            # i..j aralığını yeni blok ile değiştir
                            lines[i : j + 1] = new_block
                            replaced = True
                            break
                if replaced:
                    break

    # 3) Hiç değişiklik yoksa geri dön
    if lines == original:
        return "⚪ main.py zaten güncel – patch uygulanmadı."

    # 4) Yeni içeriği oluştur ve commit et
    new_content = "\n".join(lines)
    commit_msg = f"Auto-Patch {datetime.utcnow().isoformat()}"

    github_commit(
        REPO,
        FILE_PATH,
        new_content,
        sha,
        commit_msg,
        BRANCH,
    )

    return f"🟢 main.py güncellendi.\n📝 Commit: {commit_msg}" 
