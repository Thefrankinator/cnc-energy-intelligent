# Dataset Info — CNC Milling (University of Michigan)

**Source** : University of Michigan — SMART Lab (System-level Manufacturing and Automation Research Testbed)
**Date** : Avril 2018

---

## Contexte général

Des expériences d'usinage ont été réalisées sur des blocs de **cire** (2" x 2" x 1.5") à l'aide d'une **fraiseuse CNC**. Chaque expérience consiste à graver une forme en "S" sur la face supérieure du bloc. Au total, **18 expériences** ont été conduites avec différentes combinaisons de paramètres (vitesse d'avance, pression de serrage, état de l'outil).

---

## Structure du dataset

### 1. `train.csv` — Données générales (18 lignes = 18 expériences)

| Variable | Description |
|---|---|
| `No` | Numéro de l'expérience (1 à 18) |
| `material` | Matériau usiné — toujours `wax` (cire) |
| `feedrate` | Vitesse d'avance de l'outil (mm/s) — valeurs : 3, 6, 12, 15, 20 |
| `clamp_pressure` | Pression de serrage du bloc dans l'étau (bar) — valeurs : 2.5, 3.0, 4.0 |
| `tool_condition` | État de l'outil : `unworn` (neuf) ou `worn` (usé) |
| `machining_finalized` | Usinage terminé sans incident ? (`yes` / `no`) |
| `passed_visual_inspection` | Pièce validée visuellement ? (`yes` / `no` / vide si usinage non terminé) |

**Distribution** :
- 8 expériences avec outil **neuf** (unworn)
- 10 expériences avec outil **usé** (worn)

---

### 2. `experiment_01.csv` à `experiment_18.csv` — Séries temporelles

- **Fréquence d'échantillonnage** : 100 ms par point ( entre 2 lignes on a 100 ms qui se sont ecoulées)
- **Contenu** : mesures en temps réel des 4 moteurs de la CNC

#### Axe X (X1)
| Variable | Unité |
|---|---|
| `X1_ActualPosition` | Position réelle (mm) |
| `X1_ActualVelocity` | Vitesse réelle (mm/s) |
| `X1_ActualAcceleration` | Accélération réelle (mm/s²) |
| `X1_CommandPosition` | Position de référence (mm) |
| `X1_CommandVelocity` | Vitesse de référence (mm/s) |
| `X1_CommandAcceleration` | Accélération de référence (mm/s²) |
| `X1_CurrentFeedback` | Courant de retour (A) |
| `X1_DCBusVoltage` | Tension bus DC (V) |
| `X1_OutputCurrent` | Courant de sortie (A) |
| `X1_OutputVoltage` | Tension de sortie (V) |
| `X1_OutputPower` | **Puissance de sortie (kW)** |

#### Axes Y (Y1) et Z (Z1)
Mêmes variables que X1, appliquées aux axes Y et Z.

> Note : Z1 n'a pas de variable `OutputPower`.

---

### Rôle des axes X, Y, Z

Les 3 axes représentent les **directions de déplacement de l'outil** dans l'espace :

```
        Z (haut/bas)
        |
        |
        |_______ X (gauche/droite)
       /
      /
     Y (avant/arrière)
```

- **X** — déplacement horizontal gauche/droite
- **Y** — déplacement horizontal avant/arrière
- **Z** — déplacement vertical haut/bas (profondeur de coupe)

Lors de la gravure du "S" dans la cire :
- **X et Y** bougent ensemble pour dessiner la forme
- **Z** descend progressivement à chaque couche — c'est pourquoi on a `Layer 1`, `Layer 2`, `Layer 3`

Du point de vue énergétique :
- **S1 (broche)** consomme le plus — elle fait tourner l'outil
- **X et Y** consomment selon la vitesse d'avance (feedrate)
- **Z** consomme peu, il descend lentement

#### Broche / Spindle (S1)
| Variable | Unité |
|---|---|
| `S1_ActualPosition` | Position réelle (mm) |
| `S1_ActualVelocity` | Vitesse réelle (mm/s) |
| `S1_ActualAcceleration` | Accélération réelle (mm/s²) |
| `S1_CommandPosition` | Position de référence (mm) |
| `S1_CommandVelocity` | Vitesse de référence (mm/s) |
| `S1_CommandAcceleration` | Accélération de référence (mm/s²) |
| `S1_CurrentFeedback` | Courant de retour (A) |
| `S1_DCBusVoltage` | Tension bus DC (V) |
| `S1_OutputCurrent` | Courant de sortie (A) |
| `S1_OutputVoltage` | Tension de sortie (V) |
| `S1_OutputPower` | **Puissance de sortie (kW)** |
| `S1_SystemInertia` | Inertie du système (kg·m²) |

#### Métadonnées programme (M1)
| Variable | Description |
|---|---|
| `M1_CURRENT_PROGRAM_NUMBER` | Numéro du programme G-code actif |
| `M1_sequence_number` | Ligne du G-code en cours d'exécution |
| `M1_CURRENT_FEEDRATE` | Vitesse d'avance instantanée de la broche |

#### Phase d'usinage
| Variable | Description |
|---|---|
| `Machining_Process` | Phase en cours : `Starting`, `Prep`, `Layer 1 Up`, `Layer 1 Down`, `Layer 2 Up`, `Layer 2 Down`, `Layer 3 Up`, `Layer 3 Down` |

---

## Objectifs analytiques

### 1. Détection d'usure de l'outil
Classification binaire supervisée : **worn** vs **unworn**.
- 8 expériences outil neuf / 10 expériences outil usé.

### 2. Détection de serrage insuffisant
Identifier quand la pression de serrage est trop faible pour maintenir la pièce en place.
- Risque de déplacement → usinage interrompu (`machining_finalized = no`)
- Défauts visuels → pièce rejetée (`passed_visual_inspection = no`)

### 3. Prédiction des défauts visuels
Estimer si la pièce finale passera l'inspection qualité, à partir des signaux machines.

### 4. Analyse énergétique (angle principal du projet)
Les variables de **puissance** (`X1_OutputPower`, `Y1_OutputPower`, `S1_OutputPower`) et de **courant/tension** permettent d'analyser :
- L'impact de l'**état de l'outil** (usé vs. neuf) sur la consommation énergétique
- L'influence de la **vitesse d'avance** (feedrate) et de la **pression de serrage** sur l'énergie consommée
- La détection d'**anomalies énergétiques** liées à des conditions d'usinage dégradées
- L'optimisation de la **consommation par phase** d'usinage (Layer 1, 2, 3)

---

## Notes importantes

- Certaines variables peuvent contenir des **erreurs de mesure** détectables quand :
  - `M1_CURRENT_FEEDRATE` = 50
  - `X1_ActualPosition` = 198
  - `M1_CURRENT_PROGRAM_NUMBER` ≠ 0
- La source de ces erreurs n'a pas été identifiée par les auteurs du dataset.
