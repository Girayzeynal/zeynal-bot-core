import requests
import os

TOKEN = os.getenv("GITHUB_TOKEN")

def github_get_file(repo, path, branch="main"):
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    r = requests.get(url, headers={"Authorization": f"token {TOKEN}"})
    data = r.json()
    content = base64.b64decode(data["content"]).decode()
    return content, data["sha"]


def github_commit(repo, path, encoded, sha, message, branch="main"):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    payload = {
        "message": message,
        "content": encoded,
        "sha": sha,
        "branch": branch
    }
    requests.put(url, json=payload, headers={"Authorization": f"token {TOKEN}"})
