# Règles métier — source de vérité

Référence absolue du moteur de réconciliation (`backend/app/engine/`). Ne pas modifier une règle
silencieusement : proposer le changement, attendre l'accord, puis mettre à jour ce fichier et les tests.

## Principe

RADA AI détecte les **articles servis jamais enregistrés dans la caisse (POS)**. La caméra observe la zone de
remise, le POS fournit les ventes avec leur catégorie, le système compare **par catégorie** et chiffre l'écart
en MAD. Il n'accuse jamais un employé : il signale un « écart à vérifier » avec des photos (jamais de vidéo).

Hors périmètre : gestion de stock, surveillance des employés, reconnaissance faciale, identification du
produit exact.

## Règles R1 à R13

- **R1.** Un seul sens : servi sans vente (CV > POS). Une vente sans article détecté est ignorée et ne crée
  jamais de perte.
- **R2.** Comparaison par catégorie, jamais par commande. L'écart de temps entre articles de catégories
  différentes n'a aucune importance.
- **R3.** Une vente POS payée crée un crédit par unité dans sa catégorie (avec son heure et son prix). Un
  article offert saisi à 0 MAD crée aussi un crédit.
- **R4.** Une détection = un événement unique par article (le tracking évite un événement par image).
  Champs : `event_id`, heure, catégorie, `count`, confiance, `snapshot_ref`. Si `count = N`, elle représente
  N unités.
- **R5.** Deux fenêtres par catégorie et par site : `lookback` (une vente reste valable jusqu'à N minutes
  AVANT l'article, soit le temps de préparation) et `grace` (on attend N minutes APRÈS l'article avant de
  conclure).
- **R6.** Rapprochement : chaque unité détectée prend le plus ancien crédit libre de sa catégorie dont
  l'heure de VENTE est dans `[det.ts - lookback, det.ts + grace]`. Détections traitées de la plus ancienne à
  la plus récente (résultat reproductible).
- **R7.** Décision à l'échéance seulement : à l'instant de la détection, l'absence de vente ne veut rien
  dire. La détection reste `pending` jusqu'à `det.ts + grace`. Sans crédit à ce moment : anomalie.
- **R8.** Annulation ou remboursement après service : si la vente qui servait de crédit passe à `voided` ou
  `refunded`, la détection liée redevient non rapprochée et devient une anomalie (subtype
  `cancelled_after_service`).
- **R9.** Détection sous le seuil de confiance du site : pas d'anomalie, état `low_confidence` (résumé
  « à vérifier »), jamais comptée dans la perte.
- **R10.** Perte estimée = quantité manquante × prix moyen pondéré de la catégorie (ventes payées des 30
  derniers jours ; ventes à 0 MAD et annulées EXCLUES du calcul ; mis à jour chaque nuit). Fourchette =
  quantité × prix min à quantité × prix max. Montant FIGÉ dans l'alerte à sa création.
- **R11. Validation humaine facultative et gestion par exception.**
  - La création d'une anomalie ne nécessite aucune intervention humaine. Une anomalie est enregistrée
    automatiquement à l'expiration de `grace`.
  - Son état initial est `anomaly`. Elle reste dans cet état tant qu'aucune décision humaine n'est prise.
  - Le gérant n'est jamais obligé de confirmer ou de rejeter chaque anomalie.
  - Le dashboard présente les anomalies regroupées par site, période, catégorie et niveau de priorité.
  - Les notifications sont réservées aux écarts dépassant le seuil défini par R12. Une notification ne
    nécessite pas d'accusé de réception pour que le moteur continue à fonctionner.
  - Le gérant peut consulter les anomalies individuellement ou examiner un groupe d'anomalies avec les
    photos contextuelles correspondantes.
  - Une anomalie non examinée reste `anomaly` : elle n'est jamais automatiquement considérée comme
    confirmée ou comme une fausse alerte.
  - Deux indicateurs sont maintenus :
    - Perte détectée : montant estimé des anomalies non résolues, avant validation humaine.
    - Perte confirmée : montant des anomalies explicitement confirmées par le gérant.
  - Les anomalies `false_alarm` sont exclues de la perte confirmée. Les anomalies `auto_resolved` sont
    exclues du rapport officiel après recalcul R13.
  - Toute décision humaine est horodatée et associée à l'utilisateur qui l'a prise.
