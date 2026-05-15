# CNC Energy Intelligence Platform — Project Context

## Description
Plateforme intelligente de prédiction et surveillance de la consommation énergétique des machines CNC. Projet scolaire en équipe de 5, dans le cadre de la formation Big Data / Data Science / IA.

## Status
- **Phase**: Semaine 1 — design DataOps terminé, implémentation pipeline à démarrer
- **Durée**: 3 semaines
- **Version CDC**: 2.0 (révisée, Avril 2026)
- **MVP cible**: J+15 (prédiction fonctionnelle + dashboard basique)
- **Dataset** : validé — CNC Milling Dataset, University of Michigan SMART Lab (2018)

## Objectifs
- Prédire la consommation énergétique à court terme (modèle supervisé)
- Détecter les anomalies en quasi-temps-réel
- Exposer les résultats via un dashboard accessible à des non-techniciens

## Architecture DataOps — Medallion (Bronze / Silver / Gold)

```
dataset/ (19 CSV source)
      |
      v
  BRONZE  →  Copie immuable, versioning DVC, manifest MD5
      |
      v
  SILVER  →  Validation schéma, flag défauts, gestion NaN, rapport qualité
      |
      v
   GOLD   →  Feature store complet, prêt pour le ML
      |
      v
  [ML CONSUMPTION]
```

| Couche | Format | Contenu |
|---|---|---|
| **Bronze** | CSV (inchangé) | Copie exacte des 19 fichiers source, immuable, versionné DVC (`data-v{N}`) |
| **Silver** | Parquet | 53 colonnes originales + 6 flags (`defect_feedrate_50`, `defect_position_198`, `defect_program_nonzero`, `missing_power`, `interpolated`, `validation_run_id`) |
| **Gold** | Parquet | ~80 features (lags ×5, rolling windows ×3, agrégations par phase, features croisées, join métadonnées) + 2 targets (`target_power_next_1s`, `target_power_next_3s`) |

**Décisions clés :**
- Défauts : flaggés en Silver, supprimés du training en Gold (conservés dans `diagnostics/`)
- Split : exp. 01–14 (train) / 15–16 (val) / 17–18 (test) — par numéro, pas aléatoire
- Détail complet : voir `dataops_pipeline.md`

## Architecture ML — 5 couches
1. **Ingestion (ETL)** — collecte, nettoyage, versioning via DVC
2. **Stockage** — Bronze / Silver / Gold + Model Registry (MLflow)
3. **Feature Engineering** — transformations temporelles, lags, fenêtres glissantes
4. **ML** — LightGBM/XGBoost/Prophet (prédiction) + Isolation Forest (anomalies)
5. **Serving** — FastAPI conteneurisée (Docker) + Streamlit dashboard

## Stack technique
| Composant | Technologie |
|---|---|
| Langage | Python 3.10+ |
| Modèle prédiction | LightGBM / XGBoost / Prophet |
| Anomalies | Isolation Forest (scikit-learn) |
| Versioning données | DVC |
| Tracking | MLflow |
| Monitoring dérive | Evidently |
| API | FastAPI |
| Dashboard | Streamlit |
| Conteneurisation | Docker / Docker Compose |
| Tests | pytest |

## Organisation de l'équipe — 5 modules
| Module | Responsabilité |
|---|---|
| Data Pipeline | ETL + DVC + Feature Store |
| ML | Modèle supervisé + détection anomalies + MLflow |
| MLOps | Réentraînement automatisé + CI + monitoring |
| Backend | API FastAPI + logique anomalies + retours humains |
| Frontend | Dashboard Streamlit + validation humaine |

## Planning
| Semaine | Priorités |
|---|---|
| S1 | Validation dataset · Interfaces · ETL de base · Première expérimentation ML |
| S2 | Feature engineering · Entraînement modèle · API de base · Dashboard V1 |
| S3 | Intégration · Monitoring MLflow + Evidently · Tests · Démo finale |

## Contraintes et risques clés
- **Dataset** : validé (University of Michigan SMART Lab). Fallback UCI/Kaggle non nécessaire.
- **Interfaces** : session de cadrage obligatoire en J1 (contrats JSON entre modules).
- **MVP J+15** : garantit une démo même si les couches avancées ne sont pas finalisées.
- **V2 (post-MVP)** : intégration d'un agent Reinforcement Learning.

## Documents
- `cahier_des_charges_cnc_v2.pdf` — spécification complète v2.0
- `dataset_info.md` — description complète du dataset (colonnes, axes, objectifs, rôle des moteurs)
- `dataops_pipeline.md` — design du pipeline DataOps Medallion avec checkboxes de suivi
- `dataset/` — 19 fichiers CSV sources (train.csv + experiment_01 à 18, déplacés depuis Inbox)

## Notes
- Stack 100% open source, déploiement local (pas de cloud).
- Coût estimé : 45 000 DH (300h à 150 DH/h).
- Utilisateurs cibles : opérateur machine, responsable énergie, directeur de production.
