"""
Bronze Layer — CNC Energy Intelligence Platform
Ingestion immuable des fichiers CSV sources.

Usage:
    python src/bronze/ingest.py

Produit:
    data/bronze/metadata/train.csv
    data/bronze/experiments/experiment_NN.csv  (×18)
    data/bronze/ingestion_log.jsonl            (append-only)
"""

import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR   = PROJECT_ROOT / "dataset"
BRONZE_DIR   = PROJECT_ROOT / "data" / "bronze"
METADATA_DIR = BRONZE_DIR / "metadata"
EXPERIMENTS_DIR = BRONZE_DIR / "experiments"
LOG_FILE     = BRONZE_DIR / "ingestion_log.jsonl"


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

# Calcul du hash MD5 d'un fichier (en lisant par chunks pour les gros fichiers)
def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def count_lines(path: Path) -> int:
    """Compte les lignes (en-tête inclus)."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


def load_last_hashes() -> dict[str, str]:
    """Charge les MD5 du dernier run depuis ingestion_log.jsonl.
    Retourne {filename: md5} ou {} si aucun log existant."""
    if not LOG_FILE.exists():
        return {}
    last_run: dict = {}
    with LOG_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entry = json.loads(line)
                # Chaque entrée de log est un dict {"run_id": ..., "files": [...]}
                for file_info in entry.get("files", []):
                    last_run[file_info["filename"]] = file_info["md5"]
    return last_run


def append_log(entry: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# DVC (optionnel — graceful fallback si non installé)
# ---------------------------------------------------------------------------

def run_dvc_add() -> bool:
    """Lance `dvc add data/bronze`. Retourne True si succès."""
    try:
        result = subprocess.run(
            ["dvc", "add", str(BRONZE_DIR.relative_to(PROJECT_ROOT))],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  [DVC] Avertissement : dvc add a échoué.\n{result.stderr.strip()}")
            return False
        print("  [DVC] data/bronze versionné avec succès.")
        return True
    except FileNotFoundError:
        print("  [DVC] dvc non installé — versioning ignoré.")
        return False


def create_git_tag(tag_name: str) -> None:
    """Crée un tag Git pour marquer la version des données."""
    try:
        subprocess.run(
            ["git", "tag", tag_name],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        print(f"  [Git] Tag '{tag_name}' créé.")
    except FileNotFoundError:
        print("  [Git] git non disponible — tag ignoré.")


def get_next_data_version() -> int:
    """Détermine le prochain numéro de version en lisant les tags Git existants."""
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "data-v*"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        tags = [t.strip() for t in result.stdout.splitlines() if t.strip()]
        if not tags:
            return 1
        versions = []
        for tag in tags:
            try:
                versions.append(int(tag.replace("data-v", "")))
            except ValueError:
                pass
        return max(versions) + 1 if versions else 1
    except FileNotFoundError:
        return 1


# ---------------------------------------------------------------------------
# Logique principale
# ---------------------------------------------------------------------------

def ingest() -> None:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\n=== Bronze Ingestion — run_id: {run_id} ===")
    print(f"    Source  : {SOURCE_DIR}")
    print(f"    Cible   : {BRONZE_DIR}\n")

    # Vérification répertoire source
    if not SOURCE_DIR.exists():
        print(f"[ERREUR] Répertoire source introuvable : {SOURCE_DIR}")
        sys.exit(1)

    # Lister tous les CSV sources
    csv_files = sorted(SOURCE_DIR.glob("*.csv"))
    if not csv_files:
        print("[ERREUR] Aucun fichier CSV trouvé dans le répertoire source.")
        sys.exit(1)
    print(f"  {len(csv_files)} fichier(s) CSV détecté(s).")

    # Charger les hashs du run précédent pour la détection de changements
    previous_hashes = load_last_hashes()

    # Créer les dossiers de destination
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)

    # Ingérer chaque fichier
    files_log = []
    skipped = 0
    copied = 0

    for src_path in csv_files:
        file_hash = md5(src_path)
        prev_hash = previous_hashes.get(src_path.name)

        if prev_hash == file_hash:
            print(f"  [SKIP] {src_path.name} — inchangé (MD5 identique)")
            skipped += 1
            # On réenregistre quand même dans le log pour garder le manifest complet
            dest = METADATA_DIR / src_path.name if src_path.name == "train.csv" else EXPERIMENTS_DIR / src_path.name
            files_log.append({
                "filename": src_path.name,
                "md5": file_hash,
                "size_bytes": src_path.stat().st_size,
                "nb_lines": count_lines(src_path),
                "destination": str(dest.relative_to(PROJECT_ROOT)),
                "status": "skipped_unchanged",
            })
            continue

        # Déterminer destination
        if src_path.name == "train.csv":
            dest = METADATA_DIR / src_path.name
        else:
            dest = EXPERIMENTS_DIR / src_path.name

        # Copie verbatim (préserve métadonnées fichier)
        shutil.copy2(src_path, dest)

        nb_lines = count_lines(src_path)
        size_bytes = src_path.stat().st_size

        print(f"  [COPY] {src_path.name} -> {dest.relative_to(PROJECT_ROOT)}  "
              f"({size_bytes:,} octets, {nb_lines} lignes, MD5: {file_hash[:8]}...)")
        copied += 1

        files_log.append({
            "filename": src_path.name,
            "md5": file_hash,
            "size_bytes": size_bytes,
            "nb_lines": nb_lines,
            "destination": str(dest.relative_to(PROJECT_ROOT)),
            "status": "copied",
        })

    # Vérification d'intégrité post-copie
    print("\n  Vérification d'intégrité des copies...")
    errors = []
    for entry in files_log:
        if entry["status"] == "skipped_unchanged":
            continue
        dest_path = PROJECT_ROOT / entry["destination"]
        actual_hash = md5(dest_path)
        if actual_hash != entry["md5"]:
            errors.append(f"  [ERREUR INTÉGRITÉ] {entry['filename']} — hash différent après copie !")
    if errors:
        for e in errors:
            print(e)
        sys.exit(1)
    print(f"  Intégrité OK — {copied} fichier(s) copié(s), {skipped} ignoré(s).\n")

    # Écrire dans le log append-only
    log_entry = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(SOURCE_DIR),
        "nb_files_total": len(csv_files),
        "nb_copied": copied,
        "nb_skipped": skipped,
        "files": files_log,
    }
    append_log(log_entry)
    print(f"  Log appended -> {LOG_FILE.relative_to(PROJECT_ROOT)}")

    # DVC versioning (seulement si au moins un fichier a été copié)
    if copied > 0:
        version = get_next_data_version()
        dvc_ok = run_dvc_add()
        if dvc_ok:
            create_git_tag(f"data-v{version}")
    else:
        print("  [DVC] Aucun nouveau fichier — versioning ignoré.")

    print(f"\n=== Bronze ingestion terminée. run_id: {run_id} ===\n")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ingest()
