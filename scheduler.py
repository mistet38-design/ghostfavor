import logging
from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from config import TIMEOUT_MATCH_MINUTES
from database.models import Annonce, Echange, StatutAnnonce, StatutEchange, User
from database.session import async_session
from keyboards.menus import clavier_accepter_refuser
from services.escrow import rembourser_garantie
from services.matching import trouver_correspondance

logger = logging.getLogger(__name__)


async def _reactiver_ou_expirer_annonce(session, annonce_id: int) -> Annonce:
    result = await session.execute(select(Annonce).where(Annonce.id == annonce_id))
    annonce = result.scalar_one()
    if annonce.creneau_fin < datetime.utcnow():
        annonce.statut = StatutAnnonce.expiree
    else:
        annonce.statut = StatutAnnonce.ouverte
    return annonce


async def job_expirer_matchs_non_confirmes(bot: Bot):
    """
    Annule les échanges en_attente créés depuis plus de TIMEOUT_MATCH_MINUTES.
    Rembourse toute garantie déjà bloquée par la partie qui avait accepté.
    Remet les annonces en ouvertes (ou expirées si leur créneau est dépassé).
    """
    seuil = datetime.utcnow() - timedelta(minutes=TIMEOUT_MATCH_MINUTES)

    async with async_session() as session:
        result = await session.execute(
            select(Echange).where(
                Echange.statut == StatutEchange.en_attente,
                Echange.created_at < seuil,
            )
        )
        echanges_expires = result.scalars().all()

        for echange in echanges_expires:
            echange.statut = StatutEchange.annule

            result_a = await session.execute(select(User).where(User.id == echange.partie_a_id))
            result_b = await session.execute(select(User).where(User.id == echange.partie_b_id))
            user_a, user_b = result_a.scalar_one(), result_b.scalar_one()

            # Rembourser la garantie de quiconque avait déjà accepté avant le timeout
            if echange.confirmation_a:
                await rembourser_garantie(session, user_a, echange.montant_escrow, echange.id)
            if echange.confirmation_b:
                await rembourser_garantie(session, user_b, echange.montant_escrow, echange.id)

            annonce_offre = await _reactiver_ou_expirer_annonce(session, echange.annonce_offre_id)
            annonce_demande = await _reactiver_ou_expirer_annonce(session, echange.annonce_demande_id)

            await session.commit()

            for user in (user_a, user_b):
                try:
                    await bot.send_message(
                        user.telegram_id,
                        f"⏱️ Le match #{echange.id} a expiré faute de confirmation à temps. "
                        "Toute garantie déjà déposée a été remboursée. "
                        "Ton annonce reste active si son créneau n'est pas passé.",
                    )
                except Exception:
                    logger.warning("Impossible de notifier user %s (timeout match)", user.telegram_id)

        if echanges_expires:
            logger.info("Matchs expirés traités : %d", len(echanges_expires))


async def job_expirer_annonces_perimees():
    """Marque comme expirées les annonces ouvertes dont le créneau est déjà passé."""
    async with async_session() as session:
        result = await session.execute(
            select(Annonce).where(
                Annonce.statut == StatutAnnonce.ouverte,
                Annonce.creneau_fin < datetime.utcnow(),
            )
        )
        annonces = result.scalars().all()
        for annonce in annonces:
            annonce.statut = StatutAnnonce.expiree
        if annonces:
            await session.commit()
            logger.info("Annonces expirées : %d", len(annonces))


async def job_relancer_matching(bot: Bot):
    """
    Filet de sécurité : retente le matching sur toutes les annonces encore ouvertes,
    au cas où deux annonces compatibles auraient été publiées quasi simultanément
    et manqué le matching immédiat fait à la publication.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Annonce).where(
                Annonce.statut == StatutAnnonce.ouverte,
                Annonce.creneau_fin >= datetime.utcnow(),
            )
        )
        annonces_ouvertes = result.scalars().all()

        deja_matchees_ce_cycle = set()

        for annonce in annonces_ouvertes:
            if annonce.id in deja_matchees_ce_cycle:
                continue

            # recharger le statut au cas où elle vient d'être matchée dans ce même cycle
            result_check = await session.execute(select(Annonce).where(Annonce.id == annonce.id))
            annonce_fraiche = result_check.scalar_one()
            if annonce_fraiche.statut != StatutAnnonce.ouverte:
                continue

            correspondance = await trouver_correspondance(session, annonce_fraiche)
            if not correspondance:
                continue

            annonce_fraiche.statut = StatutAnnonce.matchee
            correspondance.statut = StatutAnnonce.matchee
            deja_matchees_ce_cycle.add(annonce_fraiche.id)
            deja_matchees_ce_cycle.add(correspondance.id)

            if annonce_fraiche.type.value == "offre":
                offre, demande = annonce_fraiche, correspondance
            else:
                offre, demande = correspondance, annonce_fraiche

            echange = Echange(
                annonce_offre_id=offre.id,
                annonce_demande_id=demande.id,
                partie_a_id=offre.user_id,
                partie_b_id=demande.user_id,
                montant_escrow=max(offre.depot_stars, demande.depot_stars),
            )
            session.add(echange)
            await session.flush()

            result_a = await session.execute(select(User).where(User.id == offre.user_id))
            result_b = await session.execute(select(User).where(User.id == demande.user_id))
            user_a, user_b = result_a.scalar_one(), result_b.scalar_one()

            await session.commit()

            for uid in (user_a.telegram_id, user_b.telegram_id):
                try:
                    await bot.send_message(
                        uid,
                        "🔔 *Match trouvé !* Une correspondance vient d'apparaître pour ton annonce.",
                        parse_mode="Markdown",
                        reply_markup=clavier_accepter_refuser(echange.id),
                    )
                except Exception:
                    logger.warning("Impossible de notifier user %s (nouveau match)", uid)


def demarrer_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    scheduler.add_job(job_expirer_matchs_non_confirmes, "interval", minutes=5, args=[bot])
    scheduler.add_job(job_expirer_annonces_perimees, "interval", minutes=10)
    scheduler.add_job(job_relancer_matching, "interval", minutes=10, args=[bot])

    scheduler.start()
    logger.info("Scheduler démarré (expiration matchs, expiration annonces, relance matching)")
    return scheduler
