# Flight Deals

Scanner personnel d'erreurs de prix et de bonnes affaires (éco + business). 100 % GitHub, gratuit.

Toutes les 15 min, GitHub Actions collecte les prix (API Travelpayouts + flux RSS de bons plans), applique tes
filtres (plafonds, gros-porteur > 5 h, 6 mois, coût total du séjour backpacker), puis :
- ouvre une **Issue** par affaire -> notification push sur l'appli GitHub + email,
- met à jour le **dashboard** (`docs/`, GitHub Pages), installable sur le téléphone.

Réglages : `config.json` · budgets par pays : `data/budgets.json`

## Fonctionnement : analyse continue, publication à 12h et 19h
- **Toute la journée** (scan toutes les 15 min) : l'appli analyse les prix, note chaque offre sur 11 et ne garde que les deals
  **≥ 8/10**, après revérification du prix pour les dates exactes. Ils attendent dans une réserve (`data/pool.json`).
- **À 12h et à 19h (heure de Paris)** : les **3 meilleurs deals standard** et les **3 meilleures offres business** de la réserve sont
  revérifiés une dernière fois, puis publiés sur le dashboard et notifiés (une seule notification groupée par créneau, et une Issue
  par offre pour pouvoir refuser). Les offres sont choisies à tour de rôle dans chaque région du monde. Si moins de 3 offres
  atteignent 8/10, on en publie moins : on ne remplit jamais.
- **10/10** : publication et notification immédiates, sans attendre le créneau (plafond de 4 par jour pour éviter une inondation
  si une donnée est fausse ; le surplus attend le créneau).
- **Un créneau manqué est rattrapé** : un scan retardé par GitHub publie jusqu'à 3 h après l'heure prévue, une seule fois.
- **État visible sur le téléphone** : le bandeau en haut du dashboard (`docs/status.json`) dit si l'appli tourne, combien d'offres
  ont été analysées, combien attendent leur créneau, et affiche en rouge toute erreur. Un dashboard vide ne veut donc pas dire
  « panne » : c'est qu'aucune offre n'a atteint 8/10.
- Réglages : `publication` dans `config.json` (créneaux, seuils, nombre par créneau).

## Grille de notation (sur 11)
Un deal n'est retenu que s'il atteint **8/10** (`publication.min_score`) ; **10/10** déclenche la publication immédiate. La note business est calculée sur la même échelle à partir de la remise (11 × remise / 0,85 : 8/10 ≈ −62 %, 10/10 ≈ −77 %).
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

## Bagages inclus dans le prix
Sur un long voyage, un **sac à dos + un bagage cabine** sont indispensables : le prix du vol affiché les INCLUT. Les moteurs de
recherche affichent le tarif nu ; `flightdeals/baggage.py` ajoute le supplément estimé quand la compagnie les facture (Ryanair,
Wizz, easyJet, Vueling, Transavia…) ou quand elle est inconnue (supplément par prudence). Ce supplément est ajouté **avant** la note et
le budget, donc une offre bon marché chez une compagnie à bagages payants peut passer sous le seuil. Chaque billet d'un montage
d'escales est traité séparément. Barème modifiable : `data/airlines.json` (mes connaissances : à vérifier à la réservation).
Business : bagages inclus par nature.

## Fiabilité des prix : ce que l'appli peut et ne peut pas garantir
Aucune source gratuite et officielle ne donne de prix en temps réel à un particulier (Amadeus Self-Service est fermé, Kiwi Tequila
réservé aux partenaires). Les prix de détection viennent du **cache** d'un agrégateur (Travelpayouts/Aviasales). Pour limiter le risque :
1. revérification pour les dates exactes (offre écartée si le prix a disparu ou monté de plus de 10 %) ;
2. **vérification en direct optionnelle** sur Google Flights via SerpApi (secret `SERPAPI_KEY`, quota gratuit mensuel limité,
   budget `live.monthly_budget`, suivi dans `data/live_usage.json`) : appliquée seulement aux finalistes d'un créneau et aux 10/10, avec des
   remplaçants si l'un est écarté. Elle confirme prix, compagnie, **type d'avion** (donc le double couloir devient vérifié) et niveau de prix ;
3. chaque alerte contient un lien Google Flights prérempli (dates exactes) pour vérifier en 30 secondes, et le **site officiel de la
   compagnie** pour acheter (jamais un intermédiaire) ;
4. sans clé ou quota épuisé, l'offre est publiée avec un avertissement orange « prix non confirmé en direct ».

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

## Notifications sur le téléphone (natives, sans appli externe)
Le raccourci installé sur l'écran d'accueil reçoit lui-même les notifications (Web Push), même appli fermée.
Un tap ouvre le dashboard sur les données fraîches. À activer une seule fois :
1. Secret GitHub `VAPID_PRIVATE_KEY` : la clé privée du serveur de notifications (`python scripts/generate_vapid.py` en génère une ;
   la clé publique correspondante est la constante `VAPID_PUBLIC` de `docs/index.html`).
2. Sur le téléphone, ouvre le raccourci > « 🔔 Notifications » > « Activer » > copie le texte affiché > colle-le dans le
   secret GitHub `PUSH_SUBSCRIPTION`.
3. Actions > push-test > Run workflow : une notification de test doit arriver.
iPhone : iOS 16.4 minimum, et il faut ouvrir l'appli depuis l'icône de l'écran d'accueil (pas depuis Safari).
Le dashboard se rafraîchit au retour sur l'appli, toutes les 2 min, et dès qu'une notification arrive.
(Option : `NTFY_TOPIC` active en plus ntfy.sh, inutile si les notifications natives fonctionnent.)
Nettoyage : le workflow `cleanup-issues` ferme les anciennes Issues d'alerte.

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
