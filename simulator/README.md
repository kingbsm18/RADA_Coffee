# Simulateur

Rejoue des scénarios **sans caméra** : événements `visual_event.v1` vers le backend + CSV de ventes POS correspondant.

```bash
pip install pyyaml
python simulator/replay.py --list
python simulator/replay.py --scenario missing_sale --dry-run
export RADA_EDGE_KEY=...        # clé edge du site (affichée une seule fois à sa création)
python simulator/replay.py --scenario missing_sale --csv-out sales.csv
```
Puis importer `sales.csv` (`POST /sites/{id}/pos/import`) après avoir mappé les catégories POS :
`Boissons chaudes → coffee`, `Sodas → soft_drink` (voir `docs/pos_integration.md`).

- Les identifiants sont déterministes : rejouer deux fois la même commande ne crée aucun doublon.
  Pour un vrai nouveau rejeu, changer `--run-id` (sinon 409 si l'heure de départ a changé).
- `scenarios.yaml` : chaque élément déclare l'état final attendu (`expect`). `backend/tests/test_simulator.py`
  vérifie ces attentes avec le vrai moteur de rapprochement, donc un scénario ne peut pas mentir.
- Fenêtres des scénarios : coffee 25 min avant / 12 après, soft_drink 10 / 7, seuil de confiance 0,6.
