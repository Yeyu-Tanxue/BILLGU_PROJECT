import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "vocab.db")
# Vercel 运行时文件系统只允许写 /tmp；若未配置 DATABASE_URL，回退到 /tmp。
DB_PATH = os.environ.get("DB_PATH") or ("/tmp/vocab.db" if os.environ.get("VERCEL") else DEFAULT_DB_PATH)


def _is_pg():
    return DATABASE_URL.startswith("postgres")


class DBWrapper:
    """让 psycopg2 cursor 的用法和 sqlite3 conn.execute().fetchone() 兼容"""

    def __init__(self, conn, cursor):
        self._conn = conn
        self._cur = cursor

    def execute(self, sql, params=None):
        if _is_pg():
            sql = sql.replace("?", "%s")
        self._cur.execute(sql, params or ())
        return self

    def executemany(self, sql, params_list):
        if _is_pg():
            from psycopg2.extras import execute_batch

            sql = sql.replace("?", "%s")
            execute_batch(self._cur, sql, params_list, page_size=500)
        else:
            self._cur.executemany(sql, params_list)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    def commit(self):
        self._conn.commit()

    def close(self):
        self._cur.close()
        self._conn.close()


def get_db():
    if _is_pg():
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        return DBWrapper(conn, cur)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return DBWrapper(conn, conn.cursor())


