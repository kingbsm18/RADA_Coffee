# Intégration POS

Tant que le POS n'est pas choisi : **import CSV** (`POST /sites/{id}/pos/import`). Réimporter le même fichier ne change rien.

## Format CSV
UTF-8 (BOM accepté), séparateur `,` ou `;` détecté, une ligne = **une ligne de vente**.

| Colonne | Obligatoire | Règles |
|---|---|---|
| `external_id` | oui | **unique par ligne de vente** (si le POS exporte des tickets multi-articles, combiner ticket + n° de ligne) |
| `timestamp` | oui | ISO 8601 avec fuseau, ou `jj/mm/aaaa hh:mm[:ss]`, ou `aaaa-mm-jj hh:mm[:ss]`. Sans fuseau = heure locale du site |
| `product_name` | oui | |
| `pos_category` | non | utilisée pour le mapping |
| `quantity` | oui | entier 1 à 100 |
| `unit_price` | oui | 2 décimales max, `,` ou `.` ; `0` = article offert (crée quand même un crédit) |
| `status` | non (défaut `paid`) | `paid`, `voided`, `refunded` (alias : annulé, remboursé, void, cancelled, refund…) |

- Les dates avec `/` sont lues **jour d'abord** (`11/05/2026` = 11 mai). Le rapport d'import renvoie la plus
  ancienne et la plus récente vente lues : **vérifiez-les** après chaque premier import.
- Une ligne invalide est rejetée et listée, sans bloquer le reste. Valeurs ambiguës (`1.234,50`) = rejet.
- Un statut qui change plus tard (`paid` → `voided`) met la vente à jour et apparaît dans `status_changes` (règle R8).

## Mapping produit → catégorie
```bash
curl -X PUT $API/api/v1/sites/cafe-01/category-mappings -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"match_field":"pos_category","match_value":"Boissons chaudes","category":"coffee"},
                {"match_field":"product_name","match_value":"Coca-Cola","category":"soft_drink"}]}'
```
Le nom du produit l'emporte sur la catégorie POS. Les ventes sans mapping (`unmapped` dans le rapport) ne créent
aucun crédit tant qu'elles ne sont pas mappées ; le mapping est réappliqué aux ventes existantes.

## Test d'horloge (à faire le jour 1)
Faire une vente test à une heure connue, l'importer, et comparer avec l'heure lue : un décalage d'une heure
signale une horloge ou une base de fuseaux obsolète (Maroc UTC+0 depuis le 2026-09-20).

## Quand le POS sera connu
Questions au fournisseur : API ? webhooks ? exemple de réponse d'une vente (données masquées) ; l'`id` est-il
unique par ligne ? les annulations/remboursements sont-ils renvoyés ? fuseau et format des heures ? paiement
avant ou après la remise de l'article (règle les fenêtres `lookback`/`grace`) ?
Implémenter ensuite `backend/app/pos/adapters/your_pos.py` (renommer) : mapper vers `PosSaleIn`, enregistrer dans
`pos/registry.py`, ajouter l'exemple réel comme fixture de test. Ne rien deviner : un champ faux = de faux crédits.
