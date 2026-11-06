# Flight Deals

Scanner personnel d'erreurs de prix et de bonnes affaires (éco + business). 100 % GitHub, gratuit.

Toutes les 15 min, GitHub Actions collecte les prix (API Travelpayouts + flux RSS de bons plans), applique tes
filtres (plafonds, gros-porteur > 5 h, 6 mois, coût total du séjour backpacker), puis :
- ouvre une **Issue** par affaire -> notification push sur l'appli GitHub + email,
- met à jour le **dashboard** (`docs/`, GitHub Pages), installable sur le téléphone.

Réglages : `config.json` · budgets par pays : `data/budgets.json`

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
