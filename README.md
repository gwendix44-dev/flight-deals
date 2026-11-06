# Flight Deals

Scanner personnel d'erreurs de prix et de bonnes affaires (éco + business). 100 % GitHub, gratuit.

Toutes les 15 min, GitHub Actions collecte les prix (API Travelpayouts + flux RSS de bons plans), applique tes
filtres (plafonds, gros-porteur > 5 h, 6 mois, coût total du séjour backpacker), puis :
- ouvre une **Issue** par affaire -> notification push sur l'appli GitHub + email,
- met à jour le **dashboard** (`docs/`, GitHub Pages), installable sur le téléphone.

Réglages : `config.json` · budgets par pays : `data/budgets.json`

## Grille de notation (sur 11)
Un deal n'est alerté que s'il atteint **9,5/11** (`scoring.min_score` dans `config.json`).
Prix vs prix habituel (3) · budget total du séjour (2) · destination hors sentiers battus (1,5) ·
qualité du vol (1,5) · durée adaptée à la distance (1) · coût par jour (1) · bonus erreur de prix (+1).
Budget total (vols + sur place) : 1 500 € max. Séjour : 3 semaines max, minimum 5 j (≤3 500 km), 7 j (≤7 000 km),
10 j (≤10 000 km), 14 j au-delà. Les journaux du scan listent les 5 meilleures offres refusées pour régler le seuil.

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
