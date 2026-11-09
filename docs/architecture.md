# Architecture

Monolithe modulaire (pas de microservices). Le flux caméra n'entre **jamais** dans le backend.

```
Caméra IP ──RTSP──▶ edge/ (détection YOLO + ByteTrack, zone de remise)
                      │  visual_event.v1 (HTTPS, X-Edge-Key, outbox SQLite)
                      ▼
POS ─(CSV | API)─▶ backend/ FastAPI ──▶ PostgreSQL
                      │  moteur pur (engine/) : crédits, rapprochement, alertes
                      ▼
                 frontend/ Next.js  ◀── WebSocket (alertes en direct)
```

## Règles de conception
- Heures en UTC (`TIMESTAMPTZ`), montants en `NUMERIC`/`Decimal` (jamais float, JSON = chaînes).
- Moteur = fonctions pures qui reçoivent `now` et les réglages (aucun accès horloge/base dedans).
- Idempotence partout : `(site_id, event_id)`, `(site_id, external_id)`, une alerte par détection.
- `site_id` dans toutes les tables ; fenêtres, seuils, catégories en configuration par site.
- Vocabulaire : « perte estimée », « écart à vérifier ». Jamais « vol » ni « fraude prouvée ».

## Authentification
- **Dashboard** : `POST /auth/login` → JWT (HS256, 60 min), rôles `admin` / `manager`. Blocage après 5 échecs / 5 min.
- **Edge** : une clé par site (`X-Edge-Key`), seul son hash SHA-256 est stocké ; rotation par un admin.
  Cette clé ne peut qu'écrire (événements, photos) pour son propre site.
- Un utilisateur ne voit que les sites de son organisation (404 sinon).
- Les accès aux photos et les revues d'alertes sont journalisés (`audit_log`).

## API (`/api/v1`)
| Domaine | Endpoints |
|---|---|
| Santé | `GET /health`, `GET /health/ready` |
| Auth | `POST /auth/login`, `GET /auth/me` |
| Sites | `GET/POST /sites`, `GET /sites/{id}`, `POST /sites/{id}/edge-key/rotate` |
| Réglages | `GET/PUT /sites/{id}/settings`, `GET/PUT /sites/{id}/category-mappings` |
| POS | `POST /sites/{id}/pos/import` (CSV), `GET /sites/{id}/pos/imports` |
| Événements | `POST /events` (edge, idempotent), `GET /events` |
| Alertes | `GET /alerts`, `GET/PATCH /alerts/{id}` (confirmed / false_alarm) |
| Photos | `POST /images` (edge), `GET /sites/{id}/images`, `GET /images/{site}/{ref}` |
| Analyses | `GET /analytics/daily`, `/daily/export.csv`, `/hourly` |
| Temps réel | `WS /ws/alerts?site_id=…` (le jeton est le **premier message**, pas dans l'URL) |

## Tables
`organization`, `site`, `camera`, `app_user`, `category`, `category_mapping`, `site_settings`,
`pos_sale`, `pos_import_batch`, `detection`, `credit_link`, `alert`, `daily_summary`,
`hourly_summary`, `cv_model`, `site_model`, `audit_log`. Migrations : `backend/migrations` (Alembic).

## Configuration (variables d'environnement)
`ENVIRONMENT` (dev|local|hybrid|cloud — hors dev : secrets forts exigés), `DATABASE_URL`, `SECRET_KEY`,
`ADMIN_USERNAME`/`ADMIN_PASSWORD` (premier admin), `CORS_ORIGINS`, `STORAGE_BACKEND` (local|s3),
`SNAPSHOT_DIR`, `SNAPSHOT_MAX_BYTES`, `SNAPSHOT_RETENTION_DAYS`, `S3_BUCKET`, `POS_IMPORT_MAX_BYTES`,
`MAX_FUTURE_SKEW_SECONDS`, `FEATURE_FLAGS`. Défauts : `backend/app/config.py`.

## État d'avancement
| Fait et testé (439 tests backend, SQLite et PostgreSQL 16) | Présent mais non branché | À faire |
|---|---|---|
| API, auth, modèles, migration, import CSV, stockage, WebSocket, résumés, `engine/credits`, `engine/reconcile` | `edge/` (détection, tracking, événements, outbox), `training/` (scripts), `simulator/`, `engine/pricing`, `cancellations`, `finalize`, `loss`, `noise_baseline`, `scheduler` : écrits côté équipe ; seuls les tests du backend sont exécutés en continu (les tests `pricing`, `loss`, `noise_baseline`… passent), `edge/` et `training/` ne sont pas testés ici | cycle de rapprochement en base (relier `reconcile`, `alert_service`, annulations R8, fin de service R13), pages du frontend, purge de rétention, export PDF, adaptateur API du POS |

## Fuseau horaire
Le Maroc est repassé à UTC+0 le 2026-09-20. Le backend vérifie au démarrage (hors dev) que sa base de
fuseaux horaires le sait. Caméra, machine edge et caisse doivent être sur une version à jour et en NTP :
un décalage d'une heure casserait les fenêtres de rapprochement (5 à 30 min).
