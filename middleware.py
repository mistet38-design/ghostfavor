import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from sqlalchemy import select

from database.models import User
from database.session import async_session

# Note : stockage en mémoire — suffisant pour une seule instance de bot.
# Pour plusieurs instances (scaling horizontal), remplacer par un compteur Redis
# avec expiration (INCR + EXPIRE) pour partager l'état entre process.
_derniers_appels: Dict[int, float] = {}
DELAI_MIN_SECONDES = 0.7


class ThrottlingMiddleware(BaseMiddleware):
    """Anti-spam basique : ignore les messages/callbacks trop rapprochés d'un même utilisateur."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        maintenant = time.monotonic()
        dernier = _derniers_appels.get(user.id, 0)

        if maintenant - dernier < DELAI_MIN_SECONDES:
            return  # on ignore silencieusement, pas de réponse pour ne pas encourager le spam

        _derniers_appels[user.id] = maintenant
        return await handler(event, data)


class BanCheckMiddleware(BaseMiddleware):
    """Bloque toute interaction pour les comptes bannis (sauf réponse d'information)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        async with async_session() as session:
            result = await session.execute(select(User).where(User.telegram_id == user.id))
            db_user = result.scalar_one_or_none()

        if db_user and db_user.banni:
            bot = data.get("bot")
            if bot:
                try:
                    await bot.send_message(
                        user.id, "🚫 Ton compte a été banni de QuietSwap suite à un litige ou un abus."
                    )
                except Exception:
                    pass
            return

        return await handler(event, data)
