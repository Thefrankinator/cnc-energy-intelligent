# DataOps Pipeline — CNC Energy Intelligence Platform

**Architecture** : Medallion (Bronze / Silver / Gold)
**Scope** : DataOps uniquement (ingestion → qualité → stockage → feature engineering)
**Dataset** : 19 fichiers CSV — 1 metadata (`train.csv`) + 18 séries temporelles (`experiment_01` à `experiment_18`)

---

## Vue d'ensemble

```
RAW CSV FILES (19 fichiers)
        |
        v
+--------------------+
|   BRONZE LAYER     |  Données brutes, immuables, versionnées
+--------------------+
        |
        v
+--------------------+
|   SILVER LAYER     |  Données nettoyées, validées, flaggées
+--------------------+
        |
        v
+--------------------+
|    GOLD LAYER      |  Feature store prêt pour le ML
+--------------------+
        |
        v
  [ML CONSUMPTION]
```

---

## BRONZE — Données brutes immuables

> Principe : on touche à rien. On copie, on versionne, on trace.

**Entrée** : `dataset/` (19 CSV originaux)
**Sortie** : `data/bronze/` (CSV copiés, immuables)

### Checklist

- [x] Scanner le répertoire source et lister tous les fichiers `.csv`
- [x] Calculer le hash MD5 de chaque fichier
- [x] Comparer les hashs avec la version DVC précédente (skip si inchangé)
- [x] Copier `train.csv` verbatim dans `data/bronze/metadata/`
- [x] Copier `experiment_01.csv` à `experiment_18.csv` verbatim dans `data/bronze/experiments/`
- [x] Écrire le manifest par fichier : `{filename, MD5, taille_bytes, nb_lignes, ingested_at}`
- [x] Appender l'entrée dans `data/bronze/ingestion_log.jsonl`
- [x] Versionner `data/bronze/` avec DVC (`dvc add`)
- [x] Créer le tag Git `data-v{N}` associé au commit DVC
- [ ] Configurer le remote DVC partagé pour l'équipe : `dvc remote add -d team_remote /chemin/vers/dvc-store-partage` (clé USB, dossier réseau, ou SSH). Documenter le chemin dans `_context.md`.

### Structure de sortie

```
data/bronze/
├── metadata/
│   └── train.csv                  -- copie exacte, immuable
├── experiments/
│   ├── experiment_01.csv
│   ├── experiment_02.csv
│   └── ... (jusqu'à 18)
└── ingestion_log.jsonl            -- append-only, une ligne JSON par run
```

> Règle absolue : si un fichier Bronze est modifié → c'est un bug, pas une feature.

---

## SILVER — Données nettoyées et validées

> Principe : valider, nettoyer, documenter les défauts. Chaque ligne a un statut.

**Entrée** : `data/bronze/`
**Sortie** : `data/silver/` (Parquet + colonnes de flags ajoutées)

### Étape 1 — Validation schéma

#### Sur `train.csv`

- [x] Vérifier exactement 18 lignes et 7 colonnes
- [x] Vérifier colonne `No` : entiers 1..18, sans doublons, sans gaps
- [x] Vérifier `tool_condition` ∈ {`unworn`, `worn`}
- [x] Vérifier `feedrate` ∈ {3, 6, 12, 15, 20}
- [x] Vérifier `clamp_pressure` ∈ {2.5, 3.0, 4.0}
- [x] Vérifier `machining_finalized` ∈ {`yes`, `no`}
- [x] Vérifier `passed_visual_inspection` ∈ {`yes`, `no`, vide}
- [x] Vérifier l'absence de lignes entièrement nulles

#### Sur `experiment_NN.csv` (×18)

