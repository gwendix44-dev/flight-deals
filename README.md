# Flight Deals

Scanner personnel d'erreurs de prix et de bonnes affaires (éco + business). 100 % GitHub, gratuit.

Toutes les 15 min, GitHub Actions collecte les prix (API Travelpayouts + flux RSS de bons plans), applique tes
filtres (plafonds, gros-porteur > 5 h, 6 mois, coût total du séjour backpacker), puis :
- ouvre une **Issue** par affaire -> notification push sur l'appli GitHub + email,
- met à jour le **dashboard** (`docs/`, GitHub Pages), installable sur le téléphone.

Réglages : `config.json` · budgets par pays : `data/budgets.json`

## Philosophie : la pépite, pas le voyage correct
L'appli ne sert pas à partir tous les mois : elle cherche l'occasion exceptionnelle qui ne se présente que **3 à 5 fois par an**.
Un bon plan qui te ferait partir juste avant une vraie occasion est exactement ce qu'il faut éviter. Une alerte n'est donc
envoyée que si l'offre est une **anomalie de prix** (`scoring.require_anomaly`) : erreur signalée par une source, prix au moins
moitié moins cher que d'habitude sur la ligne, ou au moins 75 % sous le prix habituel pour la distance. Il faut en plus
atteindre la note minimale (faisabilité et attrait du séjour complet) et passer la revérification. Chaque alerte indique son
rang dans les 12 derniers mois (`data/alerts_log.json`, compteur aussi visible sur le dashboard) et sa rareté sur la ligne.
Mesuré sur l'historique réel du dépôt : 0 ligne ne remplissait ces conditions un jour normal.

## Grille de notation (sur 11)
Un deal n'est alerté que s'il atteint **7,5/11** (`scoring.min_score` dans `config.json`). Mesuré sur l'historique réel : la meilleure note observée est ~7,9 ; à 9,5 aucune alerte ne partirait.
Prix vs prix habituel (3) · budget total du séjour (2) · destination hors sentiers battus (1,5) ·
qualité du vol (1,5) · durée adaptée à la distance (1) · coût par jour (1) · bonus erreur de prix (+1).
Budget total (vols + sur place) : 1 500 € max jusqu'à 8 000 km, 1 900 € de 8 000 à 12 000 km, 2 500 € au-delà (réglable : `economy.total_trip_cap_eur`). Séjour : 3 semaines max, minimum 5 j (≤3 500 km), 7 j (≤7 000 km),
10 j (≤10 000 km), 14 j au-delà. Les journaux du scan listent les 5 meilleures offres refusées pour régler le seuil.

## Départs réels et section business
- **Tu habites à Nantes et Paris** : NTE, CDG et ORY sont tes départs directs. Les autres aéroports (LHR, MAD, FCO, LIS, DUB,
  AMS, FRA) restent possibles, mais le billet A/R pour les rejoindre depuis Paris ou Nantes est ajouté au **coût du séjour**
  (`home.positioning_eur` dans `config.json`, estimations modifiables), jamais au prix du vol, qui reste comparé au vrai tarif.
- **Section business class** (onglet séparé du dashboard, étiquette `business` sur les Issues) : A/R en business ≤ 800 €
  (`business.flight_cap_eur`), long-courrier (≥ 3 600 km), avec au moins 50 % de remise sur le prix habituel du business. Le prix du
  séjour n'est PAS pris en compte (affiché à titre indicatif). Ni note sur 11, ni budget total. Ces offres viennent des flux de
  bons plans (l'API gratuite ne distingue pas la cabine) et sont donc marquées « à confirmer sur le lien ».

## Réalisme du séjour et vérification avant affichage
- **Coût du séjour poste par poste** (`data/costs.json`, 86 pays, modifiable) : hébergement (dortoir/chambre simple), nourriture,
  transports locaux, activités, déplacements entre villes, visa/autorisation d'entrée (passeport français, à revérifier),
  assurance, transferts + SIM, marge de 10 %, supplément haute saison (20 déc → 5 janv). Le détail est dans chaque alerte.
- **Aucune offre n'est affichée sans contrôle** : prix revérifié pour les dates exactes (écartée s'il a disparu ou monté de
  plus de 10 %), montages revérifiés billet par billet, départ ≥ 10 jours, prix plausible (≥ 60 €), séjour dans la fourchette
  de distance. Les offres des flux de bons plans sont signalées « à confirmer sur le lien ». Les prix restent ceux du cache
  des moteurs de recherche (quelques heures de retard possible).
