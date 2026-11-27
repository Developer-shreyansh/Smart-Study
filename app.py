from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from uuid import uuid4
import fitz
import re
import json
from typing import Literal
from backend.config import settings, ROOT
from backend.database import init_db, connect, rows, row
from backend.services.ai import ask, local_tutor, smalltalk_response

app = FastAPI(title="Smart Study", version="1.0.0", description="AI-powered study assistant API")
app.mount("/assets", StaticFiles(directory=ROOT / "frontend" / "assets"), name="assets")

@app.on_event("startup")
def startup(): init_db()

@app.get("/")
def home(): return FileResponse(ROOT / "frontend" / "index.html")

@app.get("/manifest.webmanifest")
def manifest(): return FileResponse(ROOT / "frontend" / "manifest.webmanifest", media_type="application/manifest+json")

@app.get("/service-worker.js")
def service_worker():
    return FileResponse(ROOT / "frontend" / "service-worker.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})

@app.get("/api/health")
def health():
    provider="Groq" if settings.groq_api_key else "OpenRouter" if settings.openrouter_api_key else "Gemini" if settings.gemini_api_key else None
    return {"status":"healthy", "application":"Smart Study", "ai_configured":bool(provider), "ai_provider":provider}

@app.get("/api/dashboard")
def dashboard():
    return {"documents": row("SELECT count(*) n FROM documents")["n"], "quizzes":row("SELECT count(*) n FROM quiz_sessions")["n"], "flashcards":row("SELECT count(*) n FROM flashcards")["n"], "tasks":row("SELECT count(*) n FROM study_tasks WHERE completed=0")["n"], "recent_documents":rows("SELECT id,title,pages,created_at FROM documents ORDER BY id DESC LIMIT 5"), "tasks_list":rows("SELECT * FROM study_tasks WHERE completed=0 ORDER BY due_date IS NULL,due_date LIMIT 5")}

@app.get("/api/documents")
def documents(q: str = ""): return rows("SELECT id,title,pages,created_at FROM documents WHERE title LIKE ? ORDER BY id DESC", (f"%{q}%",))

@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf": raise HTTPException(400, "Please upload a PDF file.")
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024: raise HTTPException(400, f"PDF exceeds {settings.max_upload_mb} MB limit.")
    stored = f"{uuid4().hex}.pdf"; path = settings.data_dir / "uploads" / stored; path.write_bytes(content)
    try:
        pdf = fitz.open(stream=content, filetype="pdf")
        page_text = [(i + 1, p.get_text()) for i,p in enumerate(pdf)]; pdf.close()
    except Exception:
        path.unlink(missing_ok=True); raise HTTPException(400, "This PDF could not be read.")
    title = Path(file.filename).stem
    with connect() as con:
        cur=con.execute("INSERT INTO documents(title,filename,stored_name,pages,text_content) VALUES(?,?,?,?,?)",(title,file.filename,stored,len(page_text),"\n".join(t for _,t in page_text)))
        did=cur.lastrowid
        for pg,text in page_text:
            for chunk in [text[i:i+1200] for i in range(0,len(text),1200) if text[i:i+1200].strip()]: con.execute("INSERT INTO document_chunks(document_id,page_number,content) VALUES(?,?,?)",(did,pg,chunk))
    return {"id":did,"title":title,"pages":len(page_text)}

@app.get("/api/documents/{document_id}")
def document(document_id:int):
    item=row("SELECT id,title,pages,text_content,created_at FROM documents WHERE id=?",(document_id,))
    if not item: raise HTTPException(404,"Document not found")
    return item

@app.delete("/api/documents/{document_id}")
def delete_document(document_id:int):
    item=row("SELECT stored_name FROM documents WHERE id=?",(document_id,))
    if not item: raise HTTPException(404,"Document not found")
    (settings.data_dir / "uploads" / item["stored_name"]).unlink(missing_ok=True)
    with connect() as con: con.execute("DELETE FROM documents WHERE id=?",(document_id,))
    return {"ok":True}

class ChatRequest(BaseModel): question:str=Field(min_length=1,max_length=4000); document_id:int|None=None; conversation_id:int|None=None
@app.post("/api/chat")
def chat(req:ChatRequest):
    context=""; sources=[]; relevant=[]
    if req.document_id:
        doc=row("SELECT title FROM documents WHERE id=?",(req.document_id,))
        if not doc: raise HTTPException(404,"Document not found")
        terms=set(re.findall(r"[a-zA-Z0-9]{3,}",req.question.lower()))
        candidates=rows("SELECT content,page_number FROM document_chunks WHERE document_id=?",(req.document_id,))
        ranked=sorted(((sum(1 for term in terms if term in chunk["content"].lower()),chunk) for chunk in candidates),key=lambda item:item[0],reverse=True)
        relevant=[chunk for score,chunk in ranked[:4] if score>0]
        if relevant:
            context="Use only this document context and say if insufficient:\n"+"\n".join(x["content"] for x in relevant)
            sources=[{"document":doc["title"],"page":x["page_number"]} for x in relevant]
        else:
            context="No relevant passages were found in the selected document. Tell the user the document search could not find an answer; do not answer from general knowledge."
    with connect() as con:
        cid=req.conversation_id
        if not cid: cid=con.execute("INSERT INTO conversations(title) VALUES(?)",(req.question[:60],)).lastrowid
        con.execute("INSERT INTO chat_messages(conversation_id,role,content) VALUES(?,?,?)",(cid,"user",req.question))
        greeting=smalltalk_response(req.question)
        if greeting:
            answer,live=greeting,False
        elif settings.gemini_api_key or settings.openrouter_api_key or settings.groq_api_key:
            answer,live=ask(req.question,context)
            if not live:
                answer += "\n\n" + local_tutor(req.question,relevant)
        else:
            answer,live=(local_tutor(req.question,relevant) if relevant or not req.document_id else
                         "I couldn’t find a passage that matches this question in the selected document. Try a key term from the PDF or ask about another section. I won’t make up a document-based answer."),False
        con.execute("INSERT INTO chat_messages(conversation_id,role,content,sources) VALUES(?,?,?,?)",(cid,"assistant",answer,str(sources)))
    provider="local" if greeting else "groq" if settings.groq_api_key else "openrouter" if settings.openrouter_api_key else "gemini"
    return {"conversation_id":cid,"answer":answer,"sources":sources,"live_ai":live,"mode":provider if live or greeting else "offline"}

class QuizRequest(BaseModel):
    topic: str = Field(default="", max_length=200)
    document_id: int | None = None
    count: int = Field(default=5, ge=3, le=10)
    difficulty: Literal["Easy", "Medium", "Hard"] = "Medium"

@app.post("/api/quizzes/generate")
def generate_quiz(req: QuizRequest):
    title = req.topic.strip()
    context = ""
    if req.document_id:
        doc = row("SELECT title,text_content FROM documents WHERE id=?", (req.document_id,))
        if not doc: raise HTTPException(404, "Document not found")
        title = doc["title"]
        context = "Create questions grounded only in this source. Do not invent unsupported facts.\n" + doc["text_content"][:18000]
    elif not title:
        raise HTTPException(400, "Enter a topic or choose a document.")
    prompt = (
        f"Create exactly {req.count} {req.difficulty.lower()} multiple-choice study questions about {title}. "
        "Return only valid JSON with this schema: {\"questions\":[{\"question\":string,\"options\":[string,string,string,string],\"answer\":integer from 0 to 3,\"explanation\":string}]}. "
        "Each question must have one unambiguous correct answer and useful distractors."
    )
    generated, live = ask(prompt, context)
    if not live: raise HTTPException(503, generated)
    try:
        cleaned = generated.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
        questions = json.loads(cleaned)["questions"]
        if len(questions) != req.count: raise ValueError("wrong question count")
        for question in questions:
            if (not isinstance(question.get("question"), str) or len(question.get("options", [])) != 4
                    or not isinstance(question.get("answer"), int) or question["answer"] not in range(4)):
                raise ValueError("invalid question structure")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(502, "The AI returned an invalid quiz. Please try generating it again.")
    with connect() as con:
        session_id = con.execute("INSERT INTO quiz_sessions(title,total) VALUES(?,?)", (title, len(questions))).lastrowid
        for position, question in enumerate(questions, 1):
            con.execute("INSERT INTO quiz_questions(session_id,position,prompt,options_json,correct_index,explanation) VALUES(?,?,?,?,?,?)",
                        (session_id, position, question["question"], json.dumps(question["options"]), question["answer"], question.get("explanation", "")))
    return {"id": session_id, "title": title, "difficulty": req.difficulty,
            "questions": [{"position": i, "question": q["question"], "options": q["options"]} for i, q in enumerate(questions, 1)]}

class QuizSubmission(BaseModel): answers: list[int]

@app.post("/api/quizzes/{session_id}/submit")
def submit_quiz(session_id: int, submission: QuizSubmission):
    questions = rows("SELECT id,position,prompt,options_json,correct_index,explanation FROM quiz_questions WHERE session_id=? ORDER BY position", (session_id,))
    if not questions: raise HTTPException(404, "Quiz not found")
    session = row("SELECT score FROM quiz_sessions WHERE id=?", (session_id,))
    if session["score"] is not None: raise HTTPException(409, "This quiz has already been submitted.")
    if len(submission.answers) != len(questions) or any(a not in range(4) for a in submission.answers):
        raise HTTPException(400, "Please answer every question before submitting.")
    review=[]; score=0
    with connect() as con:
        for q, selected in zip(questions, submission.answers):
            correct = selected == q["correct_index"]; score += int(correct)
            con.execute("INSERT INTO quiz_answers(question_id,selected_index,is_correct) VALUES(?,?,?)", (q["id"], selected, int(correct)))
            options=json.loads(q["options_json"])
            review.append({"question":q["prompt"],"options":options,"selected":selected,"correct":q["correct_index"],"is_correct":correct,"explanation":q["explanation"]})
        con.execute("UPDATE quiz_sessions SET score=? WHERE id=?", (score, session_id))
    return {"score":score,"total":len(questions),"review":review}

@app.get("/api/quizzes")
def quiz_history():
    return rows("SELECT id,title,score,total,created_at FROM quiz_sessions ORDER BY id DESC LIMIT 20")

class Task(BaseModel): title:str=Field(min_length=1,max_length=200); subject:str=""; due_date:str=""; priority:str="Medium"
@app.get("/api/tasks")
def tasks(): return rows("SELECT * FROM study_tasks ORDER BY completed,due_date IS NULL,due_date")
@app.post("/api/tasks")
def add_task(task:Task):
    with connect() as con: ident=con.execute("INSERT INTO study_tasks(title,subject,due_date,priority) VALUES(?,?,?,?)",(task.title,task.subject,task.due_date or None,task.priority)).lastrowid
    return {"id":ident}
@app.patch("/api/tasks/{task_id}/toggle")
def toggle(task_id:int):
    with connect() as con:
        cur=con.execute("UPDATE study_tasks SET completed=1-completed WHERE id=?",(task_id,))
        if cur.rowcount==0: raise HTTPException(404,"Task not found")
    return {"ok":True}

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id:int):
    with connect() as con:
        cur=con.execute("DELETE FROM study_tasks WHERE id=?",(task_id,))
        if cur.rowcount==0: raise HTTPException(404,"Task not found")
    return {"ok":True}