- [x] Vérifier exactement 53 colonnes par fichier *(ajusté : dataset réel = 48 cols, Z1_OutputPower absent)*
- [x] Vérifier `Machining_Process` ∈ {Starting, Prep, Layer 1 Up, Layer 1 Down, Layer 2 Up, Layer 2 Down, Layer 3 Up, Layer 3 Down} *(WARN : labels `End` et `Repositioning` présents dans le dataset, classifiés WARN)*
- [x] Vérifier `X1_OutputPower`, `Y1_OutputPower`, `S1_OutputPower` ≥ 0 *(WARN : bruit flottant < -1e-4 toléré)*
- [x] Vérifier l'absence de valeurs infinies (`+Inf`, `-Inf`) dans toutes les colonnes numériques
- [x] Vérifier qu'aucun fichier n'est vide (nb_lignes > 0)

### Étape 2 — Détection des défauts connus

> Les lignes défectueuses sont **flaggées, pas supprimées** à ce stade.

- [x] Ajouter colonne `defect_feedrate_50` : `True` si `M1_CURRENT_FEEDRATE == 50` *(6 253 lignes)*
- [x] Ajouter colonne `defect_position_198` : `True` si `X1_ActualPosition == 198` *(4 360 lignes)*
- [x] Ajouter colonne `defect_program_nonzero` : `True` si `M1_CURRENT_PROGRAM_NUMBER != 0` *(24 581 lignes — program 1 toujours actif, attendu)*
- [x] Calculer et logger le nombre de lignes défectueuses par expérience et par type

### Étape 3 — Ajout de l'index temporel

