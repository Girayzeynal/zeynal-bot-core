"""
HB-AUTO-PATCHER v1 (GOD MODE)

Çalıştırma:
    python -m hb_core.patcher

Ne yapar?
    1) main.py dosyasının timestamp'li yedeğini alır.
    2) FAZ-13 GOD-LAYER import hatasını düzeltir:
         - faz13_god_pipeline -> run_faz13_with_god_layer
    3) main.py'nin üst kısmına güvenli bir hb_core importu ekler (yoksa).
    4) Yapılan değişiklikleri terminale yazar.
"""

import datetime
import pathlib
import re
import shutil
import sys


# ============================================================
# 🔧 Yol Ayarları
# ============================================================

THIS_FILE = pathlib.Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[1]   # repo kökü (main.py ile aynı seviye)
MAIN_PATH = PROJECT_ROOT / "main.py"


# ============================================================
# 🧠 Yardımcılar
# ============================================================

def _read_main() -> str:
    if not MAIN_PATH.exists():
        print(f"[HB-PATCHER] main.py bulunamadı: {MAIN_PATH}")
        sys.exit(1)
    return MAIN_PATH.read_text(encoding="utf-8")


def _backup_main():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = PROJECT_ROOT / f"main_backup_{ts}.py"
    shutil.copy2(MAIN_PATH, backup_path)
    print(f"[HB-PATCHER] Yedek alındı -> {backup_path.name}")


def _write_main(text: str):
    MAIN_PATH.write_text(text, encoding="utf-8")
    print(f"[HB-PATCHER] main.py güncellendi.")


# ============================================================
# 🧩 Patch Adımları
# ============================================================

def patch_add_hb_core_import(src: str) -> tuple[str, bool]:
    """
    Üst import bloğuna güvenli bir:
        import hb_core  # HB GOD-MODE core
    ekler. (Yoksa)
    Çalışmayı bozmaz, sadece paketi görünür yapar.
    """
    if "import hb_core" in src:
        return src, False

    # İlk import bloklarının sonunu bulalım (telebot / flask civarı)
    m = re.search(r"(import\s+telebot[^\n]*\n)", src)
    if not m:
        # telebot yoksa en başa ekle
        new_src = 'import hb_core  # HB GOD-MODE core\n' + src
        return new_src, True

    insert_pos = m.end()
    new_src = (
        src[:insert_pos]
        + "import hb_core  # HB GOD-MODE core\n"
        + src[insert_pos:]
    )
    return new_src, True


def patch_fix_god_layer_import(src: str) -> tuple[str, bool]:
    """
    ImportError: cannot import name 'faz13_god_pipeline'
    hatasını otomatik düzeltir.

    - from faz13_engine.faz13_god_layer import (...) bloğunu
      run_faz13_with_god_layer, faz13_god_text şeklinde günceller.
    - main.py içindeki faz13_god_pipeline( çağrılarını
      run_faz13_with_god_layer( ile değiştirir.
    """
    changed = False

    # 1) import bloğunu düzelt
    pattern = re.compile(
        r"from\s+faz13_engine\.faz13_god_layer\s+import\s*\((.*?)\)",
        re.DOTALL,
    )

    def repl(match: re.Match) -> str:
        nonlocal changed
        changed = True
        return (
            "from faz13_engine.faz13_god_layer import (\n"
            "    run_faz13_with_god_layer,\n"
            "    faz13_god_text,\n"
            ")\n"
        )

    new_src, n = pattern.subn(repl, src)
    if n > 0:
        print(f"[HB-PATCHER] GOD-LAYER import bloğu güncellendi.")
    src = new_src

    # 2) fonksiyon adını düzelt (kullanım tarafı)
    if "faz13_god_pipeline(" in src:
        src = src.replace("faz13_god_pipeline(", "run_faz13_with_god_layer(")
        changed = True
        print("[HB-PATCHER] faz13_god_pipeline() -> run_faz13_with_god_layer()")

    return src, changed


def run_all_patches():
    print("[HB-PATCHER] GOD MODE başlıyor...")
    print(f"[HB-PATCHER] Proje kökü: {PROJECT_ROOT}")
    print(f"[HB-PATCHER] Hedef dosya: {MAIN_PATH}")

    src = _read_main()
    _backup_main()

    total_changes = 0

    # 1) hb_core importu ekle
    src, changed = patch_add_hb_core_import(src)
    if changed:
        total_changes += 1

    # 2) GOD-LAYER import & fonksiyon adı fix
    src, changed = patch_fix_god_layer_import(src)
    if changed:
        total_changes += 1

    if total_changes == 0:
        print("[HB-PATCHER] Değişiklik yapılmadı (zaten güncel gibi duruyor).")
    else:
        _write_main(src)
        print(f"[HB-PATCHER] Toplam patch sayısı: {total_changes}")

    print("[HB-PATCHER] GOD MODE işlem tamam.")


# ============================================================
# 🔥 Entry Point
# ============================================================

def main():
    try:
        run_all_patches()
    except Exception as e:
        print(f"[HB-PATCHER] Kritik hata: {e}")
        raise


if __name__ == "__main__":
    main()
