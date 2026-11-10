# Checklist du pilote

## Avant
- [ ] POS connu et accès (API ou export CSV) confirmé ; exemple de vente réel obtenu
- [ ] Paiement avant ou après remise de l'article : noté (règle `lookback`/`grace`)
- [ ] Caméra, résolution du sous-flux, machine de détection choisis ; NTP actif partout
- [ ] Information du personnel et affichage conformes (`legal_cndp.md`) ; durée de conservation approuvée
- [ ] Sauvegarde PostgreSQL quotidienne + restauration testée

## Jour d'installation
- [ ] Zone de remise tracée ; angle et éclairage vérifiés aux heures calme et chargée
- [ ] Vente test pour vérifier l'horloge (écart d'une heure = base de fuseaux obsolète)
- [ ] Un événement de test visible dans le dashboard ; coupure réseau simulée : l'outbox renvoie sans doublon

## Mode ombre
- [ ] Sessions calmes et chargées annotées à la main (vérité terrain), photos comprises
- [ ] Mesures : précision et rappel des événements (cibles indicatives du dossier de conception : ≥ 90 % / ≥ 85 %, **non acquises**, à réviser)
- [ ] Niveau de bruit par catégorie ; percentile 95 des délais vente/article

## Go / no-go
- [ ] Les écarts « à vérifier » dépassent nettement le bruit mesuré
- [ ] Le gérant sait consulter une alerte et ses photos ; la qualifier (confirmé / fausse alerte) est **facultatif** (R11)
- [ ] Aucun discours « accusation » : l'outil signale, un humain vérifie

## Après
- [ ] Rapport de fin de service (R13) comparé au comptage manuel ; mises à jour des réglages consignées
