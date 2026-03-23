import secrets

SECRET_KEY = secrets.token_hex(32)

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from rapidfuzz import fuzz

import json
import os
import random
from typing import List, Dict, Any


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

if not SECRET_KEY:
    raise ValueError("SECRET_KEY not set in environment")

app = FastAPI()

# ---------------------
# GLOBAL CONTROL
# ---------------------
chatbot_active = True   # 🔥 ADMIN CONTROL

# ---------------------
# TEMPLATES
# ---------------------
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory="templates")

# ---------------------
# STATIC FILES
# ---------------------
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------
# DATABASE
# ---------------------
def get_db():
    conn = sqlite3.connect("chatbot.db")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        sender TEXT,
        message TEXT,
        time TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()


from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# ---------------------
# LOAD INTENTS
# ---------------------
intents: List[Dict[str, Any]] = []

def load_intents():
    global intents
    try:
        if os.path.exists("intents.json") and os.path.getsize("intents.json") > 0:
            with open("intents.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                intents = [i for i in data if isinstance(i, dict)] #type: ignore
    except Exception as e:
        print("Error loading intents:", e)

load_intents()

# ---------------------
# AI RESPONSE
# ---------------------
def get_response(user_msg: str) -> str:
    user_msg = user_msg.lower().strip()

    best_score = 0
    best_responses = []

    for intent in intents:
        patterns = intent.get("patterns", [])
        responses = intent.get("responses", [])

        for pattern in patterns:
            pattern = pattern.lower()

            if user_msg == pattern:
                return random.choice(responses)

            if user_msg in pattern or pattern in user_msg:
                return random.choice(responses)

            score = fuzz.token_sort_ratio(user_msg, pattern)

            if score > best_score:
                best_score = score
                best_responses = responses

    if best_score > 60 and best_responses:
        return random.choice(best_responses) #type: ignore

    return "Ask me something about AI 😊"

# ---------------------
# HOME
# ---------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse("/login")

# ---------------------
# ADMIN PANEL
# ---------------------
@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    request.session["user"] = username
    user = request.session.get("user")
    request.session.clear()

    if user != "admin":
        return RedirectResponse("/login")

    conn = get_db()
    cursor = conn.cursor()

    # 🔥 USER ANALYTICS
    cursor.execute("""
    SELECT users.rowid, users.username, COUNT(chat_history.id)
    FROM users
    LEFT JOIN chat_history ON users.username = chat_history.username
    GROUP BY users.username
    """)
    users = cursor.fetchall()

    cursor.execute("SELECT id, username, sender, message, time FROM chat_history ORDER BY id DESC")
    chats = cursor.fetchall()

    conn.close()

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "users": users,
        "chats": chats,
        "bot_status": chatbot_active
    })

# ---------------------
# TOGGLE CHATBOT
# ---------------------
@app.get("/toggle_bot")
def toggle_bot(request: Request):
    global chatbot_active

    user = request.cookies.get("user")
    if user != "admin":
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    chatbot_active = not chatbot_active
    return {"status": chatbot_active}

# ---------------------
# INTENT API
# ---------------------
@app.get("/get_intents")
def get_intents():
    return intents

@app.post("/update_intents")
async def update_intents(request: Request):
    data = await request.json()

    with open("intents.json", "w") as f:
        json.dump(data, f, indent=4)

    load_intents()
    return {"status": "updated"}

# ---------------------
# DELETE USER
# ---------------------
@app.get("/delete_user/{user_id}")
def delete_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT username FROM users WHERE rowid=?", (user_id,))
    row = cursor.fetchone()

    if row:
        username = row[0]
        cursor.execute("DELETE FROM chat_history WHERE username=?", (username,))
        cursor.execute("DELETE FROM users WHERE rowid=?", (user_id,))

    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)

# ---------------------
# DELETE CHAT
# ---------------------
@app.get("/delete_chat/{chat_id}")
def delete_chat(chat_id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM chat_history WHERE id=?", (chat_id,))
    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)

# ---------------------
# CLEAR CHATS
# ---------------------
@app.get("/clear_chats")
def clear_chats():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)

# ---------------------
# LOGIN
# ---------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
    "request": request,
    "msg": ""
})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT password FROM users WHERE username=?", (username,))
    data = cursor.fetchone()
    conn.close()

    if data and check_password_hash(data[0], password):
        response = RedirectResponse("/chat", status_code=303)
        response.set_cookie(key="user", value=username, httponly=True)
        return response

    return templates.TemplateResponse("login.html", {"request": request, "msg": "Invalid login"})

# ---------------------
# REGISTER
# ---------------------
@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "msg": ""})

@app.post("/register", response_class=HTMLResponse)
def register(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    if cursor.fetchone():
        return templates.TemplateResponse("register.html", {"request": request, "msg": "User exists"})

    cursor.execute("INSERT INTO users VALUES (?, ?)", (username, generate_password_hash(password)))
    conn.commit()
    conn.close()

    response = RedirectResponse("/chat", status_code=303)
    response.set_cookie(key="user", value=username, httponly=True)
    return response

# ---------------------
# CHAT
# ---------------------
@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    user = request.cookies.get("user")
    if not user:
        return RedirectResponse("/login")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT sender, message, time FROM chat_history WHERE username=?", (user,))
    chats = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "chat_history": chats
    })

@app.post("/chat", response_class=HTMLResponse)
def chat(request: Request, message: str = Form(...)):
    global chatbot_active

    user = request.cookies.get("user")
    if not user:
        return RedirectResponse("/login")

    if not chatbot_active:
        return RedirectResponse("/chat", status_code=303)

    conn = get_db()
    cursor = conn.cursor()

    time = datetime.now().strftime("%H:%M")

    cursor.execute(
        "INSERT INTO chat_history (username, sender, message, time) VALUES (?, ?, ?, ?)",
        (user, "user", message, time)
    )

    reply = get_response(message)

    cursor.execute(
        "INSERT INTO chat_history (username, sender, message, time) VALUES (?, ?, ?, ?)",
        (user, "bot", reply, time)
    )

    conn.commit()
    conn.close()

    return RedirectResponse("/chat", status_code=303)

# ---------------------
# LOGOUT
# ---------------------
@app.get("/logout")
def logout():
    response = RedirectResponse("/login")
    response.delete_cookie("user")
    return response

# ---------------------
# RUN
# ---------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
