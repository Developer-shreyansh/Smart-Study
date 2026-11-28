"""AI provider integration (Groq, OpenRouter, Gemini) with local fallback."""
from io import BytesIO
import base64
import logging
import re
from backend.config import settings

logger = logging.getLogger(__name__)


def smalltalk_response(prompt: str) -> str | None:
    normalized = re.sub(r"[^a-z ]", " ", prompt.lower())
    normalized = " ".join(normalized.split())
    greetings = {
        "hi", "hello", "hey", "hiya", "howdy", "good morning", "good afternoon",
        "good evening", "how are you", "how are u", "how r u", "how is it going",
        "hows it going", "what is up", "whats up", "are you there",
    }
    if normalized in greetings:
        return "Hi! I’m here and ready to help. What are you studying today?"
    if normalized in {"thanks", "thank you", "thanks a lot", "thx"}:
        return "You’re welcome! What would you like to work on next?"
    if normalized in {"bye", "goodbye", "see you", "see you later"}:
        return "See you later! Good luck with your studies."
    return None


def local_tutor(prompt: str, passages: list[dict]) -> str:
    """Answer from uploaded material without a network service or API credential."""
    greeting = smalltalk_response(prompt)
    if greeting:
        return greeting
    if not passages:
        return ("I can help with your uploaded documents while the AI provider is offline. Choose a document and ask about its contents; "
                "for general questions or image analysis, check that the server can reach your AI provider and that your key and model are valid.")

    question_terms = set(re.findall(r"[a-zA-Z0-9]{3,}", prompt.lower()))
    sentences = []
    for passage in passages:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", passage["content"]):
            sentence = " ".join(sentence.split())
            if len(sentence) >= 35:
                score = sum(term in sentence.lower() for term in question_terms)
                if score:
                    sentences.append((score, sentence))
    sentences.sort(key=lambda item: item[0], reverse=True)
    selected = []
    for _, sentence in sentences:
        if sentence not in selected:
            selected.append(sentence)
        if len(selected) == 4:
            break
    if not selected:
        return ("I couldn’t find a passage that matches this question in the selected document. "
                "Try using a key term from the document or ask about another section. I won’t make up a document-based answer.")
    return "Here are the most relevant passages from your document:\n\n" + "\n\n".join(f"• {s}" for s in selected)


def _prepare_image_for_ai(image_bytes: bytes, image_mime: str) -> tuple[bytes, str]:
    """Downscale overly large images in memory before sending them to AI APIs."""
    try:
        from PIL import Image
        with Image.open(BytesIO(image_bytes)) as img:
            max_dim = max(img.size)
            if max_dim <= 2048 and len(image_bytes) <= 4 * 1024 * 1024:
                return image_bytes, image_mime
            if max_dim > 2048:
                scale = 2048 / max_dim
                new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            out = BytesIO()
            if image_mime == "image/png" and len(image_bytes) <= 4 * 1024 * 1024:
                img.save(out, format="PNG", optimize=True)
                return out.getvalue(), "image/png"
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(out, format="JPEG", quality=88, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, image_mime


def _build_openai_user_content(user_text: str, image_bytes: bytes | None, image_mime: str | None):
    if not image_bytes or not image_mime:
        return user_text
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{encoded}"}},
    ]


