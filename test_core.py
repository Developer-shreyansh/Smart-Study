import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app import health, chat, ChatRequest, generate_quiz, QuizRequest, submit_quiz, QuizSubmission
from backend.database import init_db, row, connect


class SmartStudyCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = TemporaryDirectory()
        cls.db_path_patch = patch("backend.database.DB_PATH", Path(cls.temp_dir.name) / "tests.sqlite3")
        cls.db_path_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.db_path_patch.stop()
        cls.temp_dir.cleanup()

    def setUp(self):
        init_db()

    def test_health_metadata_is_branded(self):
        payload = health()
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(payload["application"], "Smart Study")

    def test_schema_is_available(self):
        self.assertIsNotNone(row("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"))

    def test_offline_tutor_answers_from_selected_document(self):
        with connect() as con:
            doc_id = con.execute(
                "INSERT INTO documents(title,filename,stored_name,pages,text_content) VALUES(?,?,?,?,?)",
                ("Tutor test", "tutor-test.pdf", "", 1, "Photosynthesis converts light energy into chemical energy in plants."),
            ).lastrowid
            con.execute(
                "INSERT INTO document_chunks(document_id,page_number,content) VALUES(?,?,?)",
                (doc_id, 1, "Photosynthesis converts light energy into chemical energy in plants."),
            )
        try:
            with patch("backend.app.settings", SimpleNamespace(gemini_api_key="", openrouter_api_key="", groq_api_key="")):
                result = chat(ChatRequest(question="What is photosynthesis?", document_id=doc_id))
            self.assertEqual(result["mode"], "offline")
            self.assertIn("chemical energy", result["answer"])
            self.assertEqual(result["sources"][0]["page"], 1)
        finally:
            with connect() as con:
                con.execute("DELETE FROM documents WHERE id=?", (doc_id,))

    def test_openrouter_key_uses_live_provider_path(self):
        fake_settings = SimpleNamespace(gemini_api_key="", openrouter_api_key="test-key", groq_api_key="")
        with patch("backend.app.settings", fake_settings), patch("backend.app.ask", return_value=("Hello from the tutor.", True)):
            result = chat(ChatRequest(question="Explain gravity"))
        self.assertTrue(result["live_ai"])
        self.assertEqual(result["mode"], "openrouter")
        self.assertEqual(result["answer"], "Hello from the tutor.")

    def test_greeting_gets_natural_reply_without_model_call(self):
        with patch("backend.app.ask", side_effect=AssertionError("small talk should be local")):
            result = chat(ChatRequest(question="How are you?"))
        self.assertEqual(result["mode"], "local")
        self.assertIn("What are you studying", result["answer"])

    def test_quiz_generate_submit_and_score(self):
        payload = {"questions": [
            {"question": f"Question {i}?", "options": ["Right", "Wrong A", "Wrong B", "Wrong C"], "answer": 0, "explanation": "Because it is correct."}
            for i in range(3)
        ]}
        with patch("backend.app.ask", return_value=(__import__("json").dumps(payload), True)):
            quiz = generate_quiz(QuizRequest(topic="Loops", count=3))
        try:
            result = submit_quiz(quiz["id"], QuizSubmission(answers=[0, 1, 0]))
            self.assertEqual(result["score"], 2)
            self.assertEqual(result["total"], 3)
            self.assertFalse(result["review"][1]["is_correct"])
        finally:
            with connect() as con:
                con.execute("DELETE FROM quiz_sessions WHERE id=?", (quiz["id"],))


if __name__ == "__main__":
    unittest.main()
