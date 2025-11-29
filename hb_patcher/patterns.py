PATCH_RULES = [
    {
        "action": "insert_after",
        "pattern": "# 🔧 CONFIG & GLOBALS",
        "payload": "# AUTO PATCH TEST SATIRI"
    },
    {
        "action": "insert_before",
        "pattern": "def cmd_status",
        "payload": "# PATCHER OTOMATİK GÜNCELLEME NOKTASI"
    }
]
