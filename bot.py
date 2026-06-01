# 🚗 Bot Import Auto DE → CH

Bot Telegram qui scrape mobile.de et compare les prix avec AutoScout24.ch
pour détecter les meilleures opportunités d'import Allemagne → Suisse.

---

## ⚙️ Variables d'environnement (à configurer sur Railway)

| Variable | Description | Exemple |
|---|---|---|
| `TELEGRAM_TOKEN` | Token de ton bot Telegram | `123456:ABCdef...` |
| `TELEGRAM_CHAT_ID` | Ton Chat ID Telegram | `987654321` |
| `MARGE_MIN_CHF` | Marge nette min pour alerte | `2000` |
| `SCAN_INTERVAL` | Intervalle scan en secondes | `3600` (1h) |

---

## 📱 Étape 1 — Créer ton bot Telegram

1. Ouvre Telegram, cherche **@BotFather**
2. Envoie `/newbot`
3. Choisis un nom (ex: `ImportAutoBot`)
4. Choisis un username (ex: `mon_import_auto_bot`)
5. BotFather te donne un **token** → note-le

**Récupérer ton Chat ID :**
1. Cherche **@userinfobot** sur Telegram
2. Envoie `/start`
3. Il te donne ton Chat ID → note-le

---

## 🚀 Étape 2 — Déployer sur Railway

1. Crée un compte sur [railway.app](https://railway.app) (gratuit)
2. Clique **New Project** → **Deploy from GitHub repo**
3. Upload ce dossier sur GitHub (ou glisse les fichiers)
4. Dans Railway → **Variables** → ajoute les 4 variables ci-dessus
5. Railway démarre automatiquement le bot

---

## 💰 Calcul de la marge

```
Valeur CHF = Prix € × taux EUR/CHF (temps réel)
Frais import = TVA 7.7% + homologation 300 CHF + transport 450 CHF + divers 200 CHF
Coût total = Valeur CHF + Frais import
Marge nette = Prix marché AutoScout24.ch - Coût total
```

---

## 🔧 Critères de recherche

- **Marques** : VW, Audi, Mercedes, BMW, Porsche, Opel, Toyota
- **Budget max** : 20'000 €
- **Année** : 2018 et plus récent
- **Kilométrage** : max 100'000 km
- **Carburant** : Essence uniquement
- **Boîte** : Automatique uniquement

---

## ⚠️ Notes importantes

- Le scraping de mobile.de peut être instable selon leur protection anti-bot
- Les frais d'import sont des estimations — vérifier avec un transitaire pour les vrais montants
- Le prix marché AutoScout24 est une médiane des annonces similaires, pas une cote officielle
- Toujours inspecter physiquement le véhicule avant achat
