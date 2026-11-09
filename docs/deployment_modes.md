# Modes de déploiement

Le code ne change pas, seule la configuration change.

| Mode | Où tourne quoi | Usage |
|---|---|---|
| **dev** | tout sur le PC (`make dev`) ; simulateur à la place de la caméra | développement |
| **local** | edge + backend + base sur une machine du café | pilote sans cloud |
| **hybrid** (recommandé) | edge au café ; backend + base dans le cloud | produit multi-cafés |
| **cloud** | vidéos enregistrées ou simulateur seulement, jamais de flux en direct | démos, tests |

Dans tous les modes : le flux caméra est lu par `edge/` sur le réseau du café et seuls des **événements légers**
(et éventuellement des photos) sortent.

## Réglages par mode
- `ENVIRONMENT=dev` en développement ; `local`/`hybrid`/`cloud` imposent `SECRET_KEY` ≥ 32 caractères aléatoires,
  `ADMIN_PASSWORD` ≥ 12 caractères et un mot de passe de base ≠ `change_me`.
- Photos : `STORAGE_BACKEND=local` (disque) ou `s3` (`S3_BUCKET`, extra `pip install -e ".[s3]"` ; **non testé sur un vrai bucket**).
  Politique d'envoi côté edge : `always | on_alert | never` (champ `snapshot_upload_policy` du site).
- Docs OpenAPI (`/docs`) désactivées hors dev.

## Démarrage
```bash
cp .env.example .env        # puis remplir les secrets
make dev                    # compose dev : base + backend (alembic upgrade head) + frontend
# production : alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Les fichiers `docker-compose.{local,edge,cloud}.yml` sont encore vides.

## Exploitation
- Sauvegarde PostgreSQL quotidienne (`pg_dump`) **et test de restauration** ; surveiller le disque (photos, logs).
- HTTPS obligatoire devant le backend (reverse proxy) dès que le dashboard ou l'edge ne sont pas sur la même machine.
- NTP sur toutes les machines. Jamais d'identifiants caméra/POS dans Git ni dans les logs.
- Mode hybride : vérifier avec le responsable du site où les données sont hébergées (voir `legal_cndp.md`).
