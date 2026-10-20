# Bot de trading crypto 24h/24

Bot Python qui analyse le marché en continu, achète et vend automatiquement, et protège chaque position avec un stop loss.

> ⚠️ **Aucun bot ne garantit des gains.** Le code est testé, mais une stratégie peut perdre de l'argent, et le marché crypto est très volatil.
> Le bot démarre **en simulation** (argent fictif). Ne passe en réel qu'après plusieurs semaines de résultats en simulation, et avec une somme que tu peux perdre en entier.

## Ce que fait le bot

Toutes les `poll_seconds` secondes, pour chaque paire (BTC/EUR, ETH/EUR, SOL/EUR par défaut) :

1. Il télécharge les dernières bougies (en ignorant la bougie pas encore terminée).
2. Il calcule les indicateurs : EMA 12 et 26, EMA 200 (tendance), RSI et ATR (volatilité).
3. Il **achète** si toutes ces conditions sont réunies :
   - l'EMA rapide croise l'EMA lente vers le haut ;
   - le prix est au-dessus de l'EMA 200 (tendance haussière) ;
   - le RSI est sous 70 (marché pas suracheté) ;
   - tous les garde-fous de risque sont respectés (voir plus bas).
4. Il **vend** au premier de ces événements :
   - stop loss touché (prix d'entrée − 2 × ATR) ;
   - take profit touché (prix d'entrée + 4 × ATR) ;
   - croisement baissier des EMA.
5. Il enregistre tout dans `data/state.json`. Après un redémarrage, il reprend ses positions là où il les avait laissées.

### Garde-fous

| Protection | Réglage |
|---|---|
| Montant fixe par trade | `risk.quote_per_trade` |
| Nombre max de positions ouvertes | `risk.max_open_positions` |
| Pause des achats après X € de pertes dans la journée | `risk.max_daily_loss` |
| Nombre max d'achats par jour | `risk.max_trades_per_day` |
| Arrêt d'urgence des achats | créer le fichier `data/STOP` (le supprimer pour reprendre) |
| Le mode réel exige une confirmation explicite | `LIVE_TRADING_CONFIRMED=oui` dans `.env` |
| Erreurs réseau | 3 nouvelles tentatives automatiques (2 s, 4 s, 8 s), puis réessai au tour suivant |
| Crash ou redémarrage du serveur | Docker relance le bot automatiquement |

## Installation

### 1. Récupérer le code et configurer

```bash
git clone https://github.com/detailingdbh/Crypto-.git
cd Crypto-
cp config.example.yaml config.yaml
cp .env.example .env
```

Ouvre `config.yaml` et choisis ton exchange (`revolutx`, `binance`, `kraken`…), tes paires et tes montants.

### 2. Tester la stratégie sur le passé (backtest)

```bash
pip install -r requirements.txt
python backtest.py --days 180
# ou avec Docker, sans rien installer :
docker compose run --rm bot python backtest.py --days 180
```

Le backtest affiche le gain ou la perte, le nombre de trades, le taux de trades gagnants et la pire baisse. Il compare aussi avec « acheter et garder ». Si la stratégie fait moins bien que « acheter et garder », change les réglages ou n'active pas le mode réel.

### 3. Lancer en simulation, 24h/24

Tu as besoin d'une machine allumée en permanence. Un petit serveur VPS à 4-6 €/mois (Hetzner, OVH, Scaleway…) suffit. Installe Docker dessus, puis :

```bash
mkdir -p data && chown 1000:1000 data   # le bot (utilisateur 1000 dans Docker) doit pouvoir écrire ici
docker compose up -d --build     # démarre le bot en arrière-plan
docker compose logs -f           # voir ce qu'il fait en direct
docker compose down              # l'arrêter
```

Sans Docker : `python run.py`. Pour une seule analyse de test : `python run.py --once`.

### 4. Notifications sur ton téléphone (recommandé)

1. Sur Telegram, parle à **@BotFather**, tape `/newbot` et récupère le **token**.
2. Envoie un message à ton nouveau bot, puis ouvre `https://api.telegram.org/bot<TOKEN>/getUpdates` pour lire ton **chat id**.
3. Remplis `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans `.env`.

Tu recevras chaque achat, chaque vente avec son résultat, et les erreurs.

### 5. Passer en réel (seulement après la simulation)

1. Sur ton exchange, crée une clé API **avec le droit de trader mais SANS droit de retrait**.
2. Mets-la dans `.env` :
   - Binance, Kraken… : `EXCHANGE_API_KEY` et `EXCHANGE_SECRET` ;
   - Revolut X : `EXCHANGE_API_KEY` et `EXCHANGE_PRIVATE_KEY` (clé Ed25519).
3. Dans `config.yaml`, mets `mode: live`.
4. Dans `.env`, mets `LIVE_TRADING_CONFIRMED=oui`.
5. Relance : `docker compose up -d --build`.

Commence avec un petit `quote_per_trade`. Si tu changes de mode, supprime `data/state.json` pour repartir proprement.

## Limites à connaître

- Le stop loss est géré **par le bot**, pas par l'exchange. Si le bot est arrêté, les positions ouvertes ne sont plus protégées.
- En réel, si l'exchange ne répond pas pendant l'envoi d'un ordre, le bot ne le renvoie pas, pour ne jamais acheter deux fois. Il te prévient, et tu vérifies ton compte.
- Les memecoins ne sont pas visés par défaut. On peut ajouter leurs paires si l'exchange les liste, mais leur volatilité extrême rend le stop loss beaucoup moins fiable.
- Les connexions aux exchanges en réel n'ont pas pu être testées ici. Teste toujours d'abord en simulation.
- En France, les plus-values sont imposables (flat tax de 30 %) et les comptes ouverts sur un exchange étranger se déclarent (formulaire 3916-bis). Les trades sont dans `data/state.json` (champ `history`).

## Développement

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Structure :

```
bot/indicators.py  EMA, RSI, ATR
bot/strategy.py    règles d'achat et de vente
bot/broker.py      ordres réels (ccxt) et simulation
bot/runner.py      boucle 24/7, garde-fous, gestion des erreurs
bot/state.py       sauvegarde des positions et de l'historique
backtest.py        test sur l'historique
run.py             point d'entrée
```
