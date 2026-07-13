import asyncpg
import asyncio
from asyncpg.pool import Pool
import os
import logging

DATABASE_URL = os.getenv("DATABASE_URL")
pool: Pool = None

async def init_pool():
    global pool
    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=30,
        max_inactive_connection_lifetime=300,
        statement_cache_size=0
    )
    return pool

async def execute(query, *args, fetchone=False, fetchall=False, fetchval=False):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with pool.acquire() as conn:
                if fetchone:
                    return await conn.fetchrow(query, *args)
                elif fetchall:
                    return await conn.fetch(query, *args)
                elif fetchval:
                    return await conn.fetchval(query, *args)
                else:
                    return await conn.execute(query, *args)
        except (asyncpg.exceptions.ConnectionDoesNotExistError,
                asyncpg.exceptions.InterfaceError,
                ConnectionError) as e:
            logging.warning(f"DB connection error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
        except Exception as e:
            logging.error(f"DB error: {e}")
            raise

async def init_tables():
    await execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            lang TEXT DEFAULT 'ru',
            email TEXT,
            email_verified BOOLEAN DEFAULT FALSE
        )
    """)
    await execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            amount INTEGER,
            price INTEGER,
            order_id TEXT,
            status TEXT,
            date TEXT
        )
    """)
    await execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            amount INTEGER,
            status TEXT,
            date TEXT,
            screenshot TEXT,
            expire_at TEXT
        )
    """)