- [x] Construire la colonne `timestamp_ms` = `row_index × 100` (millisecondes depuis le début de l'expérience)
  > Note : timestamp synthétique, suffisant pour le ML batch. Pour le serving temps-réel, cette colonne devra être remplacée par l'horloge réelle de la machine.

### Étape 4 — Traitement des valeurs manquantes

- [x] Colonnes position/vitesse : forward-fill si gap ≤ 3 lignes consécutives *(0 gaps détectés dans ce dataset)*
- [x] Colonnes position/vitesse : flag `interpolated = True` si gap > 3 lignes
- [x] Colonnes power (`X1/Y1/S1_OutputPower`) manquantes : flag `missing_power = True`, **pas d'imputation** *(0 valeurs manquantes)*
- [x] Colonne `Machining_Process` : forward-fill (propager la dernière phase connue)

### Étape 5 — Rapport qualité

- [x] Générer `data/silver/quality/quality_report_{run_id}.json` avec :
  - Règles évaluées, fichiers vérifiés, lignes affectées, % affecté
  - Résumé des défauts par type et par expérience
  - Statut global : `PASS` / `WARN` / `FAIL`
- [x] Appender une ligne résumée dans `data/silver/quality/quality_summary.csv`
- [x] Si statut `FAIL` → arrêter le pipeline et logger l'erreur
- [x] Si statut `WARN` → continuer avec alerte dans les logs

### Colonnes ajoutées (Silver)

| Colonne | Type | Description |
|---|---|---|
| `timestamp_ms` | int64 | `row_index × 100` ms depuis début expérience |
| `defect_feedrate_50` | boolean | FEEDRATE == 50 |
| `defect_position_198` | boolean | X1_ActualPosition == 198 |
| `defect_program_nonzero` | boolean | PROGRAM_NUMBER != 0 |
| `missing_power` | boolean | Valeur power manquante |
| `interpolated` | boolean | Ligne forward-fillée |
| `validation_run_id` | string | ID du run de validation |

### Structure de sortie

```
data/silver/
├── experiments/
│   ├── experiment_01_silver.parquet   -- 53 cols + 6 cols flags
│   └── ... (jusqu'à 18)
├── metadata/
│   └── train_silver.parquet
└── quality/
    ├── quality_report_{run_id}.json
    └── quality_summary.csv
```

---

## GOLD — Feature Store prêt pour le ML

> Principe : données enrichies et transformées. Le ML ne doit plus rien recalculer.

**Entrée** : `data/silver/`
**Sortie** : `data/gold/` (Parquet avec ~80 features + 2 targets)

### Étape 1 — Suppression des défauts

- [x] Retirer du dataset d'entraînement toutes les lignes où `defect_feedrate_50 = True` OU `defect_position_198 = True` *(7 431 lignes supprimées, 29.4%)*
- [x] Supprimer la colonne `defect_program_nonzero` entièrement *(97.2% True = aucun signal discriminant)*
- [x] Sauvegarder les lignes défectueuses séparément dans `data/gold/diagnostics/defect_rows.parquet`
- [x] Logger par expérience : `{nb_lignes_avant, nb_lignes_supprimées, nb_lignes_après, pct_supprimé}`

### Étape 2 — Join métadonnées

- [x] Joindre `train_silver.parquet` à chaque série temporelle via le numéro d'expérience
- [x] Encoder `tool_condition` → 0 (unworn) / 1 (worn) → `tool_condition_enc`
- [x] Encoder `machining_finalized` → 0 (no) / 1 (yes) → `machining_finalized_enc`
- [x] Encoder `passed_visual_inspection` → 0 (no) / 1 (yes) / -1 (manquant) → `passed_visual_inspection_enc`
- [x] Propager les colonnes métadonnées sur toutes les lignes de chaque expérience (broadcast)

### Étape 3 — Encodage des phases

> **Contrainte d'implémentation** : `phase_row_index` et `phase_duration_rows` doivent être calculés par expérience, puis par phase au sein de chaque expérience. Utiliser `groupby(['experiment_id', 'phase_id'])`. Ne jamais calculer ces features sur le dataframe global concaténé.

- [x] Créer `phase_id` : encodage ordinal (Starting=0, Prep=1, Layer1Up=2, Layer1Down=3, Layer2Up=4, Layer2Down=5, Layer3Up=6, Layer3Down=7, End=8, Repositioning=9) *(End et Repositioning ajoutés — présents dans le dataset réel)*
- [x] Créer `is_cutting_phase` : `True` uniquement pour Layer X Up/Down (phase_id 2–7)
- [x] Créer `phase_row_index` : position de la ligne dans la phase courante (remis à 0 à chaque changement de phase)
- [x] Créer `phase_duration_rows` : durée totale de la phase (en nombre de lignes)

### Étape 4 — Features temporelles (lags)

> Appliqués sur : `X1_OutputPower`, `Y1_OutputPower`, `S1_OutputPower`, `M1_CURRENT_FEEDRATE`

> **Contrainte d'implémentation** : tous les lags doivent être calculés à l'intérieur des frontières d'expérience. Utiliser `df.groupby('experiment_id', group_keys=False).apply(lambda g: g.assign(...))`. Ne jamais appliquer `shift()` sur le dataframe global concaténé — la fin de l'expérience N polluerait le début de l'expérience N+1.

- [x] Calculer lag 1 (= 100ms en arrière) pour les 4 colonnes cibles
- [x] Calculer lag 5 (= 500ms)
- [x] Calculer lag 10 (= 1 seconde)
- [x] Calculer lag 30 (= 3 secondes)
- [x] Calculer lag 60 (= 6 secondes)
- [x] Nommage : `{col}_lag_{N}` — ex: `X1_OutputPower_lag_5`

### Étape 5 — Fenêtres glissantes (rolling)

> Appliqués sur les mêmes 4 colonnes cibles

> **Contrainte d'implémentation** : même règle que les lags — appliquer `rolling()` par groupe d'expérience uniquement (`groupby('experiment_id', group_keys=False).apply(...)`). Ne jamais appliquer sur le dataframe global.

- [x] Rolling window 10 lignes (1s) → mean, std, min, max
- [x] Rolling window 30 lignes (3s) → mean, std
- [x] Rolling window 60 lignes (6s) → mean
- [x] Nommage : `{col}_roll{W}_{stat}` — ex: `X1_OutputPower_roll10_mean`

### Étape 6 — Agrégations par phase

> **Contrainte d'implémentation** : calculer par `groupby(['experiment_id', 'phase_id'])`, puis broadcaster les valeurs agrégées sur toutes les lignes du groupe avec `transform()`.

- [x] Calculer `phase_power_total` : somme (X1 + Y1 + S1 OutputPower) sur toute la phase courante
- [x] Calculer `phase_power_mean` : moyenne de la puissance totale sur la phase
- [x] Calculer `phase_power_peak` : maximum de la puissance totale sur la phase
- [x] Calculer `phase_energy_kwh` : `phase_power_mean × phase_duration_rows × 0.1 / 3600`
- [x] Propager ces valeurs sur chaque ligne de la phase (broadcast)

### Étape 7 — Features croisées

- [x] Calculer `total_output_power` = X1 + Y1 + S1 OutputPower
- [x] Calculer `power_spindle_ratio` = S1_OutputPower / (total_output_power + 1e-9)
- [x] Calculer `xy_power_ratio` = X1_OutputPower / (Y1_OutputPower + 1e-9)
- [x] Calculer `velocity_magnitude_xy` = sqrt(X1_ActualVelocity^2 + Y1_ActualVelocity^2)

### Étape 8 — Définition des targets

- [x] Créer `target_power_next_1s` = `total_output_power` décalé de -10 lignes
- [x] Créer `target_power_next_3s` = `total_output_power` décalé de -30 lignes
- [x] Supprimer les lignes sans target valide (NaN en fin d'expérience) *(540 lignes supprimées — 30 par expérience)*

### Étape 9 — Split et export

- [x] Expériences 01–14 → `data/gold/train_gold.parquet` *(12 398 lignes)*
- [x] Expériences 15–16 → `data/gold/validation_gold.parquet` *(1 042 lignes)*
- [x] Expériences 17–18 → `data/gold/test_gold.parquet` *(3 875 lignes — held-out)*
- [x] Exporter un fichier par expérience dans `data/gold/per_experiment/`
- [x] Générer `data/gold/feature_registry.json` — **123 entrées (121 features + 2 targets)** — **schéma obligatoire par entrée** :

```json
{
  "feature_name": "X1_OutputPower_lag_5",
  "dtype": "float64",
  "source_column": "X1_OutputPower",
  "transformation": "lag_5 (500ms lookback)",
  "layer": "gold",
  "is_target": false,
  "notes": "Appliqué dans les frontières d'expérience uniquement"
}
```

> Toutes les features ET les targets doivent avoir une entrée dans ce fichier. C'est le contrat d'interface entre le module Data Pipeline et le module ML.

### Structure de sortie

```
data/gold/
├── train_gold.parquet              -- 123 cols, 12 398 lignes, exp 01-14
├── validation_gold.parquet         -- 123 cols, 1 042 lignes, exp 15-16
├── test_gold.parquet               -- 123 cols, 3 875 lignes, exp 17-18 (held-out)
├── per_experiment/
│   ├── experiment_01_gold.parquet
│   └── ... (18 fichiers)
├── diagnostics/
│   └── defect_rows.parquet         -- 7 431 lignes défectueuses pour analyse
├── feature_registry.json           -- 123 entrées (121 features + 2 targets)
└── gold_recap.md                   -- recap complet avec descriptions des features
```

### Note — Politique NaN au serving (à implémenter dans FastAPI, pas ici)

> Si `missing_power = True` sur une ligne entrante à l'inférence, l'API FastAPI doit retourner :
> ```json
> { "prediction": null, "reason": "missing_power" }
> ```
> **Le modèle ML ne doit jamais recevoir une ligne avec NaN dans les colonnes power.** Ce garde-fou est la responsabilité du module Backend (FastAPI), pas du module ML.

---

## Contrats de données entre couches

| Passage | Format | Colonnes clés |
|---|---|---|
| Source → Bronze | CSV (copie exacte) | `file_hash`, `ingested_at` |
| Bronze → Silver | Parquet (48 cols + 7 flags) | `experiment_id`, flags défauts, `timestamp_ms` |
| Silver → Gold | Parquet (123 cols — 121 features + 2 targets) | `experiment_id`, `gold_run_id`, targets |

---

## Règles de rejeu (pipeline idempotent)

- [x] Si les hashs MD5 n'ont pas changé → Bronze skippé
- [x] Si `data/silver/` est plus récent que `data/bronze/` → Silver skippé
- [x] Si `data/gold/` est plus récent que `data/silver/` → Gold skippé
- [x] Chaque run est traçable via `run_id` (UUID) présent dans les logs et les fichiers Parquet
