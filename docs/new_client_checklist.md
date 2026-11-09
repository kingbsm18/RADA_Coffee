# Nouveau client / nouveau café

1. **Organisation et admin** : premier admin via `ADMIN_USERNAME`/`ADMIN_PASSWORD` au démarrage ; ensuite un `app_user` par personne.
2. **Site** : `POST /sites` (`id` du type `cafe-02`, fuseau, devise). La clé edge n'est affichée qu'**une fois** : la noter dans un coffre.
3. **Catégories et fenêtres** : `PUT /sites/{id}/settings` (valeurs de départ : coffee 25/12 min, soft_drink 10/7 min — à mesurer ensuite ; plafond 30 min).
4. **Mapping POS → catégorie** : voir `pos_integration.md`.
5. **Import test** : un CSV d'une journée ; contrôler `earliest`/`latest`, les lignes rejetées et `unmapped`.
6. **Edge** : renseigner `edge/config.yaml` (site, zone de remise, `backend_url`) ; l'URL RTSP et la clé edge viennent d'un `.env`, jamais de Git.
7. **Caméra** : cadrage limité à la zone de remise ; sous-flux pour la détection ; horloges en NTP.
8. **Mode ombre** (R12) : enregistrer sans notifier pendant la période convenue, mesurer le bruit du café.
9. **Calibration** : fenêtres = percentile 95 des délais réels ; seuil de confiance ; puis activer les alertes fortes.
10. **Légal** : `legal_cndp.md` validé avec le responsable du site **avant** la mise en service.
