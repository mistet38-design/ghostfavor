from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from config import CATEGORIES, DEPOT_MIN_PAR_NIVEAU, Limites
from database.models import Annonce, Echange, StatutAnnonce, StatutEchange, TypeAnnonce, User
from database.session import async_session
from keyboards.menus import clavier_accepter_refuser, clavier_categories, clavier_confirmation, menu_principal
from services.matching import trouver_correspondance
from states import PublicationAnnonce

router = Router()
LIMITES = Limites()


async def _get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


@router.message(F.text.in_({"📤 Publier une offre", "📥 Publier une demande"}))
async def demarrer_publication(message: Message, state: FSMContext):
    type_annonce = TypeAnnonce.offre if "offre" in message.text else TypeAnnonce.demande
    await state.update_data(type_annonce=type_annonce.value)
    await message.answer(
        "Dans quelle catégorie ? (liste fermée — pour la sécurité de tous, aucune autre catégorie n'est possible)",
        reply_markup=clavier_categories(),
    )
    await state.set_state(PublicationAnnonce.choix_categorie)


@router.callback_query(PublicationAnnonce.choix_categorie, F.data.startswith("cat:"))
async def choisir_categorie(callback: CallbackQuery, state: FSMContext):
    cle_categorie = callback.data.split(":", 1)[1]
    await state.update_data(categorie=cle_categorie)

    data = await state.get_data()
    nature = "offre" if data["type_annonce"] == "offre" else "demande"
    await callback.message.edit_text(
        f"Catégorie : {CATEGORIES[cle_categorie]}\n\n"
        f"Décris ta {nature} en {LIMITES.description_max_chars} caractères max "
        "(reste factuel, sans donner ton adresse exacte ni de détail identifiant)."
    )
    await state.set_state(PublicationAnnonce.saisie_description)


@router.message(PublicationAnnonce.saisie_description, F.text)
async def saisir_description(message: Message, state: FSMContext):
    texte = message.text.strip()
    if len(texte) > LIMITES.description_max_chars:
        await message.answer(f"Trop long ({len(texte)} caractères). Max {LIMITES.description_max_chars}.")
        return

    await state.update_data(description=texte)
    await message.answer(
        "Quel créneau ? Format : `JJ/MM HH:MM-HH:MM`\nEx : `15/08 14:00-17:00`",
        parse_mode="Markdown",
    )
    await state.set_state(PublicationAnnonce.saisie_creneau)


@router.message(PublicationAnnonce.saisie_creneau, F.text)
async def saisir_creneau(message: Message, state: FSMContext):
    try:
        date_part, plage = message.text.strip().split(" ")
        heure_debut, heure_fin = plage.split("-")
        annee = datetime.now().year
        debut = datetime.strptime(f"{date_part}/{annee} {heure_debut}", "%d/%m/%Y %H:%M")
        fin = datetime.strptime(f"{date_part}/{annee} {heure_fin}", "%d/%m/%Y %H:%M")
        if fin <= debut:
            raise ValueError
    except ValueError:
        await message.answer(
            "Format non reconnu. Réessaie, ex : `15/08 14:00-17:00`", parse_mode="Markdown"
        )
        return

    await state.update_data(creneau_debut=debut.isoformat(), creneau_fin=fin.isoformat())

    data = await state.get_data()
    user = await _get_user(message.from_user.id)
    depot_min = DEPOT_MIN_PAR_NIVEAU[user.niveau.value]

    await state.update_data(depot_stars=depot_min)

    recap = (
        f"*Récapitulatif*\n\n"
        f"Type : {'Offre' if data['type_annonce'] == 'offre' else 'Demande'}\n"
        f"Catégorie : {CATEGORIES[data['categorie']]}\n"
        f"Description : {data['description']}\n"
        f"Créneau : {debut.strftime('%d/%m %H:%M')} → {fin.strftime('%H:%M')}\n"
        f"Ville : {user.ville}\n"
        f"Garantie requise si match : *{depot_min} Stars* (bloquée seulement à l'acceptation du match)\n\n"
        "Confirmer la publication ?"
    )
    await message.answer(
        recap, parse_mode="Markdown", reply_markup=clavier_confirmation("publish", 0)
    )
    await state.set_state(PublicationAnnonce.confirmation_depot)


@router.callback_query(PublicationAnnonce.confirmation_depot, F.data.startswith("publish:"))
async def confirmer_publication(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    if action == "cancel":
        await callback.message.edit_text("❌ Publication annulée.")
        await state.clear()
        return

    data = await state.get_data()

    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one()

        annonce = Annonce(
            user_id=user.id,
            type=TypeAnnonce(data["type_annonce"]),
            categorie=data["categorie"],
            description=data["description"],
            ville=user.ville,
            creneau_debut=datetime.fromisoformat(data["creneau_debut"]),
            creneau_fin=datetime.fromisoformat(data["creneau_fin"]),
            depot_stars=data["depot_stars"],
        )
        session.add(annonce)
        await session.flush()

        correspondance = await trouver_correspondance(session, annonce)

        if correspondance:
            annonce.statut = StatutAnnonce.matchee
            correspondance.statut = StatutAnnonce.matchee

            if annonce.type == TypeAnnonce.offre:
                offre, demande = annonce, correspondance
            else:
                offre, demande = correspondance, annonce

            echange = Echange(
                annonce_offre_id=offre.id,
                annonce_demande_id=demande.id,
                partie_a_id=offre.user_id,
                partie_b_id=demande.user_id,
                montant_escrow=max(offre.depot_stars, demande.depot_stars),
            )
            session.add(echange)
            await session.commit()
            await session.refresh(echange)

            result_a = await session.execute(select(User).where(User.id == offre.user_id))
            result_b = await session.execute(select(User).where(User.id == demande.user_id))
            user_a = result_a.scalar_one()
            user_b = result_b.scalar_one()

            bot = callback.bot
            for uid, autre in [(user_a.telegram_id, "quelqu'un de ta ville"), (user_b.telegram_id, "quelqu'un de ta ville")]:
                await bot.send_message(
                    uid,
                    f"🔔 *Match trouvé !* Catégorie : {CATEGORIES[annonce.categorie]}\n\n"
                    f"Un·e voisin·e correspond à ton annonce. Tu as {120} minutes pour accepter.",
                    parse_mode="Markdown",
                    reply_markup=clavier_accepter_refuser(echange.id),
                )

            await callback.message.edit_text("✅ Publié — et un match a été trouvé immédiatement ! Vérifie tes messages.")
        else:
            await session.commit()
            await callback.message.edit_text(
                "✅ Publié. Tu seras notifié·e dès qu'une correspondance est trouvée."
            )

    await callback.message.answer("Que veux-tu faire ensuite ?", reply_markup=menu_principal())
    await state.clear()
