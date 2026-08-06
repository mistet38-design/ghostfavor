from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select

from config import DEPOT_MIN_PAR_NIVEAU, SEUILS_NIVEAU
from database.models import ScoreLog, User
from database.session import async_session

router = Router()


@router.message(F.text == "⭐ Mon score & historique")
async def afficher_score(message: Message):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("Fais /start d'abord.")
            return

        result_logs = await session.execute(
            select(ScoreLog).where(ScoreLog.user_id == user.id).order_by(ScoreLog.created_at.desc()).limit(10)
        )
        logs = result_logs.scalars().all()

    depot_actuel = DEPOT_MIN_PAR_NIVEAU[user.niveau.value]

    lignes = [
        f"⭐ *Score : {user.score}* — niveau {user.niveau.value}",
        f"Garantie requise actuelle : {depot_actuel} Stars",
        "",
        "*Historique récent :*",
    ]
    if not logs:
        lignes.append("Aucun mouvement de score pour l'instant.")
    for log in logs:
        signe = "+" if log.delta >= 0 else ""
        lignes.append(f"• {signe}{log.delta} — {log.raison}")

    await message.answer("\n".join(lignes), parse_mode="Markdown")