- **R12.** Niveau de bruit : mesuré en mode ombre par café ; les alertes fortes (notification) ne partent
  que si l'écart dépasse nettement ce niveau. Toutes les anomalies restent enregistrées.
- **R13.** Recalcul de fin de service : toute anomalie dont une vente correspondante existe finalement (vente
  saisie tard ou synchronisée tard) passe en `auto_resolved` (jamais supprimée). Le rapport officiel est
  celui d'après ce recalcul.

## Précisions

- Le rapprochement utilise l'**heure de la vente** (event time), jamais l'heure d'import. Un retard de
  synchronisation de l'API est corrigé par R13.
- Fenêtre bornée : le crédit doit être dans `[det.ts - lookback, det.ts + grace]`. Ne jamais utiliser `now`
  comme borne haute sans la plafonner à `det.ts + grace`.
- Un crédit n'est consommé qu'une fois. Un crédit jamais consommé est ignoré (aucune alerte, aucune perte).
- Idempotence : relancer le moteur ne crée jamais deux alertes pour la même détection (clé unique par
  détection).
- Heures en UTC (`TIMESTAMPTZ`). Montants en `NUMERIC` / `Decimal`, jamais float. Moteur = fonctions pures qui
  reçoivent `now` et les réglages en paramètres (jamais `datetime.now()` dedans).
- Vocabulaire : « perte estimée », « écart à vérifier ». Jamais « vol », « fraude prouvée » ou
  « perte exacte ».

## États d'une détection

`pending`, `matched`, `low_confidence`, `anomaly`, `confirmed`, `false_alarm`, `auto_resolved`.

Correspondance avec l'implémentation : une anomalie non examinée est une alerte au statut `open` (la détection
est à l'état `anomaly`) ; `confirmed` et `false_alarm` sont les seules décisions humaines possibles.

## Valeurs de départ (à mesurer ensuite : percentile 95 du délai réel)

| Catégorie | lookback | grace |
|---|---|---|
| coffee | 20-30 min | 10-15 min |
| soft_drink | 10 min | 5-10 min |

Plafond absolu : 30 min (appliqué dans `engine/types.py`, `MAX_WINDOW`).

## Algorithme de référence

```python
def cycle(site, now):
    for det in detections_pending(site):                 # oldest first
        window_end = min(now, det.ts + grace[det.category])
        credit = oldest_free_credit(site, det.category,
                                    start=det.ts - lookback[det.category], end=window_end)
        if credit:
            link(det, credit)                            # matched
        elif now >= det.ts + grace[det.category]:
            if det.confidence >= threshold[site]:
                create_anomaly(det, loss=estimated_loss(det.category))
            else:
                mark_low_confidence(det)
        # else: still pending

def on_cancellation(sale):                               # R8
    for det in detections_linked_to(sale):
        unlink(det)
        create_anomaly(det, subtype="cancelled_after_service")
```

## Questions ouvertes (à trancher avant de coder `reconcile.py` / `cancellations.py`)

Ne sont PAS des règles décidées.

1. **R8 :** après annulation de la vente liée, la détection cherche-t-elle d'abord un autre crédit libre dans
   sa fenêtre (re-rapprochement), ou devient-elle immédiatement anomalie `cancelled_after_service` ?
2. **R4 / R6 :** si `count = 3` et seulement 2 crédits disponibles, la détection est-elle découpée en unités
   (2 rapprochées + 1 anomalie) ou reste-t-elle un seul objet avec un état partiel ?
3. **R11 : niveau de priorité.** Le dashboard doit regrouper par « niveau de priorité » mais aucune définition
   n'existe. **Implémenté par défaut** : `haute` si l'alerte est forte (R12), sinon `normale` (champ `priority` de l'API).
   Alternative : des paliers selon la perte estimée. À confirmer.
4. **R11 : « perte détectée ».** Implémentation actuelle = anomalies `open` + `confirmed` (tout ce que le système a
   signalé et que personne n'a rejeté ; `false_alarm` et `auto_resolved` exclus). Alternative : `open` seulement. À confirmer.
