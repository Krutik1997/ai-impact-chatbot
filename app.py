chatbot_active = True
import secrets

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from rapidfuzz import fuzz

import json
import os
import random
from typing import List, Dict, Any

SECRET_KEY = os.environ.get("SECRET_KEY","dev-secret-key")

app = FastAPI()

import psycopg2
import os

DATABASE_URL = os.environ.get("DATABASE_URL")


# ---------------------
# GLOBAL CONTROL
# ---------------------

# ---------------------
# TEMPLATES
# ---------------------
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ---------------------
# STATIC FILES
# ---------------------
if (BASE_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# ---------------------
# DATABASE
# ---------------------

def get_db():
    return psycopg2.connect(DATABASE_URL)
    
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
        id SERIAL PRIMARY KEY,
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

    cursor.execute("SELECT password FROM users WHERE username=%s", (username,))
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

    cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
    if cursor.fetchone():
        return templates.TemplateResponse("register.html", {"request": request, "msg": "User exists"})

    cursor.execute("INSERT INTO users VALUES (%s, %s)", (username, generate_password_hash(password)))
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

    cursor.execute("SELECT sender, message, time FROM chat_history WHERE username=%s", (user,))
    chats = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "chat_history": chats
    })

@app.post("/chat")
async def chat(request: Request):
    global chatbot_active

    data = await request.json()
    message = data.get("message")

    user = request.cookies.get("user")

    if not user:
        return {"reply": "Please login first"}

    if not chatbot_active:
        return {"reply": "Bot is currently OFF"}

    conn = get_db()
    cursor = conn.cursor()

    time = datetime.now().strftime("%H:%M")

    # save user msg
    cursor.execute(
        "INSERT INTO chat_history (username, sender, message, time) VALUES (%s, %s, %s, %s)",
        (user, "user", message, time)
    )

    # bot reply
    reply = get_response(message)

    cursor.execute(
        "INSERT INTO chat_history (username, sender, message, time) VALUES (%s, %s, %s, %s)",
        (user, "bot", reply, time)
    )

    conn.commit()
    conn.close()

    return {"reply": reply}

#---------------------
# ADMIN PAGE
#---------------------
@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    user = request.cookies.get("user")

    # 🔐 Only admin allowed
    if user != "admin":
        return RedirectResponse("/login")

    conn = get_db()
    cursor = conn.cursor()

    # 👥 Users with chat count
    cursor.execute("""
        SELECT u.username, COUNT(c.id)
        FROM users u
        LEFT JOIN chat_history c ON u.username = c.username
        GROUP BY u.username
    """)
    users = cursor.fetchall()

    # 💬 All chats
    cursor.execute("""
        SELECT id, username, sender, message, time
        FROM chat_history
        ORDER BY id DESC
    """)
    chats = cursor.fetchall()

    conn.close()

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "users": users,
            "chats": chats,
            "bot_status": chatbot_active
        }
    )
    
#---------------------
# TOGGLE CHATBOT
#---------------------
@app.get("/toggle_bot")
def toggle_bot():
    global chatbot_active
    chatbot_active = not chatbot_active
    return {"status": chatbot_active}
 
#---------------------
# DELETE USER
#---------------------
@app.get("/delete_user/{user_id}")
def delete_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM users WHERE username=%s", (user_id,))
    cursor.execute("DELETE FROM chat_history WHERE username NOT IN (SELECT username FROM users)")

    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)

#---------------------
# DELETE CHAT
#---------------------
@app.get("/delete_chat/{chat_id}")
def delete_chat(chat_id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM chat_history WHERE id=%s", (chat_id,))

    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)

#---------------------
# CLEAR CHAT HISTORY
#---------------------
@app.get("/clear_chats")
def clear_chats():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM chat_history")

    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)

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
