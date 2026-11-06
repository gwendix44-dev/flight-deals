# Flight Deals

Scanner personnel d'erreurs de prix et de bonnes affaires (éco + business), 100 % gratuit, sans serveur.

## Fonctionnement
GitHub Actions lance `python -m flightdeals.main` toutes les 30 min :
1. collecte (API Travelpayouts + flux RSS de bons plans),
2. filtres (distance, plafonds, règle gros-porteur > 5 h, fenêtre de 6 mois),
3. coût total du séjour en backpacker (`data/budgets.json`),
4. détection d'anomalie vs médiane historique (`data/history.json`),
5. alerte email + push ntfy, et mise à jour de `docs/deals.json` (dashboard PWA dans `docs/`).

Réglages : `config.json`. Budgets par pays : `data/budgets.json`.

## Commandes
```bash
python -m flightdeals.main --demo      # offres fictives, rien n'est envoyé
python -m flightdeals.main --dry-run   # vraies sources, aucun envoi ni écriture
python -m unittest discover -s tests
```

## Secrets GitHub à créer (Settings > Secrets > Actions)
- `TRAVELPAYOUTS_TOKEN` : token gratuit sur travelpayouts.com
- `GMAIL_USER` + `GMAIL_APP_PASSWORD` : mot de passe d'application Google (validation en 2 étapes requise)
- `NTFY_TOPIC` : nom long et aléatoire, à suivre dans l'app ntfy (iOS/Android)
