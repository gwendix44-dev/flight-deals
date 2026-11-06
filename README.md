# Flight Deals

Scanner personnel d'erreurs de prix et de bonnes affaires (éco + business). 100 % GitHub, gratuit.

Toutes les 30 min, GitHub Actions collecte les prix (API Travelpayouts + flux RSS de bons plans), applique tes
filtres (plafonds, gros-porteur > 5 h, 6 mois, coût total du séjour backpacker) et ouvre une **Issue** par affaire.
GitHub t'envoie l'email et la notification sur l'appli mobile GitHub.

Réglages : `config.json` · budgets par pays : `data/budgets.json`

## Installation (5 min)
1. Dépôt GitHub (privé OK) avec ce code.
2. Settings > Secrets and variables > Actions : ajouter `TRAVELPAYOUTS_TOKEN` (token gratuit sur travelpayouts.com).
3. Installer l'appli **GitHub** sur le téléphone, onglet Notifications activé ; suivre le dépôt avec « Watch > All activity ».
4. Onglet Actions > scan-flights > Run workflow pour un premier test.

## Local
```bash
python -m flightdeals.main --demo
python -m unittest discover -s tests
```
