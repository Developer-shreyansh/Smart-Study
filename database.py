import sqlite3
from contextlib import contextmanager
from backend.config import settings

DB_PATH = settings.data_dir / "database" / "smart_study.sqlite3"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL, stored_name TEXT NOT NULL,
 pages INTEGER NOT NULL DEFAULT 0, text_content TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS document_chunks (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 page_number INTEGER, content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS quiz_sessions (id INTEGER PRIMARY KEY, title TEXT NOT NULL, score INTEGER, total INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS quiz_questions (
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, prompt TEXT NOT NULL, options_json TEXT NOT NULL,
 correct_index INTEGER NOT NULL, explanation TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quiz_answers (
 id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
 selected_index INTEGER NOT NULL, is_correct INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS flashcard_decks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS flashcards (id INTEGER PRIMARY KEY, deck_id INTEGER NOT NULL REFERENCES flashcard_decks(id) ON DELETE CASCADE, front TEXT NOT NULL, back TEXT NOT NULL, flagged INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS study_tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, subject TEXT, due_date TEXT, priority TEXT NOT NULL DEFAULT 'Medium', completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS study_goals (id INTEGER PRIMARY KEY, title TEXT NOT NULL, target_date TEXT, completed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally: con.close()

def init_db():
    with connect() as con: con.executescript(SCHEMA)

def rows(query, args=()):
    with connect() as con: return [dict(r) for r in con.execute(query, args).fetchall()]

def row(query, args=()):
    data = rows(query, args)
    return data[0] if data else None