- **Toute la planète** : 155 destinations hors Europe et Afrique du Nord ; chaque scan sélectionne à tour de rôle la meilleure
  offre de chaque région (2 maximum par région, 1 par destination).

## Refuser une offre : l'appli apprend
Deux façons de dire pourquoi tu refuses (« trop cher », « séjour trop court », « trop d'escales »,
« destination déjà vue », « trop loin », « vol trop long », « avion pas adapté », « trop touristique »,
« billets séparés trop risqués », « mauvaise période », « pas assez exceptionnel ») :
1. **Dashboard** : bouton « 👎 Refuser » sur la carte, zone de texte + raisons rapides. Pour envoyer depuis la page,
   clique sur « 🔑 Connecter GitHub » et colle un token *fine-grained* limité à ce dépôt, permission **Issues : Read and write**
   (créé sur github.com/settings/personal-access-tokens/new ; il reste dans ton navigateur). Sans token, le texte est copié
   et l'Issue s'ouvre pour que tu le colles en commentaire.
2. **Appli GitHub / site** : commente directement l'Issue de l'offre.
Le workflow `feedback` lit le commentaire aussitôt (uniquement s'il vient du propriétaire du dépôt), met à jour
`docs/preferences.json`, répond sur l'Issue et la ferme. Les préférences s'appliquent au scan suivant (15 min max).
Commandes : `/prefs` liste les réglages appris, `/reset` les efface. Le lecteur de raisons fonctionne par mots-clés
(gratuit, prévisible) : si ta phrase n'est pas comprise, la réponse te le dit.

## Montages d'escales (billets séparés)
`python -m flightdeals.combos` (workflow `scan-combos`, toutes les 3 h) assemble des billets aller simple
origine -> hub -> destination (2 escales max) et les compare au meilleur billet classique (gain minimum 20 %).
Règles d'escale : 4 h à 10 h de jour (jamais de nuit à l'aéroport) ou 2 nuits minimum sur place (hébergement compté).
Le retour est le billet aller simple le moins cher trouvé. Hubs : `HUBS` dans `flightdeals/airports.py`.

## Notifications sur le téléphone et rafraîchissement
- **Push** : l'appli **ntfy** (gratuite, Android/iOS) reçoit chaque pépite. Secret GitHub `NTFY_TOPIC` = nom du topic (long et
  aléatoire : quiconque le connaît peut lire les notifications). Un tap sur la notification ouvre le dashboard (`?fresh=1`, données
  lues directement chez GitHub sans attendre le déploiement de Pages) ; le bouton « Voir l'offre » ouvre le lien de réservation.
- **Dashboard** : se rafraîchit au retour sur l'appli, toutes les 2 min, et instantanément à chaque notification tant qu'il est
  ouvert (bouton « 🔔 Notifications » : coller le même topic).
- **Issues GitHub** : continuent d'exister (point d'entrée du refus par commentaire). Pour ne pas recevoir deux notifications,
  mets le dépôt en « Watch > Custom > cocher seulement Issues si tu veux garder GitHub, sinon « Ignore ».
- **Nettoyage** : workflow `cleanup-issues` (à lancer une fois à la main) ferme les anciennes Issues d'alerte.

## Installation
1. Dépôt GitHub **public** avec ce code.
2. Settings > Secrets and variables > Actions : `TRAVELPAYOUTS_TOKEN` (token gratuit sur travelpayouts.com).
3. Settings > Pages : source = branche `main`, dossier `/docs`.
4. Settings > Actions > General > Workflow permissions : « Read and write ».
5. Téléphone : appli **GitHub** (notifications activées, dépôt en Watch > All activity) ;
   ouvrir l'URL Pages dans Chrome/Safari > « Ajouter à l'écran d'accueil ».
6. Onglet Actions > scan-flights > Run workflow pour un premier test.

## Local
```bash
python -m flightdeals.main --demo
python -m unittest discover -s tests
```
