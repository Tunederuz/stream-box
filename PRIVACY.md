# Règles de confidentialité de Stream Box

Stream Box est un logiciel libre qui transforme un mini PC branché sur une TV en lecteur Twitch, YouTube et Jellyfin.
Chaque box est installée et utilisée par son propriétaire, chez lui : il n'existe aucun serveur Stream Box.

## Compte YouTube (API YouTube Data)

Quand le propriétaire connecte son compte YouTube, la box obtient un accès en **lecture seule**
(`youtube.readonly`) pour afficher, sur sa TV, les dernières vidéos des chaînes auxquelles il est abonné.

- Données lues : la liste des abonnements du compte (nom, identifiant et photo des chaînes), puis les dernières vidéos
  publiques de ces chaînes (titre, miniature, date, durée, nombre de vues).
- Où elles vont : nulle part ailleurs que sur la box elle-même. Elles sont gardées dans le dossier de configuration de
  l'utilisateur de la box, lisibles par lui seul, et ne sont ni transmises, ni vendues, ni partagées avec qui que ce
  soit.
- Rien n'est modifié sur le compte : la box ne publie, ne commente, ne s'abonne ni ne se désabonne de rien.
- Retirer l'accès : « Déconnecter le compte » dans le menu de la box (Système → Compte YouTube) ou sur sa page de
  télécommande efface les jetons de la box. L'accès peut aussi être retiré à tout moment depuis
  https://myaccount.google.com/permissions.

L'utilisation des données obtenues par les API Google respecte les
[règles relatives aux données utilisateur des services d'API Google](https://developers.google.com/terms/api-services-user-data-policy),
y compris les exigences d'utilisation limitée.

Voir aussi les [conditions d'utilisation de YouTube](https://www.youtube.com/t/terms) et les
[règles de confidentialité de Google](https://policies.google.com/privacy).

## Contact

Questions : ouvrir une issue sur le dépôt du projet.
