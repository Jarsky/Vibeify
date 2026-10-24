"""Small admin commands:  python -m app.cli make-admin <email|spotify-user-id>"""
import asyncio
import sys

from sqlalchemy import func, select

from .db import sessionmaker
from .models import SpotifyConnection, User


async def make_admin(key: str) -> int:
    async with sessionmaker()() as db:
        user = (await db.execute(select(User).where(func.lower(User.email) == key.lower()))).scalar_one_or_none()
        if user is None:
            conn = (await db.execute(select(SpotifyConnection).where(SpotifyConnection.spotify_user_id == key))).scalar_one_or_none()
            user = await db.get(User, conn.user_id) if conn else None
        if user is None:
            print(f"No user with email or Spotify id {key!r}. They need to sign in once first.")
            return 1
        user.is_admin = True
        await db.commit()
        print(f"{user.display_name} is now an admin.")
        return 0


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "make-admin":
        print(__doc__)
        return 2
    return asyncio.run(make_admin(sys.argv[2]))


if __name__ == "__main__":
    sys.exit(main())
