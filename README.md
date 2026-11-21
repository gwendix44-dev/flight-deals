# Flight Deals

Appli perso (PWA) qui scanne ~10 000 prix de vols depuis tes aéroports, note chaque offre sur 11
(séjour complet et bagages compris), et ne publie que les vraies pépites (≥ 8/10) à 12h et 19h.
Gratuit : GitHub (code, robot, site) + Travelpayouts (prix). Aucun serveur, aucun autre compte.

- Site : https://gwendix44-dev.github.io/flight-deals/
- Tests : `python3 -m unittest discover -s tests`
- Réglages : `config.json` · préférences apprises : `docs/preferences.json` (commande `/prefs`, `/reset`)

## Mise en route (une fois)
1. Réglages du dépôt → Actions → General → Workflow permissions : **Read and write**.
2. Réglages → Pages : branche `main`, dossier `/docs`.
3. Secrets (Settings → Secrets and variables → Actions) : `TRAVELPAYOUTS_TOKEN`, `VAPID_PRIVATE_KEY`, `PUSH_SUBSCRIPTION`.
4. Actions → **scan-flights** → Run workflow. Le bandeau de l'appli passe au vert.

## Fichiers
`flightdeals/` moteur · `data/` états et barèmes · `docs/` appli · `.github/workflows/` robots · `tests/`.
Le dépôt est PUBLIC : aucun secret dans un fichier suivi par git.
