// Quiz Center and planner refinements, loaded after the shared application shell.
const focusStyles = document.createElement("link"); focusStyles.rel = "stylesheet"; focusStyles.href = "/assets/css/focus.css"; document.head.append(focusStyles);
const aestheticStyles = document.createElement("link"); aestheticStyles.rel = "stylesheet"; aestheticStyles.href = "/assets/css/aesthetic.css"; document.head.append(aestheticStyles);
const focusApi = async (url, options = {}) => {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Something went wrong.");
  return data;
};
const focusEsc = value => String(value ?? "").replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const focusToast = message => { const node = document.querySelector("#toast"); node.textContent = message; node.style.display = "block"; setTimeout(() => node.style.display = "none", 2800); };
focusApi("/api/health").then(status => {
  if (status.ai_provider) {
    document.querySelector("#ai-pill").textContent = `${status.ai_provider} connected`;
    document.querySelector("#ai-status").textContent = `${status.ai_provider} is configured. Local greetings and PDF help remain available as fallbacks.`;
  }
}).catch(() => {});

document.querySelector('[data-page="flashcards"]')?.remove();
document.querySelector("#flashcards")?.remove();
document.querySelector("#tutor .muted").textContent = "Ask about your PDFs locally, or use the configured AI provider for broader questions.";
document.querySelector("#tutor .kicker").textContent = "AI TUTOR · READY";
document.querySelector("#chat .message.assistant").textContent = "Hi! I can help with general study questions or find answers in your uploaded PDFs. What would you like to work on?";
document.querySelector("#settings .muted").textContent = "AI provider keys stay on your server. Offline document help and the study planner work without an AI key.";

const quizSection = document.querySelector("#quiz");
quizSection.innerHTML = `
  <div class="section-head"><div><p class="kicker">PRACTICE & RETAIN</p><h2>Quiz Center</h2><p class="muted">Build a quick practice set from a topic or one of your PDFs.</p></div></div>
  <div class="quiz-layout"><article class="quiz-builder"><p class="kicker">NEW PRACTICE SET</p><form id="quiz-form">
    <label>Topic <input id="quiz-topic" maxlength="200" placeholder="e.g. loops in Python"></label>
    <div class="or-divider">or choose a document</div><label>Study document <select id="quiz-document"><option value="">No document selected</option></select></label>
    <div class="quiz-fields"><label>Questions <select id="quiz-count"><option>5</option><option>3</option><option>8</option><option>10</option></select></label><label>Difficulty <select id="quiz-difficulty"><option>Medium</option><option>Easy</option><option>Hard</option></select></label></div>
    <button class="primary" id="quiz-generate">Generate quiz <span>→</span></button><p class="muted tiny">AI generated · Your score is saved in this app.</p>
  </form></article><div class="quiz-main"><div id="quiz-work" class="quiz-work empty-state"><span class="quiet-icon">✳</span><h3>Your next study session starts here.</h3><p>Generate a quiz to practice, then review explanations for each answer.</p></div>
  <article class="quiz-history"><h3>Recent attempts</h3><div id="quiz-history-list" class="muted">Loading quiz history…</div></article></div></div>`;

async function fillQuizDocuments() {
  const docs = await focusApi("/api/documents");
  document.querySelector("#quiz-document").innerHTML = '<option value="">No document selected</option>' + docs.map(d => `<option value="${d.id}">${focusEsc(d.title)}</option>`).join("");
}
async function loadQuizHistory() {
  const history = await focusApi("/api/quizzes");
  const node = document.querySelector("#quiz-history-list");
  node.className = history.length ? "history-list" : "muted";
  node.innerHTML = history.length ? history.map(q => `<div class="history-item"><span><b>${focusEsc(q.title)}</b><small>${new Date(q.created_at + "Z").toLocaleDateString()}</small></span><strong>${q.score == null ? "Not submitted" : `${q.score}/${q.total}`}</strong></div>`).join("") : "No attempts yet. Your completed quizzes will appear here.";
}
let activeQuiz = null;
function showQuiz(quiz) {
  activeQuiz = quiz;
  document.querySelector("#quiz-work").className = "quiz-work";
  document.querySelector("#quiz-work").innerHTML = `<div class="quiz-topline"><span>${focusEsc(quiz.difficulty || "Practice")}</span><span>${quiz.questions.length} questions</span></div><form id="quiz-answer-form"><div class="question-list">${quiz.questions.map((q, i) => `<fieldset class="question-card"><legend><span class="question-number">${String(i + 1).padStart(2, "0")}</span>${focusEsc(q.question)}</legend><div class="answer-options">${q.options.map((option, j) => `<label class="answer-option"><input type="radio" name="answer-${i}" value="${j}" required><span>${focusEsc(option)}</span></label>`).join("")}</div></fieldset>`).join("")}</div><button class="primary submit-quiz">Submit answers <span>→</span></button></form>`;
  document.querySelector("#quiz-answer-form").onsubmit = async event => {
    event.preventDefault();
    const answers = quiz.questions.map((_, i) => Number(new FormData(event.target).get(`answer-${i}`)));
    const result = await focusApi(`/api/quizzes/${quiz.id}/submit`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({answers})});
    showQuizResult(result); loadQuizHistory();
  };
}
function showQuizResult(result) {
  activeQuiz = null;
  const percent = Math.round(result.score / result.total * 100);
  document.querySelector("#quiz-work").innerHTML = `<div class="result-head"><div class="score-ring"><b>${percent}%</b></div><div><p class="kicker">QUIZ COMPLETE</p><h3>${result.score} of ${result.total} correct</h3><p class="muted">${percent >= 80 ? "Strong work. Keep building on it." : "Review the explanations below, then try another set."}</p></div></div><div class="review-list">${result.review.map((q, i) => `<article class="review-card ${q.is_correct ? "correct" : "incorrect"}"><b>${String(i + 1).padStart(2, "0")} &nbsp;${focusEsc(q.question)}</b><p class="muted">Your answer: ${focusEsc(q.options[q.selected])}${q.is_correct ? " · Correct" : `<br>Correct answer: ${focusEsc(q.options[q.correct])}`}</p><p>${focusEsc(q.explanation)}</p></article>`).join("")}</div><button class="primary" id="new-quiz">Create another quiz</button>`;
  document.querySelector("#new-quiz").onclick = () => document.querySelector("#quiz-topic").focus();
}
document.querySelector("#quiz-form").onsubmit = async event => {
  event.preventDefault();
  const button = document.querySelector("#quiz-generate"); button.disabled = true; button.textContent = "Building your quiz…";
  try {
    const docId = document.querySelector("#quiz-document").value;
    const topic = document.querySelector("#quiz-topic").value.trim();
    if (!topic && !docId) throw new Error("Enter a topic or choose a document.");
    const quiz = await focusApi("/api/quizzes/generate", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({topic, document_id:docId ? Number(docId) : null, count:Number(document.querySelector("#quiz-count").value), difficulty:document.querySelector("#quiz-difficulty").value})});
    showQuiz(quiz);
  } catch (error) { focusToast(error.message); }
  finally { button.disabled = false; button.innerHTML = 'Generate quiz <span>→</span>'; }
};