_PG_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wordbooks (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    language TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS words (
    id SERIAL PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES wordbooks(id),
    word TEXT NOT NULL,
    phonetic TEXT,
    definition TEXT NOT NULL,
    seq INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS user_plan (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    book_id INTEGER REFERENCES wordbooks(id),
    daily_count INTEGER NOT NULL DEFAULT 30,
    start_date TEXT NOT NULL,
    interests TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS daily_lists (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER DEFAULT 0,
    day_number INTEGER NOT NULL,
    word_ids TEXT NOT NULL,
    story TEXT,
    learned INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    list_id INTEGER NOT NULL REFERENCES daily_lists(id),
    user_id INTEGER DEFAULT 0,
    review_date TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    round INTEGER NOT NULL DEFAULT 1,
    completed_date TEXT
);

CREATE TABLE IF NOT EXISTS review_sentences (
    id SERIAL PRIMARY KEY,
    list_id INTEGER NOT NULL REFERENCES daily_lists(id),
    word_id INTEGER NOT NULL REFERENCES words(id),
    sentence TEXT NOT NULL,
    translation TEXT NOT NULL,
    blank_word TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_settings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE REFERENCES users(id),
    primary_url TEXT NOT NULL DEFAULT '',
    primary_key TEXT NOT NULL DEFAULT '',
    primary_model TEXT NOT NULL DEFAULT '',
    light_url TEXT NOT NULL DEFAULT '',
    light_key TEXT NOT NULL DEFAULT '',
    light_model TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id SERIAL PRIMARY KEY,
    internal_user_id INTEGER UNIQUE REFERENCES users(id),
    auth0_sub TEXT UNIQUE NOT NULL,
    email TEXT,
    name TEXT,
    avatar_url TEXT,
    last_login_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public."user" (
    user_id TEXT PRIMARY KEY,
    tokens INTEGER DEFAULT 50000,
    name TEXT,
    email TEXT,
    time TIMESTAMPTZ DEFAULT NOW(),
    hourly_requests INTEGER DEFAULT 0,
    last_request_time TIMESTAMPTZ DEFAULT NOW(),
    generated BOOLEAN,
    stripe_subscription TEXT,
    stripe_customer TEXT,
    last_payment_time TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS xhs_note_batches (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by TEXT,
    wordbook_id INTEGER NOT NULL REFERENCES wordbooks(id),
    language TEXT NOT NULL DEFAULT 'en',
    mode TEXT NOT NULL DEFAULT 'scene',
    scene TEXT NOT NULL,
    topic TEXT NOT NULL,
    style TEXT NOT NULL,
    note_count INTEGER NOT NULL DEFAULT 10,
    words_per_note INTEGER NOT NULL DEFAULT 5,
    generation_prompt TEXT NOT NULL DEFAULT '',
    company_name TEXT NOT NULL DEFAULT '',
    company_ticker TEXT NOT NULL DEFAULT '',
    company_angle TEXT NOT NULL DEFAULT '',
    company_profile_json TEXT NOT NULL DEFAULT '{}',
    matched_vocabulary_json TEXT NOT NULL DEFAULT '[]',
    source_urls_json TEXT NOT NULL DEFAULT '[]',
    source_warnings_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'completed',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS xhs_notes (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES xhs_note_batches(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'draft',
    selected_title TEXT NOT NULL DEFAULT '',
    titles_json TEXT NOT NULL DEFAULT '[]',
    body TEXT NOT NULL DEFAULT '',
    vocabulary_json TEXT NOT NULL DEFAULT '[]',
    cover_text TEXT NOT NULL DEFAULT '',
    image_prompt TEXT NOT NULL DEFAULT '',
    hashtags_json TEXT NOT NULL DEFAULT '[]',
    cta TEXT NOT NULL DEFAULT '',
    quality_notes_json TEXT NOT NULL DEFAULT '[]',
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    visual_header_json TEXT NOT NULL DEFAULT '{}',
    company_facts_used_json TEXT NOT NULL DEFAULT '[]',
    fact_check_notes_json TEXT NOT NULL DEFAULT '[]',
    word_context_map_json TEXT NOT NULL DEFAULT '[]',
    published_url TEXT,
    published_at TIMESTAMP,
    views INTEGER,
    likes INTEGER,
    favorites INTEGER,
    comments INTEGER,
    profile_visits INTEGER,
    product_visits INTEGER,
    operator_notes TEXT
);
"""

_SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wordbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    language TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES wordbooks(id),
    word TEXT NOT NULL,
    phonetic TEXT,
    definition TEXT NOT NULL,
    seq INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS user_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    book_id INTEGER REFERENCES wordbooks(id),
    daily_count INTEGER NOT NULL DEFAULT 30,
    start_date TEXT NOT NULL,
    interests TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS daily_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER DEFAULT 0,
    day_number INTEGER NOT NULL,
    word_ids TEXT NOT NULL,
    story TEXT,
    learned INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES daily_lists(id),
    user_id INTEGER DEFAULT 0,
    review_date TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    round INTEGER NOT NULL DEFAULT 1,
    completed_date TEXT
);

CREATE TABLE IF NOT EXISTS review_sentences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES daily_lists(id),
    word_id INTEGER NOT NULL REFERENCES words(id),
    sentence TEXT NOT NULL,
    translation TEXT NOT NULL,
    blank_word TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE REFERENCES users(id),
    primary_url TEXT NOT NULL DEFAULT '',
    primary_key TEXT NOT NULL DEFAULT '',
    primary_model TEXT NOT NULL DEFAULT '',
    light_url TEXT NOT NULL DEFAULT '',
    light_key TEXT NOT NULL DEFAULT '',
    light_model TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    internal_user_id INTEGER UNIQUE REFERENCES users(id),
    auth0_sub TEXT UNIQUE NOT NULL,
    email TEXT,
    name TEXT,
    avatar_url TEXT,
    last_login_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS "user" (
    user_id TEXT PRIMARY KEY,
    tokens INTEGER DEFAULT 50000,
    name TEXT,
    email TEXT,
    time TEXT DEFAULT (datetime('now')),
    hourly_requests INTEGER DEFAULT 0,
    last_request_time TEXT DEFAULT (datetime('now')),
    generated INTEGER,
    stripe_subscription TEXT,
    stripe_customer TEXT,
    last_payment_time TEXT
);

CREATE TABLE IF NOT EXISTS xhs_note_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT (datetime('now')),
    created_by TEXT,
    wordbook_id INTEGER NOT NULL REFERENCES wordbooks(id),
    language TEXT NOT NULL DEFAULT 'en',
    mode TEXT NOT NULL DEFAULT 'scene',
    scene TEXT NOT NULL,
    topic TEXT NOT NULL,
    style TEXT NOT NULL,
    note_count INTEGER NOT NULL DEFAULT 10,
    words_per_note INTEGER NOT NULL DEFAULT 5,
    generation_prompt TEXT NOT NULL DEFAULT '',
    company_name TEXT NOT NULL DEFAULT '',
    company_ticker TEXT NOT NULL DEFAULT '',
    company_angle TEXT NOT NULL DEFAULT '',
    company_profile_json TEXT NOT NULL DEFAULT '{}',
    matched_vocabulary_json TEXT NOT NULL DEFAULT '[]',
    source_urls_json TEXT NOT NULL DEFAULT '[]',
    source_warnings_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'completed',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS xhs_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES xhs_note_batches(id),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'draft',
    selected_title TEXT NOT NULL DEFAULT '',
    titles_json TEXT NOT NULL DEFAULT '[]',
    body TEXT NOT NULL DEFAULT '',
    vocabulary_json TEXT NOT NULL DEFAULT '[]',
    cover_text TEXT NOT NULL DEFAULT '',
    image_prompt TEXT NOT NULL DEFAULT '',
    hashtags_json TEXT NOT NULL DEFAULT '[]',
    cta TEXT NOT NULL DEFAULT '',
    quality_notes_json TEXT NOT NULL DEFAULT '[]',
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    visual_header_json TEXT NOT NULL DEFAULT '{}',
    company_facts_used_json TEXT NOT NULL DEFAULT '[]',
    fact_check_notes_json TEXT NOT NULL DEFAULT '[]',
    word_context_map_json TEXT NOT NULL DEFAULT '[]',
    published_url TEXT,
    published_at TEXT,
    views INTEGER,
    likes INTEGER,
    favorites INTEGER,
    comments INTEGER,
    profile_visits INTEGER,
    product_visits INTEGER,
    operator_notes TEXT
);
"""


def init_db():
    if _is_pg():
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        for stmt in _PG_TABLES.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        migrations = [
            'ALTER TABLE public."user" ADD COLUMN IF NOT EXISTS stripe_subscription TEXT',
            'ALTER TABLE public."user" ADD COLUMN IF NOT EXISTS stripe_customer TEXT',
            'ALTER TABLE public."user" ADD COLUMN IF NOT EXISTS last_payment_time TIMESTAMPTZ',
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS created_by TEXT",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS wordbook_id INTEGER",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'en'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'scene'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS scene TEXT NOT NULL DEFAULT 'company_profile'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS topic TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS style TEXT NOT NULL DEFAULT 'story'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS note_count INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS words_per_note INTEGER NOT NULL DEFAULT 5",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS generation_prompt TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS company_name TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS company_ticker TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS company_angle TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS company_profile_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS matched_vocabulary_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS source_urls_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS source_warnings_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed'",
            "ALTER TABLE xhs_note_batches ADD COLUMN IF NOT EXISTS error_message TEXT",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS batch_id INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS selected_title TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS titles_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS body TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS vocabulary_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS cover_text TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS image_prompt TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS hashtags_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS cta TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS quality_notes_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS risk_flags_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS visual_header_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS company_facts_used_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS fact_check_notes_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS word_context_map_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS published_url TEXT",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS published_at TIMESTAMP",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS views INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS likes INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS favorites INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS comments INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS profile_visits INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS product_visits INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN IF NOT EXISTS operator_notes TEXT",
            'CREATE INDEX IF NOT EXISTS idx_user_email ON public."user" (email)',
            'CREATE INDEX IF NOT EXISTS idx_user_stripe_subscription ON public."user" (stripe_subscription)',
        ]
        for stmt in migrations:
            cur.execute(stmt)
        conn.commit()
        cur.close()
        conn.close()
    else:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.executescript(_SQLITE_TABLES)
        conn.commit()
        # 兼容旧数据库迁移
        migrations = [
            "ALTER TABLE user_plan ADD COLUMN interests TEXT DEFAULT ''",
            "ALTER TABLE user_plan ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE user_plan ADD COLUMN user_id INTEGER",
            "ALTER TABLE reviews ADD COLUMN round INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE reviews ADD COLUMN completed_date TEXT",
            "ALTER TABLE reviews ADD COLUMN user_id INTEGER DEFAULT 0",
            "ALTER TABLE daily_lists ADD COLUMN plan_id INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE daily_lists ADD COLUMN user_id INTEGER DEFAULT 0",
            'ALTER TABLE "user" ADD COLUMN stripe_subscription TEXT',
            'ALTER TABLE "user" ADD COLUMN stripe_customer TEXT',
            'ALTER TABLE "user" ADD COLUMN last_payment_time TEXT',
            "ALTER TABLE xhs_note_batches ADD COLUMN created_at TEXT DEFAULT (datetime('now'))",
            "ALTER TABLE xhs_note_batches ADD COLUMN created_by TEXT",
            "ALTER TABLE xhs_note_batches ADD COLUMN wordbook_id INTEGER",
            'ALTER TABLE xhs_note_batches ADD COLUMN language TEXT NOT NULL DEFAULT "en"',
            'ALTER TABLE xhs_note_batches ADD COLUMN mode TEXT NOT NULL DEFAULT "scene"',
            'ALTER TABLE xhs_note_batches ADD COLUMN scene TEXT NOT NULL DEFAULT "company_profile"',
            'ALTER TABLE xhs_note_batches ADD COLUMN topic TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_note_batches ADD COLUMN style TEXT NOT NULL DEFAULT "story"',
            "ALTER TABLE xhs_note_batches ADD COLUMN note_count INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE xhs_note_batches ADD COLUMN words_per_note INTEGER NOT NULL DEFAULT 5",
            'ALTER TABLE xhs_note_batches ADD COLUMN generation_prompt TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_note_batches ADD COLUMN company_name TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_note_batches ADD COLUMN company_ticker TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_note_batches ADD COLUMN company_angle TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_note_batches ADD COLUMN company_profile_json TEXT NOT NULL DEFAULT "{}"',
            'ALTER TABLE xhs_note_batches ADD COLUMN matched_vocabulary_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_note_batches ADD COLUMN source_urls_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_note_batches ADD COLUMN source_warnings_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_note_batches ADD COLUMN status TEXT NOT NULL DEFAULT "completed"',
            "ALTER TABLE xhs_note_batches ADD COLUMN error_message TEXT",
            "ALTER TABLE xhs_notes ADD COLUMN batch_id INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN created_at TEXT DEFAULT (datetime('now'))",
            "ALTER TABLE xhs_notes ADD COLUMN updated_at TEXT DEFAULT (datetime('now'))",
            'ALTER TABLE xhs_notes ADD COLUMN status TEXT NOT NULL DEFAULT "draft"',
            'ALTER TABLE xhs_notes ADD COLUMN selected_title TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_notes ADD COLUMN titles_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_notes ADD COLUMN body TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_notes ADD COLUMN vocabulary_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_notes ADD COLUMN cover_text TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_notes ADD COLUMN image_prompt TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_notes ADD COLUMN hashtags_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_notes ADD COLUMN cta TEXT NOT NULL DEFAULT ""',
            'ALTER TABLE xhs_notes ADD COLUMN quality_notes_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_notes ADD COLUMN risk_flags_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_notes ADD COLUMN visual_header_json TEXT NOT NULL DEFAULT "{}"',
            'ALTER TABLE xhs_notes ADD COLUMN company_facts_used_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_notes ADD COLUMN fact_check_notes_json TEXT NOT NULL DEFAULT "[]"',
            'ALTER TABLE xhs_notes ADD COLUMN word_context_map_json TEXT NOT NULL DEFAULT "[]"',
            "ALTER TABLE xhs_notes ADD COLUMN published_url TEXT",
            "ALTER TABLE xhs_notes ADD COLUMN published_at TEXT",
            "ALTER TABLE xhs_notes ADD COLUMN views INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN likes INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN favorites INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN comments INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN profile_visits INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN product_visits INTEGER",
            "ALTER TABLE xhs_notes ADD COLUMN operator_notes TEXT",
            'CREATE INDEX IF NOT EXISTS idx_user_email ON "user" (email)',
            'CREATE INDEX IF NOT EXISTS idx_user_stripe_subscription ON "user" (stripe_subscription)',
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
                conn.commit()
            except Exception:
                pass

        # 旧 api_settings 表有 CHECK(id=1)，需要重建
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(api_settings)").fetchall()]
            if "user_id" not in cols:
                conn.executescript("""
                    DROP TABLE IF EXISTS api_settings;
                    CREATE TABLE api_settings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER UNIQUE REFERENCES users(id),
                        primary_url TEXT NOT NULL DEFAULT '',
                        primary_key TEXT NOT NULL DEFAULT '',
                        primary_model TEXT NOT NULL DEFAULT '',
                        light_url TEXT NOT NULL DEFAULT '',
                        light_key TEXT NOT NULL DEFAULT '',
                        light_model TEXT NOT NULL DEFAULT ''
                    );
                """)
                conn.commit()
        except Exception:
            pass

        # 新增 Auth0 用户映射表
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    internal_user_id INTEGER UNIQUE REFERENCES users(id),
                    auth0_sub TEXT UNIQUE NOT NULL,
                    email TEXT,
                    name TEXT,
                    avatar_url TEXT,
                    last_login_at TEXT DEFAULT (datetime('now'))
                );
            """)
            conn.commit()
        except Exception:
            pass

        conn.close()
