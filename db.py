import typing as tp
import aiosqlite

db_name = 'cinema_bot.db'


async def init_database() -> None:
    async with aiosqlite.connect(db_name) as db:
        await db.executescript(
            """
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                );


                CREATE TABLE IF NOT EXISTS film_stats (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    film_id INTEGER NOT NULL,
                    film_title TEXT NOT NULL,
                    count INTEGER DEFAULT 0
                )"""
        )
        await db.commit()


async def get_history(user_id: int) -> tp.Any:
    async with aiosqlite.connect(db_name) as db:
        cursor = await db.execute(
            "SELECT query FROM search_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5 ",
            (user_id,)
        )
        return await cursor.fetchall()


async def write_history(user_id: int, query: str) -> None:
    async with aiosqlite.connect(db_name) as db:
        await db.execute(
            "INSERT INTO search_history (user_id, query) VALUES (?, ?)", (user_id, query)
        )
        await db.commit()


async def get_stats(user_id: int) -> tp.Any:
    async with aiosqlite.connect(db_name) as db:
        cursor = await db.execute(
            "SELECT film_title, count FROM film_stats WHERE user_id = ? ORDER BY count DESC LIMIT 5", (user_id,)
        )
        return await cursor.fetchall()


async def write_stats(user_id: int, film_id: int, film_title: str) -> None:
    async with aiosqlite.connect(db_name) as db:
        cursor = await db.execute(
            "SELECT count FROM film_stats WHERE user_id = ? AND film_id = ?", (user_id, film_id)
        )
        result = await cursor.fetchone()

        if result:
            new_count = result[0] + 1
            await db.execute(
                "UPDATE film_stats SET count = ? WHERE user_id = ? AND film_id = ?",
                (new_count, user_id, film_id)
            )
        else:
            await db.execute(
                "INSERT INTO film_stats (user_id, film_id, film_title, count) VALUES (?, ?, ?, 1)",
                (user_id, film_id, film_title)
            )

        await db.commit()