const plannerSection = document.querySelector("#planner");
plannerSection.querySelector(".section-head").insertAdjacentHTML("afterend", `<div id="planner-overview" class="planner-overview"></div><div class="planner-toolbar"><div><b>Your plan</b><span id="planner-caption" class="muted">Keep the next step small and clear.</span></div><div class="planner-filters"><button class="filter active" data-filter="open">Upcoming</button><button class="filter" data-filter="all">All tasks</button><button class="filter" data-filter="done">Completed</button></div></div>`);
let currentFilter = "open";
async function renderPlanner() {
  const items = await focusApi("/api/tasks");
  const complete = items.filter(t => t.completed).length, open = items.length - complete;
  const overdue = items.filter(t => !t.completed && t.due_date && t.due_date < new Date().toISOString().slice(0,10)).length;
  document.querySelector("#planner-overview").innerHTML = `<article class="planner-stat"><span>Open tasks</span><b>${open}</b></article><article class="planner-stat"><span>Completed</span><b>${complete}</b></article><article class="planner-stat"><span>Past due</span><b>${overdue}</b></article><article class="planner-progress"><div><span>Overall progress</span><b>${items.length ? Math.round(complete/items.length*100) : 0}%</b></div><div class="progress-track"><i style="width:${items.length ? complete/items.length*100 : 0}%"></i></div></article>`;
  const shown = items.filter(t => currentFilter === "all" || (currentFilter === "done" ? t.completed : !t.completed));
  const list = document.querySelector("#task-list"); list.className = "planner-list";
  list.innerHTML = shown.length ? shown.map(t => `<article class="planner-task ${t.completed ? "task-done" : ""}"><input class="task-check" type="checkbox" data-id="${t.id}" ${t.completed ? "checked" : ""} aria-label="Mark ${focusEsc(t.title)} complete"><div class="task-info"><b>${focusEsc(t.title)}</b><small>${focusEsc(t.subject || "General study")}${t.due_date ? ` · ${focusEsc(t.due_date)}` : " · No due date"}</small></div><span class="priority priority-${t.priority.toLowerCase()}">${focusEsc(t.priority)}</span><button class="task-delete" data-delete="${t.id}" aria-label="Delete ${focusEsc(t.title)}">×</button></article>`).join("") : `<div class="empty-state">${currentFilter === "done" ? "No completed tasks yet." : "Nothing scheduled here. Add a task above."}</div>`;
  list.querySelectorAll(".task-check").forEach(input => input.onchange = async () => { await focusApi(`/api/tasks/${input.dataset.id}/toggle`, {method:"PATCH"}); renderPlanner(); });
  list.querySelectorAll("[data-delete]").forEach(button => button.onclick = async () => { await focusApi(`/api/tasks/${button.dataset.delete}`, {method:"DELETE"}); renderPlanner(); focusToast("Task removed."); });
}
window.tasks = renderPlanner;
document.querySelectorAll(".filter").forEach(button => button.onclick = () => { currentFilter = button.dataset.filter; document.querySelectorAll(".filter").forEach(b => b.classList.toggle("active", b === button)); renderPlanner(); });
document.querySelector("#task-form").onsubmit = async event => {
  event.preventDefault();
  try {
    await focusApi("/api/tasks", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({title:document.querySelector("#task-title").value.trim(),subject:document.querySelector("#task-subject").value.trim(),due_date:document.querySelector("#task-date").value,priority:document.querySelector("#task-priority").value})});
    event.target.reset(); currentFilter="open"; document.querySelectorAll(".filter").forEach(b => b.classList.toggle("active",b.dataset.filter==="open")); renderPlanner(); focusToast("Task added to your plan.");
  } catch (error) { focusToast(error.message); }
};
fillQuizDocuments().catch(() => {}); loadQuizHistory().catch(() => {}); renderPlanner().catch(() => {});
