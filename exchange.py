from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from config import SCORE_GAIN_ECHANGE_REUSSI, SCORE_PERTE_NO_SHOW
from database.models import Annonce, Echange, StatutAnnonce, StatutEchange, User
from database.session import async_session
from keyboards.menus import clavier_confirmer_reception, menu_principal
from services.escrow import SoldeInsuffisant, bloquer_garantie, liberer_garantie_avec_commission
from services.score import appliquer_delta_score
from states import SoumissionPreuve

router = Router()


@router.callback_query(F.data.startswith("match:"))
async def repondre_match(callback: CallbackQuery):
    _, action, echange_id = callback.data.split(":")
    echange_id = int(echange_id)

    async with async_session() as session:
        result = await session.execute(select(Echange).where(Echange.id == echange_id))
        echange = result.scalar_one_or_none()
        if not echange or echange.statut != StatutEchange.en_attente:
            await callback.answer("Ce match n'est plus disponible.", show_alert=True)
            return

        result_user = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result_user.scalar_one()

        if action == "refuse":
            echange.statut = StatutEchange.annule
            # Remettre les deux annonces en ouvertes pour un nouveau matching
            result_offre = await session.execute(select(Annonce).where(Annonce.id == echange.annonce_offre_id))
            result_demande = await session.execute(select(Annonce).where(Annonce.id == echange.annonce_demande_id))
            result_offre.scalar_one().statut = StatutAnnonce.ouverte
            result_demande.scalar_one().statut = StatutAnnonce.ouverte
            await session.commit()
            await callback.message.edit_text("🚫 Match refusé.")
            return

        deja_confirme = (
            (user.id == echange.partie_a_id and echange.confirmation_a)
            or (user.id == echange.partie_b_id and echange.confirmation_b)
        )
        if deja_confirme:
            await callback.answer("Tu as déjà accepté ce match.", show_alert=True)
            return

        # action == accept — on bloque la garantie de CETTE partie
        try:
            await bloquer_garantie(session, user, echange.montant_escrow, echange.id)
        except SoldeInsuffisant:
            await callback.answer(
                "Solde insuffisant pour la garantie. Va dans Portefeuille pour déposer des Stars.",
                show_alert=True,
            )
            return

        if user.id == echange.partie_a_id:
            echange.confirmation_a = True
        else:
            echange.confirmation_b = True

        if echange.confirmation_a and echange.confirmation_b:
            echange.statut = StatutEchange.en_cours
            echange.accepte_at = datetime.utcnow()
            message_notif = (
                "✅ Les deux parties ont accepté et déposé leur garantie. "
                "L'échange peut avoir lieu. Une fois fait, la partie qui a rendu le service "
                "envoie une preuve simple (photo ou message vocal court)."
            )
        else:
            message_notif = "✅ Ton acceptation est enregistrée — en attente de l'autre partie."

        await session.commit()
        await callback.message.edit_text(message_notif)


@router.message(F.text == "🔄 Mes échanges en cours")
async def lister_echanges(message: Message):
    async with async_session() as session:
        result_user = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result_user.scalar_one_or_none()
        if not user:
            await message.answer("Fais /start d'abord.")
            return

        result = await session.execute(
            select(Echange).where(
                (Echange.partie_a_id == user.id) | (Echange.partie_b_id == user.id)
            ).where(Echange.statut.in_([StatutEchange.en_cours, StatutEchange.preuve_soumise, StatutEchange.accepte]))
        )
        echanges = result.scalars().all()

    if not echanges:
        await message.answer("Aucun échange en cours actuellement.")
        return

    lignes = ["*Tes échanges en cours :*", ""]
    for e in echanges:
        lignes.append(f"• Échange #{e.id} — statut : {e.statut.value}")
    await message.answer("\n".join(lignes), parse_mode="Markdown")


@router.message(F.photo | F.voice)
async def recevoir_preuve(message: Message, state: FSMContext):
    """L'utilisateur envoie une photo ou un vocal pendant un échange en cours."""
    data = await state.get_data()
    echange_id = data.get("echange_id_courant")
    if not echange_id:
        return  # média envoyé hors contexte, on ignore

    if message.voice and message.voice.duration > 15:
        await message.answer("Le vocal doit faire 15 secondes max. Réessaie.")
        return

    file_id = message.photo[-1].file_id if message.photo else message.voice.file_id
    type_preuve = "photo" if message.photo else "vocal"

    async with async_session() as session:
        result = await session.execute(select(Echange).where(Echange.id == echange_id))
        echange = result.scalar_one()
        echange.preuve_file_id = file_id
        echange.preuve_type = type_preuve
        echange.statut = StatutEchange.preuve_soumise
        await session.commit()

        result_a = await session.execute(select(User).where(User.id == echange.partie_a_id))
        result_b = await session.execute(select(User).where(User.id == echange.partie_b_id))
        user_a, user_b = result_a.scalar_one(), result_b.scalar_one()

        autre_id = user_b.telegram_id if message.from_user.id == user_a.telegram_id else user_a.telegram_id

    await message.bot.send_message(
        autre_id,
        "📩 Une preuve a été soumise pour ton échange en cours. Confirme si tout est en ordre :",
        reply_markup=clavier_confirmer_reception(echange_id),
    )
    await message.answer("Preuve envoyée, en attente de confirmation de l'autre partie.")


@router.callback_query(F.data.startswith("proof:ok:"))
async def confirmer_reception(callback: CallbackQuery):
    echange_id = int(callback.data.split(":")[2])

    async with async_session() as session:
        result = await session.execute(select(Echange).where(Echange.id == echange_id))
        echange = result.scalar_one()

        result_a = await session.execute(select(User).where(User.id == echange.partie_a_id))
        result_b = await session.execute(select(User).where(User.id == echange.partie_b_id))
        user_a, user_b = result_a.scalar_one(), result_b.scalar_one()

        # Le bénéficiaire de la garantie est celui qui a RENDU le service (côté offre)
        beneficiaire = user_a

        echange.statut = StatutEchange.valide
        echange.valide_at = datetime.utcnow()

        montant_net, commission = await liberer_garantie_avec_commission(session, beneficiaire, echange)
        await appliquer_delta_score(session, user_a, SCORE_GAIN_ECHANGE_REUSSI, "Échange validé")
        await appliquer_delta_score(session, user_b, SCORE_GAIN_ECHANGE_REUSSI, "Échange validé")

        await session.commit()

    await callback.message.edit_text("✅ Échange validé. Garantie libérée, score mis à jour pour les deux parties.")
    await callback.bot.send_message(
        user_a.telegram_id,
        f"✅ Échange validé ! {montant_net} Stars créditées sur ton solde (commission : {commission} Stars).",
    )
