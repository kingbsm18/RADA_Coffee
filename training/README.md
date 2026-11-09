# Entraînement (fine-tuning)

Objectif : un détecteur qui sort **directement les catégories du café** (`coffee`, `soft_drink`…), pas le produit exact.
Pas de CNN entraîné de zéro : on part d'un YOLO pré-entraîné, export final en ONNX pour `edge/`.

Pipeline (scripts présents, non revus ni exécutés ici) : `extract_frames` → `dedupe` → `split_by_day` → `train` → `evaluate` → `export_onnx`.

## Règles
- **Découpe par jour**, jamais au hasard : des images voisines dans train et test gonfleraient les scores.
- Dédupliquer les images quasi identiques avant l'annotation.
- Annoter des sessions **calmes et chargées**, de jour et de soir ; garder une vérité terrain comptée à la main.
- Respect de la vie privée : zone de remise seulement, pas de visages ; recadrer/flouter si besoin ; jeux de données hors Git
  (`training/data/` est ignoré).
- Chaque modèle exporté reçoit une `model_version`, enregistrée dans `cv_model` et envoyée dans chaque événement.
- Les cibles de précision/rappel du dossier de conception (≥ 90 % / ≥ 85 %) sont **indicatives** : à mesurer sur le café pilote.

## Licence
Ultralytics est sous AGPL-3.0 : à traiter (licence commerciale ou alternative) **avant toute commercialisation**.
