# Conformité CNDP / vie privée — points à valider

> Ce document est une liste de contrôle technique, **pas un avis juridique**. Chaque point doit être validé avec
> le responsable du site et un conseil juridique avant tout pilote (loi marocaine sur la protection des données
> personnelles et exigences de la CNDP).

## Ce que le système fait / ne fait pas
- Compte des articles remis par catégorie dans une zone fixe ; **pas** de reconnaissance faciale ni de biométrie.
- Ne conclut jamais qu'une personne a commis une faute : un écart est un signal à vérifier par un humain.
- Ne stocke **que des photos** (jamais de vidéo) ; le flux vidéo reste sur le réseau du café.

## À décider et documenter avec le café
- [ ] Finalité et base légale ; déclaration ou autorisation éventuelle auprès de la CNDP
- [ ] Information des employés et des clients (affichage, notice) ; point de contact
- [ ] Durée de conservation des photos (`SNAPSHOT_RETENTION_DAYS`, `snapshot_retention_days` par site) —
      **la purge automatique n'est pas encore implémentée** : à faire avant le pilote
- [ ] Cadrage limité à la zone de remise ; éviter les clients ; recadrage/floutage si nécessaire
- [ ] Hébergement : en mode hybride, où sont stockés les événements et les photos ? un transfert hors du Maroc est-il permis ?
- [ ] Qui a accès : rôles `admin`/`manager`, comptes nominatifs, mots de passe forts

## Ce que le code fournit déjà
- Accès aux photos réservé aux utilisateurs authentifiés de l'organisation, **journalisé** (`audit_log` : actions `image.view`, `image.list`)
- Revues d'alertes journalisées (qui, quand, ancien et nouveau statut)
- Snapshots servis sans cache (`no-store`) ; références de fichiers protégées contre le parcours de répertoires
- Clé edge par site, rotation possible ; sauvegardes et purge : voir `deployment_modes.md`

## Vocabulaire obligatoire dans l'interface
« perte estimée », « écart à vérifier » — jamais « vol », « fraude » ou « perte exacte ».
