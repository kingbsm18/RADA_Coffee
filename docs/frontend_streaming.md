# Frontend — Live Operations: streaming et contrats backend

Statut au moment de la rédaction, établi en lisant le dépôt (pas d'hypothèse).

## Ce qui existe (utilisé réellement par le frontend)

| Besoin | Endpoint backend |
| --- | --- |
| Authentification | `POST /api/v1/auth/login`, `GET /auth/me` (jeton Bearer) |
| Cafés | `GET /sites` |
| Événements de détection | `GET /events?site_id=` (état, catégorie, période, pagination) |
| Alertes | `GET /alerts`, `PATCH /alerts/{id}` (confirmed / false_alarm) |
| Temps réel | `WS /ws/alerts?site_id=` : jeton envoyé en **premier message**, messages `alert_created` / `alert_updated` |
| Photos | `GET /sites/{id}/images` (par catégorie et période), `GET /images/{site}/{ref}` (jeton requis) |
| Synthèses | `GET /analytics/daily`, `/daily/export.csv`, `/analytics/hourly` |
| Réglages | `GET /sites/{id}/settings` |
| Dernière synchro POS | `GET /sites/{id}/pos/imports` (dernier import terminé) |
| Santé API | `GET /health/ready` |

## Ce qui manque (isolé côté frontend, rien n'est simulé)

1. **Passerelle de flux sécurisée.** Le edge ne lit que du RTSP (`edge/video/capture.py`). Rien ne sert de HLS, WebRTC ou MJPEG, et aucun endpoint backend ne délivre d'URL de flux. Le lecteur affiche donc « Flux vidéo en direct indisponible ». Contrat attendu : `GET /sites/{site_id}/cameras/{camera_id}/stream` -> `{ "protocol": "hls", "url": "https://…", "expires_at": "…" }`, URL HTTPS à durée courte, authentifiée, sans identifiants RTSP. Seul `frontend/src/lib/streaming/source.ts` devra changer ; ajouter `hls.js` pour les navigateurs hors Safari.
2. **Liste des caméras** : `GET /sites/{site_id}/cameras` (la table `camera` existe). En attendant, les caméras sont déduites du `camera_id` des événements récents (page Cameras et sélecteur).
3. **Heartbeat edge** (état, FPS, latence, dernière image) : la barre d'état affiche « n/d » pour l'appareil edge et le traitement des détections.
4. **Boîtes englobantes** : `visual_event.v1` n'en contient pas. `lib/streaming/overlay.ts` définit le type `DetectionBox` ; aucune boîte n'est dessinée tant que le contrat n'est pas étendu.
5. **Quantités rapprochée / non rapprochée par détection** : `EventOut` n'a que `state`. Le frontend n'affiche que ce que le backend affirme (`missing_qty` de l'alerte liée ; `matched` = tout rapproché) et « — » sinon.
6. **Événements de détection en temps réel** : le WebSocket ne pousse que des alertes. Le fil d'événements est interrogé toutes les 5 s et rafraîchi à chaque message WebSocket.
7. **Historique d'audit d'une alerte** et **modification des réglages / utilisateurs / canaux de notification** : pas d'endpoint de lecture (audit) ou non exposés dans l'interface.

## Variables d'environnement

Voir `frontend/.env.example`. `NEXT_PUBLIC_API_URL` (HTTPS en production). Le backend doit autoriser l'origine du frontend dans `CORS_ORIGINS`. Aucune variable `NEXT_PUBLIC_*` ne doit contenir de secret.

## Déploiement Vercel (non effectué)

1. Importer le dépôt, **Root Directory** = `frontend`, framework Next.js (commandes par défaut).
2. Définir `NEXT_PUBLIC_API_URL` (Preview et Production).
3. Ajouter l'URL Vercel (et les URLs de preview si besoin) à `CORS_ORIGINS` du backend. Le backend doit être en HTTPS : un navigateur bloque `http://` et `ws://` depuis une page HTTPS.
4. Aucune vidéo ne transite par Vercel : le flux ira directement de la passerelle au navigateur.

Le déploiement n'a pas été réalisé ni vérifié.
