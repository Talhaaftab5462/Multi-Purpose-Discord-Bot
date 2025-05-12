# database.py
import asyncpg
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

async def create_pool():
    return await asyncpg.create_pool(DATABASE_URL)

async def init_db(pool):
    async with pool.acquire() as connection:
        # Create the user_data table if it doesn't exist
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS user_data (
                user_id BIGINT PRIMARY KEY,
                saves INTEGER NOT NULL,
                last_collected TIMESTAMP NOT NULL,
                locked_until TIMESTAMP,
                lockout_count INTEGER NOT NULL
            );
        ''')
        # Create the global_state table for storing key/value pairs
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        ''')


async def get_global_state(pool, key: str):
    async with pool.acquire() as connection:
        row = await connection.fetchrow('SELECT value FROM global_state WHERE key = $1', key)
        return row['value'] if row else None

async def set_global_state(pool, key: str, value: str):
    async with pool.acquire() as connection:
        await connection.execute('''
            INSERT INTO global_state (key, value)
            VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = $2;
        ''', key, value)

async def get_highest_count(pool):
    async with pool.acquire() as connection:
        row = await connection.fetchrow('SELECT value FROM global_state WHERE key = $1', 'highest_count')
        return int(row['value']) if row and row['value'] else 0

async def update_highest_count(pool, current_count):
    async with pool.acquire() as connection:
        highest_count = await get_highest_count(pool)
        if current_count > highest_count:
            await connection.execute('''
                INSERT INTO global_state (key, value)
                VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = $2;
            ''', 'highest_count', str(current_count))
            return True
        return False

async def get_user(pool, user_id: int):
    async with pool.acquire() as connection:
        row = await connection.fetchrow('SELECT * FROM user_data WHERE user_id = $1', user_id)
        return row

async def create_or_update_user(pool, user_id: int, saves: int, last_collected: datetime, locked_until, lockout_count: int):
    async with pool.acquire() as connection:
        await connection.execute('''
            INSERT INTO user_data(user_id, saves, last_collected, locked_until, lockout_count)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE
            SET saves = EXCLUDED.saves,
                last_collected = EXCLUDED.last_collected,
                locked_until = EXCLUDED.locked_until,
                lockout_count = EXCLUDED.lockout_count;
        ''', user_id, saves, last_collected, locked_until, lockout_count)

async def get_or_create_user(pool, user_id: int):
    user = await get_user(pool, user_id)
    if user is None:
        now = datetime.utcnow()
        # Default: 1 save, lockout_count 0, no locked_until
        await create_or_update_user(pool, user_id, 1, now, None, 0)
        user = await get_user(pool, user_id)
    return user
