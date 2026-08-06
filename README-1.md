# QuietSwap — Bot Telegram d'échange de coups de main de voisinage

## Ce qui a été ajouté dans cette version (par rapport au premier jet)

- **Expiration automatique des matchs non confirmés** — un job tourne toutes les 5 min, annule les matchs restés `en_attente` plus de 120 min, rembourse toute garantie déjà bloquée, et remet les annonces actives en circulation.
- **Expiration automatique des annonces périmées** — un job toutes les 10 min marque comme expirées les annonces dont le créneau est passé sans avoir trouvé de match.
- **Relance périodique du matching** — filet de sécurité toutes les 10 min qui retente un appariement sur les annonces encore ouvertes (utile si deux annonces compatibles ont été publiées à quelques secondes d'écart).
- **Anti-spam** — middleware de limitation de fréquence (0.7s entre deux actions par utilisateur).
- **Blocage effectif des comptes bannis** — un utilisateur banni par un admin ne peut plus interagir avec le bot, à aucun niveau.
- **Garde anti double-clic** — empêche de bloquer deux fois la même garantie si un utilisateur clique deux fois sur "Accepter".
- **Index de base de données** sur les colonnes utilisées par le matching et le scheduler (ville, catégorie, statut, créneau) pour rester performant même avec du volume.
- Nettoyage de bugs mineurs (texte de description cassé selon offre/demande, gestion du niveau "or").

## Ce qui a été modifié par rapport à la demande initiale

Trois points ont été changés volontairement, pour la sécurité des utilisateurs :

1. **Pas d'anonymat total** — chaque compte est vérifié par numéro de téléphone (jamais partagé avec l'autre partie, sert uniquement à limiter les faux comptes). C'est ce qui distingue une plateforme d'entraide légitime d'un outil impossible à modérer.
2. **Catégories strictement fermées** — pas de champ "autre" libre. Seules 6 catégories de services concrets et sans risque sont proposées (colis, courses, plantes/animaux, petit bricolage, transport local, aide administrative).
3. **Modération humaine systématique** — tout signalement passe par un admin humain (`/litige`), rien n'est tranché automatiquement.

## Architecture

```
quietswap/
  bot.py                  → point d'entrée
  config.py                → catégories, seuils, constantes
  states.py                → états FSM (parcours utilisateur)
  database/
    models.py              → modèles SQLAlchemy (User, Annonce, Echange, Transaction, ScoreLog, Signalement)
    session.py              → connexion PostgreSQL async
  keyboards/
    menus.py                → claviers reply + inline
  handlers/
    start.py                → onboarding (téléphone, ville, règles)
    listings.py              → publication offre/demande + matching
    exchange.py              → acceptation, preuve, confirmation, libération
    wallet.py                → dépôt Stars, solde, retrait
    report.py                → signalement / litige
    profile.py                → score et historique personnel
    admin.py                  → panel admin
  services/
    matching.py               → logique de correspondance ville + catégorie + créneau
    escrow.py                  → blocage/libération des garanties Stars
    score.py                    → calcul du score et du niveau
```

## Flow complet

1. `/start` → partage du téléphone → ville → acceptation des règles
2. Publier une offre ou une demande → catégorie (liste fermée) → description → créneau → récapitulatif
3. Si une correspondance existe déjà (même ville, même catégorie, créneau compatible) → match immédiat, les deux parties reçoivent une notification avec Accepter/Refuser
4. Acceptation → garantie Stars bloquée pour chacun → statut "en cours"
5. Une fois le service rendu, la partie qui l'a rendu envoie une photo ou un vocal (15s max) comme preuve
6. L'autre partie confirme → garantie libérée (moins 8% de commission) → score +10 pour les deux
7. En cas de problème → signalement → statut "litige" → un admin tranche via `/litige <id> <a|b>`

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env   # puis remplir BOT_TOKEN, DATABASE_URL, ADMIN_IDS
export $(cat .env | xargs)
python bot.py
```

Il faut une base PostgreSQL accessible (locale ou hébergée, ex: Railway/Supabase/Neon).

## Déploiement 24/7 (Railway)

1. Crée un projet PostgreSQL sur Railway (bouton "+ New" → Database → PostgreSQL) — il te donne automatiquement une `DATABASE_URL`
2. Ajoute ce code comme second service dans le même projet, déployé depuis GitHub
3. Dans les Variables du service bot : `BOT_TOKEN`, `DATABASE_URL` (copiée depuis le service PostgreSQL), `ADMIN_IDS`
4. Railway build et lance automatiquement `python bot.py`

## Retraits — point important non automatisé

Le retrait réel de Stars vers de la valeur monétaire passe par **Fragment** (plateforme officielle Telegram), qui n'a pas d'API publique stable pour l'automatisation complète à ce jour. Dans ce projet, `/retrait <montant>` enregistre juste la demande et notifie les admins, qui traitent manuellement via Fragment. À automatiser plus tard si le volume le justifie.

## Limites connues restantes / à améliorer avant une mise en production à grande échelle

- **MemoryStorage pour le FSM et le throttling** — fonctionnent pour une seule instance de bot. Pour scaler horizontalement (plusieurs workers), passer le FSM à `RedisStorage` et le compteur anti-spam à Redis (INCR + EXPIRE).
- **Vérification anti multi-comptes** — actuellement seulement le numéro de téléphone (unique par compte Telegram). Pas de détection d'IP/device/empreinte — à envisager si le multi-compte devient un problème observé.
- **Preuve non vérifiée automatiquement** — le bot accepte n'importe quelle photo/vocal ; il n'y a pas de détection de contenu invalide, seule la confirmation humaine de l'autre partie fait foi. Une vérification automatique de contenu (ex: détection d'image non pertinente) serait un ajout futur possible.
- **Retrait Stars → valeur réelle non automatisé** — voir section dédiée ci-dessus.
- **Le scheduler tourne dans le même process que le bot** — pour une charge importante, séparer scheduler et bot en deux services distincts partageant la même base.

## Sécurité et modération — à ne pas retirer

- Les catégories doivent rester une liste fermée, gérée uniquement via `config.py` — ne pas ajouter de champ de texte libre pour la nature du service.
- Toute décision de litige doit rester humaine (`/litige`) — ne pas automatiser la résolution des signalements.
- Le numéro de téléphone ne doit jamais être exposé dans un message envoyé à l'autre partie de l'échange.
