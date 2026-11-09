# Simulateur

Rejoue des scénarios de café synthétiques (`scenarios.yaml` : `calm`, `rush`, `ambiguous`, `void`, `refund`) à travers le
**vrai pipeline edge** (`ByteTrackLite`, zones, événements de remise), sans caméra.

```bash
pip install numpy pyyaml                      # + les dépendances de edge/requirements.txt
PYTHONPATH=. python simulator/replay.py --scenario calm --output out.json    # depuis la racine du dépôt
```
Options : `--scenario` (nom dans le YAML), `--scenarios` (chemin du YAML, défaut `simulator/scenarios.yaml`),
`--output` (fichier JSON, `-` pour la sortie standard).

> Cette page est rédigée d'après le code source : je n'ai pas exécuté `replay.py` (il demande numpy et les modules `edge/`).
> Les identifiants et les horodatages sont en UTC.