def ask(
    prompt: str,
    context: str = "",
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
) -> tuple[str, bool]:
    user_text = (context + "\n\n" if context else "") + prompt
    prepared_bytes, prepared_mime = (
        _prepare_image_for_ai(image_bytes, image_mime)
        if image_bytes and image_mime
        else (None, None)
    )
    has_image = bool(prepared_bytes and prepared_mime)
    vision_unsupported_msg: str | None = None

    if settings.groq_api_key:
        try:
            import requests
            user_content = _build_openai_user_content(user_text, prepared_bytes, prepared_mime)
            groq_models = [settings.groq_model]
            if has_image:
                vision_model = getattr(settings, "groq_vision_model", "meta-llama/llama-4-scout-17b-16e-instruct")
                if vision_model and vision_model not in groq_models:
                    groq_models.append(vision_model)

            for idx, model_name in enumerate(groq_models):
                try:
                    response = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
                        json={"model": model_name, "messages": [
                            {"role": "system", "content": "You are Smart Study, a clear and encouraging study tutor. If document context or an image is supplied, ground your answer in it and say if it does not contain the answer. When asked for code, provide a complete correct solution and explain it briefly."},
                            {"role": "user", "content": user_content},
                        ]}, timeout=45,
                    )
                    response.raise_for_status()
                    answer = response.json()["choices"][0]["message"]["content"]
                    return answer or "I could not generate a response.", True
                except Exception as exc:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if has_image and status in (400, 404, 422) and idx + 1 < len(groq_models):
                        logger.warning("Groq model %s rejected image input (status %s); retrying with %s", model_name, status, groq_models[idx + 1])
                        continue
                    raise
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if has_image and status in (400, 404, 422):
                logger.warning("Groq model rejected multimodal image input (status %s)", status)
                if settings.openrouter_api_key or settings.gemini_api_key:
                    vision_unsupported_msg = "Groq model does not support image input; falling back."
                else:
                    vision_unsupported_msg = (
                        "The configured Groq model does not support image analysis. "
                        "Use a vision-capable model or configure Gemini."
                    )
            else:
                logger.exception("Groq request failed")
                if status == 429:
                    return "Groq’s rate limit or quota was reached. Please wait and try again.", False
                if status in (401, 403):
                    return "Groq rejected the API key. Check that it is active in your Groq account.", False
                if status == 503:
                    return "Groq is temporarily unavailable. Please try again shortly.", False
                return f"Groq could not respond ({type(exc).__name__}). Check the key, model, and connection.", False

    if settings.openrouter_api_key:
        try:
            import requests
            user_content = _build_openai_user_content(user_text, prepared_bytes, prepared_mime)
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json", "X-Title": "Smart Study"},
                json={"model": settings.openrouter_model, "messages": [
                    {"role": "system", "content": "You are Smart Study, a clear and encouraging study tutor. If document context or an image is supplied, ground answers only in it and say when it does not contain the answer."},
                    {"role": "user", "content": user_content},
                ]}, timeout=45,
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            if isinstance(answer, list):
                answer = "\n".join(part.get("text", "") for part in answer if isinstance(part, dict))
            return answer or "I could not generate a response.", True
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if has_image and status in (400, 404, 422):
                logger.warning("OpenRouter model %s rejected multimodal image input (status %s)", settings.openrouter_model, status)
                if settings.gemini_api_key:
                    vision_unsupported_msg = "OpenRouter model does not support image input; falling back."
                else:
                    vision_unsupported_msg = (
                        "The configured OpenRouter model does not support image analysis. "
                        "Use a vision-capable model or configure Gemini."
                    )
            else:
                logger.exception("OpenRouter request failed")
                if status == 429:
                    return "OpenRouter’s free request limit or provider capacity was reached. Please try again later.", False
                if status in (401, 403):
                    return "OpenRouter rejected the key. Check that it is active in your OpenRouter account.", False
                return f"OpenRouter could not respond ({type(exc).__name__}). Check your connection and free-model availability.", False

    if settings.gemini_api_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=settings.gemini_api_key)
            contents = (
                [types.Part.from_bytes(data=prepared_bytes, mime_type=prepared_mime), user_text]
                if has_image
                else user_text
            )
            response = client.models.generate_content(model=settings.gemini_model, contents=contents)
            return response.text or "I could not generate a response.", True
        except Exception as exc:
            logger.exception("Gemini request failed")
            status = getattr(exc, "code", None)
            if status == 503:
                return "Gemini is temporarily overloaded (503). Please try again in a minute. Your key and model were accepted.", False
            if status == 429:
                return "Gemini’s free-tier rate limit was reached. Wait for the quota to reset, or use offline document help for now.", False
            if status in (401, 403):
                return "Gemini rejected the API key. Check that the key is active and belongs to a project with Gemini API access.", False
            if status == 404:
                return f"Gemini could not find model ‘{settings.gemini_model}’. Update GEMINI_MODEL to a model enabled for your account.", False
            return (f"Gemini could not respond ({type(exc).__name__}). Check the API key, model, quota, and server connection. "
                    "Offline document help is available below."), False

    if vision_unsupported_msg:
        return vision_unsupported_msg, False
    return local_tutor(prompt, []) if not context else (context, False)


def extract_image_text(image_bytes: bytes, image_mime: str) -> tuple[str, bool]:
    """Use the configured vision AI provider to extract readable text and study notes from an image."""
    prompt = (
        "Extract all readable text, headings, formulas, and equations from this study image accurately. "
        "If the image contains diagrams, charts, tables, or handwritten notes, include a concise, clear "
        "description of those visual elements so a student can search, study, and generate quizzes from it. "
        "Return plain readable text without markdown code fences."
    )
    return ask(prompt, image_bytes=image_bytes, image_mime=image_mime)
