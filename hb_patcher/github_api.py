import os
import base64
import logging
import requests

log = logging.getLogger("hb-patcher-github")

TOKEN = os.getenv("GITHUB_TOKEN")


def _headers() -> dict:
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN env değişkeni tanımlı değil.")
    return {"Authorization": f"token {TOKEN}",
            "Accept": "application/vnd.github.v3+json"}


def github_get_file(repo: str, path: str, branch: str = "main"):
    """
    GitHub API'den bir dosyanın içeriğini (decoded text) ve sha değerini döner.
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    r = requests.get(url, headers=_headers(), timeout=15)
    r.raise_for_status()

    data = r.json()
    content_b64 = data.get("content", "")
    # GitHub içerik satır sonu taşıyabiliyor, temizleyelim
    content_b64 = content_b64.replace("\n", "")
    decoded = base64.b64decode(content_b64).decode("utf-8")

    sha = data.get("sha")
    if not sha:
        raise RuntimeError(f"GitHub dosya SHA bulunamadı: {repo}/{path}")

    log.info(f"GitHub GET OK: {repo}/{path}@{branch}")
    return decoded, sha


def github_commit(
    repo: str,
    path: str,
    content_str: str,
    sha: str,
    message: str,
    branch: str = "main",
):
    """
    Verilen text içeriği base64'e çevirip GitHub'a commit eder.
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}"

    encoded = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")

    payload = {
        "message": message,
        "content": encoded,
        "sha": sha,
        "branch": branch,
    }

    r = requests.put(url, json=payload, headers=_headers(), timeout=15)
    r.raise_for_status()

    log.info(f"GitHub COMMIT OK: {repo}/{path}@{branch} msg={message}")
    return r.json()
