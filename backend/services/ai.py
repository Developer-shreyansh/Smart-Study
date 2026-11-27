"""Gemini integration with an explicit local fallback when not configured."""
from backend.config import settings
import re
import logging

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
        return ("I can help with your uploaded PDFs while Gemini is offline. Choose a document and ask about its contents; "
                "for general questions, check that the server can reach Gemini and that your key and model are valid.")

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
                "Try using a key term from the PDF or ask about another section. I won’t make up a document-based answer.")
    return "Here are the most relevant passages from your document:\n\n" + "\n\n".join(f"• {s}" for s in selected)

def ask(prompt: str, context: str = "") -> tuple[str, bool]:
    if settings.groq_api_key:
        try:
            import requests
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
                json={"model": settings.groq_model, "messages": [
                    {"role": "system", "content": "You are Smart Study, a clear and encouraging study tutor. If document context is supplied, ground your answer in it and say if it does not contain the answer. When asked for code, provide a complete correct solution and explain it briefly."},
                    {"role": "user", "content": (context + "\n\n" if context else "") + prompt},
                ]}, timeout=45,
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            return answer or "I could not generate a response.", True
        except Exception as exc:
            logger.exception("Groq request failed")
            status = getattr(getattr(exc, "response", None), "status_code", None)
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
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json", "X-Title": "Smart Study"},
                json={"model": settings.openrouter_model, "messages": [
                    {"role": "system", "content": "You are Smart Study, a clear and encouraging study tutor. If document context is supplied, ground answers only in it and say when it does not contain the answer."},
                    {"role": "user", "content": (context + "\n\n" if context else "") + prompt},
                ]}, timeout=45,
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            if isinstance(answer, list): answer = "\n".join(part.get("text", "") for part in answer if isinstance(part, dict))
            return answer or "I could not generate a response.", True
        except Exception as exc:
            logger.exception("OpenRouter request failed")
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                return "OpenRouter’s free request limit or provider capacity was reached. Please try again later.", False
            if status in (401, 403):
                return "OpenRouter rejected the key. Check that it is active in your OpenRouter account.", False
            return f"OpenRouter could not respond ({type(exc).__name__}). Check your connection and free-model availability.", False
    if settings.gemini_api_key:
        try:
            from google import genai
            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(model=settings.gemini_model, contents=(context + "\n\n" if context else "") + prompt)
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
    return local_tutor(prompt, []) if not context else (context, False)
