import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import (
    ChatRequest,
    QuizRequest,
    QuizSubmission,
    app,
    chat,
    generate_quiz,
    health,
    submit_quiz,
)
from backend.database import connect, init_db, row
from backend.services.ai import ask as ai_ask


def _make_image_bytes(fmt: str = "PNG", size: tuple[int, int] = (40, 20), orientation: int | None = None) -> bytes:
    img = Image.new("RGB", size, color=(35, 118, 81))
    buf = io.BytesIO()
    if orientation and fmt == "JPEG":
        exif = img.getexif()
        exif[274] = orientation
        img.save(buf, format=fmt, exif=exif)
    else:
        img.save(buf, format=fmt)
    return buf.getvalue()


class SmartStudyCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = TemporaryDirectory()
        cls.temp_path = Path(cls.temp_dir.name)
        (cls.temp_path / "uploads").mkdir(parents=True, exist_ok=True)
        (cls.temp_path / "database").mkdir(parents=True, exist_ok=True)
        cls.db_path_patch = patch("backend.database.DB_PATH", cls.temp_path / "database" / "tests.sqlite3")
        cls.db_path_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.db_path_patch.stop()
        cls.temp_dir.cleanup()

    def setUp(self):
        init_db()

    def _fake_settings(self, **overrides):
        base = dict(
            max_upload_mb=15,
            gemini_api_key="",
            openrouter_api_key="",
            groq_api_key="",
            gemini_model="gemini-3.8-flash",
            openrouter_model="openrouter/free",
            groq_model="openai/gpt-oss-20b",
            data_dir=self.temp_path,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

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
            with patch("backend.app.settings", self._fake_settings()):
                result = chat(ChatRequest(question="What is photosynthesis?", document_id=doc_id))
            self.assertEqual(result["mode"], "offline")
            self.assertIn("chemical energy", result["answer"])
            self.assertEqual(result["sources"][0]["page"], 1)
        finally:
            with connect() as con:
                con.execute("DELETE FROM documents WHERE id=?", (doc_id,))

    def test_openrouter_key_uses_live_provider_path(self):
        fake_settings = self._fake_settings(openrouter_api_key="test-key")
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
        with patch("backend.app.ask", return_value=(json.dumps(payload), True)):
            quiz = generate_quiz(QuizRequest(topic="Loops", count=3))
        try:
            result = submit_quiz(quiz["id"], QuizSubmission(answers=[0, 1, 0]))
            self.assertEqual(result["score"], 2)
            self.assertEqual(result["total"], 3)
            self.assertFalse(result["review"][1]["is_correct"])
        finally:
            with connect() as con:
                con.execute("DELETE FROM quiz_sessions WHERE id=?", (quiz["id"],))

    def test_upload_serve_and_delete_png_image(self):
        fake_settings = self._fake_settings(gemini_api_key="test-gemini")
        png_bytes = _make_image_bytes("PNG")
        with patch("backend.app.settings", fake_settings), patch(
            "backend.app.extract_image_text", return_value=("Cell membrane diagram notes.", True)
        ):
            client = TestClient(app)
            upload_res = client.post(
                "/api/documents",
                files={"file": ("biology_notes.png", png_bytes, "image/png")},
            )
            self.assertEqual(upload_res.status_code, 200)
            uploaded = upload_res.json()
            doc_id = uploaded["id"]
            self.assertEqual(uploaded["file_type"], "image")
            self.assertEqual(uploaded["pages"], 1)

            list_res = client.get("/api/documents")
            self.assertEqual(list_res.status_code, 200)
            self.assertEqual(list_res.json()[0]["file_type"], "image")

            detail_res = client.get(f"/api/documents/{doc_id}")
            self.assertEqual(detail_res.status_code, 200)
            self.assertEqual(detail_res.json()["file_type"], "image")
            self.assertIn("Cell membrane diagram", detail_res.json()["text_content"])

            file_res = client.get(f"/api/documents/{doc_id}/file")
            self.assertEqual(file_res.status_code, 200)
            self.assertEqual(file_res.headers["content-type"], "image/png")

            del_res = client.delete(f"/api/documents/{doc_id}")
            self.assertEqual(del_res.status_code, 200)
            self.assertEqual(client.get(f"/api/documents/{doc_id}/file").status_code, 404)

    def test_upload_jpg_normalizes_exif_orientation(self):
        fake_settings = self._fake_settings()
        jpg_bytes = _make_image_bytes("JPEG", size=(60, 20), orientation=6)
        with patch("backend.app.settings", fake_settings):
            client = TestClient(app)
            res = client.post(
                "/api/documents",
                files={"file": ("phone_photo.JPG", jpg_bytes, "image/jpeg")},
            )
            self.assertEqual(res.status_code, 200)
            doc_id = res.json()["id"]
            try:
                file_res = client.get(f"/api/documents/{doc_id}/file")
                self.assertEqual(file_res.status_code, 200)
                self.assertEqual(file_res.headers["content-type"], "image/jpeg")
                with Image.open(io.BytesIO(file_res.content)) as saved_img:
                    self.assertEqual(saved_img.size, (20, 60))
            finally:
                client.delete(f"/api/documents/{doc_id}")

    def test_upload_rejects_invalid_and_unsupported_files(self):
        with patch("backend.app.settings", self._fake_settings()):
            client = TestClient(app)
            bad_ext = client.post("/api/documents", files={"file": ("notes.txt", b"hello", "text/plain")})
            self.assertEqual(bad_ext.status_code, 400)
            spoofed_png = client.post("/api/documents", files={"file": ("fake.png", b"not actually a png", "image/png")})
            self.assertEqual(spoofed_png.status_code, 400)

    def test_chat_and_quiz_pass_image_to_vision_ai(self):
        fake_settings = self._fake_settings(gemini_api_key="test-gemini")
        png_bytes = _make_image_bytes("PNG")
        with patch("backend.app.settings", fake_settings), patch(
            "backend.app.extract_image_text", return_value=("Newton second law F = ma", True)
        ):
            client = TestClient(app)
            doc_id = client.post("/api/documents", files={"file": ("physics.png", png_bytes, "image/png")}).json()["id"]

        try:
            with patch("backend.app.settings", fake_settings), patch(
                "backend.app.ask", return_value=("This diagram shows F = ma.", True)
            ) as mock_ask:
                chat_res = chat(ChatRequest(question="Explain this diagram", document_id=doc_id))
            self.assertTrue(chat_res["live_ai"])
            self.assertEqual(chat_res["sources"], [{"document": "physics", "page": 1}])
            self.assertEqual(mock_ask.call_args.kwargs["image_mime"], "image/png")
            self.assertTrue(len(mock_ask.call_args.kwargs["image_bytes"]) > 0)

            quiz_payload = {"questions": [
                {"question": f"Physics Q{i}?", "options": ["F=ma", "F=mv", "F=m/a", "F=a"], "answer": 0, "explanation": "Second law."}
                for i in range(3)
            ]}
            with patch("backend.app.settings", fake_settings), patch(
                "backend.app.ask", return_value=(json.dumps(quiz_payload), True)
            ) as mock_quiz_ask:
                quiz = generate_quiz(QuizRequest(document_id=doc_id, count=3))
            self.assertEqual(len(quiz["questions"]), 3)
            self.assertEqual(mock_quiz_ask.call_args.kwargs["image_mime"], "image/png")
            with connect() as con:
                con.execute("DELETE FROM quiz_sessions WHERE id=?", (quiz["id"],))
        finally:
            with patch("backend.app.settings", fake_settings):
                TestClient(app).delete(f"/api/documents/{doc_id}")

    def test_gemini_vision_part_is_sent_when_image_provided(self):
        fake_settings = self._fake_settings(gemini_api_key="test-gemini")
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = SimpleNamespace(text="Diagram explained.")
        png_bytes = _make_image_bytes("PNG")
        with patch("backend.services.ai.settings", fake_settings), patch("google.genai.Client", return_value=fake_client):
            answer, live = ai_ask("What is this?", "Analyze image", image_bytes=png_bytes, image_mime="image/png")
        self.assertTrue(live)
        self.assertEqual(answer, "Diagram explained.")
        sent_contents = fake_client.models.generate_content.call_args.kwargs["contents"]
        self.assertIsInstance(sent_contents, list)
        self.assertEqual(len(sent_contents), 2)

    def test_groq_falls_back_to_vision_model_for_images(self):
        import requests as req_lib
        fake_settings = self._fake_settings(groq_api_key="gsk_test", groq_vision_model="meta-llama/llama-4-scout-17b-16e-instruct")
        png_bytes = _make_image_bytes("PNG")
        bad_resp = SimpleNamespace(status_code=400)
        http_err = req_lib.HTTPError("model does not support images", response=bad_resp)
        first = MagicMock()
        first.raise_for_status.side_effect = http_err
        second = MagicMock()
        second.raise_for_status.return_value = None
        second.json.return_value = {"choices": [{"message": {"content": "Groq vision read the image."}}]}

        with patch("backend.services.ai.settings", fake_settings), patch("requests.post", side_effect=[first, second]) as mock_post:
            answer, live = ai_ask("Explain this image", image_bytes=png_bytes, image_mime="image/png")
        self.assertTrue(live)
        self.assertEqual(answer, "Groq vision read the image.")
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["model"], "meta-llama/llama-4-scout-17b-16e-instruct")

    def test_pdf_upload_read_and_delete_still_works(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Mitosis divides a cell into two identical daughter cells.")
        pdf_bytes = doc.tobytes()
        doc.close()

        with patch("backend.app.settings", self._fake_settings()):
            client = TestClient(app)
            up = client.post("/api/documents", files={"file": ("mitosis.pdf", pdf_bytes, "application/pdf")})
            self.assertEqual(up.status_code, 200)
            payload = up.json()
            self.assertEqual(payload["file_type"], "pdf")
            self.assertEqual(payload["pages"], 1)
            doc_id = payload["id"]
            try:
                detail = client.get(f"/api/documents/{doc_id}")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["file_type"], "pdf")
                self.assertIn("Mitosis", detail.json()["text_content"])
            finally:
                client.delete(f"/api/documents/{doc_id}")


if __name__ == "__main__":
    unittest.main()
