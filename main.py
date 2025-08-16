import os
import random
import asyncio
import logging
import requests
import json
import base64
import gc
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from github import Github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-120b")
CLAUDE_MODEL = "anthropic/claude-3.5-sonnet"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "3"))
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "htuananh1/Data-manager"

START_BALANCE = 1000
CHAT_HISTORY_LIMIT = 20

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class GitHubStorage:
    def __init__(self, token: str, repo_name: str):
        self.g = Github(token)
        self.repo = self.g.get_repo(repo_name)
        self.branch = "main"
        self._cache = {}
        self._last_save = {}
        
    def _get_file_content(self, path: str) -> Optional[dict]:
        if path in self._cache:
            return self._cache[path]
            
        try:
            file = self.repo.get_contents(path, ref=self.branch)
            content = base64.b64decode(file.content).decode('utf-8')
            data = json.loads(content)
            self._cache[path] = data
            return data
        except:
            return None
    
    def _save_file(self, path: str, data: dict, message: str, force: bool = False):
        if not force:
            last_save = self._last_save.get(path, 0)
            if datetime.now().timestamp() - last_save < 300:
                self._cache[path] = data
                return
                
        content = json.dumps(data, ensure_ascii=False, indent=2)
        
        try:
            file = self.repo.get_contents(path, ref=self.branch)
            self.repo.update_file(
                path=path,
                message=message,
                content=content,
                sha=file.sha,
                branch=self.branch
            )
        except:
            self.repo.create_file(
                path=path,
                message=message,
                content=content,
                branch=self.branch
            )
        
        self._cache[path] = data
        self._last_save[path] = datetime.now().timestamp()
    
    def get_user_balance(self, user_id: int) -> int:
        data = self._get_file_content("data/scores.json") or {"users": {}}
        return data["users"].get(str(user_id), {}).get("balance", START_BALANCE)
    
    def update_user_balance(self, user_id: int, username: str, amount: int, game_type: str = None):
        data = self._get_file_content("data/scores.json") or {"users": {}}
        
        user_key = str(user_id)
        if user_key not in data["users"]:
            data["users"][user_key] = {
                "user_id": user_id,
                "username": username,
                "balance": START_BALANCE,
                "total_earned": 0,
                "games_played": {},
                "last_updated": datetime.now().isoformat()
            }
        
        user_data = data["users"][user_key]
        user_data["balance"] += amount
        user_data["username"] = username
        user_data["last_updated"] = datetime.now().isoformat()
        
        if amount > 0:
            user_data["total_earned"] += amount
            if game_type:
                if game_type not in user_data["games_played"]:
                    user_data["games_played"][game_type] = 0
                user_data["games_played"][game_type] += 1
        
        self._save_file("data/scores.json", data, f"Update balance: {username} ({amount:+d})")
    
    def get_all_balances(self) -> Dict[int, int]:
        data = self._get_file_content("data/scores.json") or {"users": {}}
        balances = {}
        for user_id, user_data in data["users"].items():
            balances[int(user_id)] = user_data.get("balance", START_BALANCE)
        return balances
    
    def get_leaderboard(self, limit: int = 10) -> List[tuple]:
        data = self._get_file_content("data/scores.json") or {"users": {}}
        
        users_list = []
        for user_data in data["users"].values():
            users_list.append((
                user_data["username"],
                user_data["balance"],
                len(user_data.get("games_played", {}))
            ))
        
        users_list.sort(key=lambda x: x[1], reverse=True)
        return users_list[:limit]
    
    def get_user_stats(self, user_id: int) -> dict:
        data = self._get_file_content("data/scores.json") or {"users": {}}
        user_data = data["users"].get(str(user_id), {})
        
        if not user_data:
            return {'total': 0, 'balance': START_BALANCE, 'games': {}}
        
        stats = {
            'total': user_data.get("total_earned", 0),
            'balance': user_data.get("balance", START_BALANCE),
            'games': {}
        }
        
        for game, count in user_data.get("games_played", {}).items():
            stats['games'][game] = {
                'played': count,
                'total': 0,
                'best': 0
            }
        
        return stats
    
    def get_quiz_pool(self) -> List[dict]:
        data = self._get_file_content("data/quiz_pool.json")
        return data.get("questions", []) if data else []
    
    def add_quiz(self, quiz: dict):
        data = self._get_file_content("data/quiz_pool.json") or {"questions": []}
        data["questions"].append(quiz)
        self._save_file("data/quiz_pool.json", data, "Add new quiz")
    
    def get_chat_list(self) -> List[tuple]:
        data = self._get_file_content("data/chats.json")
        return data.get("chats", []) if data else []
    
    def save_chat_info(self, chat_id: int, chat_type: str, title: str = None):
        data = self._get_file_content("data/chats.json") or {"chats": []}
        
        existing = False
        for i, chat in enumerate(data["chats"]):
            if chat[0] == chat_id:
                data["chats"][i] = (chat_id, chat_type, title)
                existing = True
                break
        
        if not existing:
            data["chats"].append((chat_id, chat_type, title))
        
        self._save_file("data/chats.json", data, f"Update chat info: {chat_id}")
    
    def get_chat_history(self, chat_id: int) -> List[dict]:
        data = self._get_file_content(f"data/chat_history/{chat_id}.json")
        return data.get("messages", []) if data else []
    
    def save_chat_history(self, chat_id: int, messages: List[dict]):
        data = {"messages": messages[-CHAT_HISTORY_LIMIT:], "updated": datetime.now().isoformat()}
        self._save_file(f"data/chat_history/{chat_id}.json", data, f"Update chat history: {chat_id}")
    
    async def force_save_all(self):
        for path, data in self._cache.items():
            try:
                self._save_file(path, data, "Periodic save", force=True)
            except Exception as e:
                logger.error(f"Error saving {path}: {e}")

storage = GitHubStorage(GITHUB_TOKEN, GITHUB_REPO)

active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
minigame_sessions: Dict[int, dict] = {}
user_balances: Dict[int, int] = {}
quiz_sessions: Dict[int, dict] = {}
quiz_history: Dict[int, List[str]] = {}
goodnight_task = None
save_task = None

def _fmt_money(x: int) -> str:
    return f"{x:,}".replace(",", ".")

def get_user_balance(user_id: int) -> int:
    if user_id not in user_balances:
        user_balances[user_id] = storage.get_user_balance(user_id)
    return user_balances[user_id]

def update_user_balance(user_id: int, username: str, amount: int, game_type: str = None):
    try:
        storage.update_user_balance(user_id, username, amount, game_type)
        if user_id in user_balances:
            user_balances[user_id] += amount
        else:
            user_balances[user_id] = storage.get_user_balance(user_id)
    except Exception as e:
        logger.error(f"Update balance error: {e}")

def save_chat_info(chat_id: int, chat_type: str, title: str = None):
    try:
        storage.save_chat_info(chat_id, chat_type, title)
    except Exception as e:
        logger.error(f"Save chat info error: {e}")

def get_all_chats():
    try:
        return storage.get_chat_list()
    except Exception as e:
        logger.error(f"Get chats error: {e}")
        return []

def cleanup_memory():
    global chat_history, quiz_history
    for chat_id in list(chat_history.keys()):
        if len(chat_history[chat_id]) > CHAT_HISTORY_LIMIT:
            chat_history[chat_id] = chat_history[chat_id][-CHAT_HISTORY_LIMIT:]
    
    for chat_id in list(quiz_history.keys()):
        if len(quiz_history[chat_id]) > 20:
            quiz_history[chat_id] = quiz_history[chat_id][-20:]
    
    gc.collect()

class GuessNumberGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.attempts = 0
        self.max_attempts = 15
        self.hints_used = 0
        self.max_hints = 4
        self.start_time = datetime.now()
        self.score = 5000
        self.secret_number = random.randint(1, 999)
        self.riddle = self.generate_riddle()
            
    def generate_riddle(self) -> str:
        riddles = []
        if self.secret_number % 2 == 0:
            riddles.append("số chẵn")
        else:
            riddles.append("số lẻ")
        if self.secret_number < 500:
            riddles.append("nhỏ hơn 500")
        else:
            riddles.append("lớn hơn hoặc bằng 500")
        return f"Số bí mật là {' và '.join(riddles)}"
        
    def get_hint(self) -> str:
        if self.hints_used >= self.max_hints:
            return "❌ Hết gợi ý rồi!"
            
        self.hints_used += 1
        self.score -= 500
        
        if self.hints_used == 1:
            hundreds = self.secret_number // 100
            hint = f"💡 Gợi ý 1: {'Số có 1-2 chữ số' if hundreds == 0 else f'Chữ số hàng trăm là {hundreds}'}"
        elif self.hints_used == 2:
            tens = (self.secret_number % 100) // 10
            hint = f"💡 Gợi ý 2: Chữ số hàng chục là {tens}"
        elif self.hints_used == 3:
            digit_sum = sum(int(d) for d in str(self.secret_number))
            hint = f"💡 Gợi ý 3: Tổng các chữ số là {digit_sum}"
        else:
            lower = (self.secret_number // 10) * 10
            upper = lower + 9
            hint = f"💡 Gợi ý 4: Số từ {max(1, lower)} đến {min(999, upper)}"
        return f"{hint}\n🎯 Còn {self.max_hints - self.hints_used} gợi ý"
        
    def make_guess(self, guess: int) -> Tuple[bool, str]:
        self.attempts += 1
        self.score -= 200
        
        if guess == self.secret_number:
            time_taken = (datetime.now() - self.start_time).seconds
            final_score = max(self.score, 100)
            return True, f"🎉 Đúng rồi! Số {self.secret_number}!\n⏱️ {time_taken}s | 🏆 {final_score} điểm"
            
        if self.attempts >= self.max_attempts:
            return True, f"😤 Hết lượt! Số là {self.secret_number}\n💡 {self.riddle}"
            
        hint = "📈 cao hơn" if guess < self.secret_number else "📉 thấp hơn"
        remaining = self.max_attempts - self.attempts
        return False, f"{guess} {hint}! Còn {remaining} lượt | 💰 {self.score}đ | /hint"

class MathQuizGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.attempts = 0
        self.max_attempts = 3
        self.start_time = datetime.now()
        self.current_question = None
        self.current_answer = None
        
    def generate_question(self) -> str:
        difficulty = min(5, self.score // 500 + 1)
        
        if difficulty <= 2:
            a = random.randint(10, 99)
            b = random.randint(10, 99)
            op = random.choice(['+', '-'])
            if op == '+':
                self.current_answer = a + b
                self.current_question = f"{a} + {b}"
            else:
                if a < b:
                    a, b = b, a
                self.current_answer = a - b
                self.current_question = f"{a} - {b}"
        elif difficulty <= 4:
            a = random.randint(10, 50)
            b = random.randint(2, 9)
            op = random.choice(['×', '+', '-'])
            if op == '×':
                self.current_answer = a * b
                self.current_question = f"{a} × {b}"
            elif op == '+':
                c = random.randint(10, 99)
                self.current_answer = a + b * 10 + c
                self.current_question = f"{a} + {b * 10} + {c}"
            else:
                c = random.randint(100, 500)
                d = random.randint(10, 99)
                self.current_answer = c - d
                self.current_question = f"{c} - {d}"
        else:
            a = random.randint(10, 30)
            b = random.randint(11, 30)
            c = random.randint(2, 9)
            self.current_answer = a * b + c
            self.current_question = f"{a} × {b} + {c}"
            
        self.attempts = 0
        return self.current_question
        
    def check_answer(self, answer: int) -> Tuple[bool, str]:
        self.attempts += 1
        
        if answer == self.current_answer:
            points = (self.max_attempts - self.attempts + 1) * 100
            self.score += points
            return True, f"✅ Đúng! +{points} điểm (Tổng: {self.score})"
        
        if self.attempts >= self.max_attempts:
            return False, f"❌ Hết lượt! Đáp án: {self.current_answer}"
            
        remaining = self.max_attempts - self.attempts
        return False, f"❌ Sai! Còn {remaining} lần thử"

class VietnameseQuiz1Game:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.current_quiz = None
        self.start_time = datetime.now()
        
    async def generate_quiz(self) -> dict:
        global quiz_history
        
        if self.chat_id not in quiz_history:
            quiz_history[self.chat_id] = []
        
        recent_questions = quiz_history[self.chat_id][-10:] if len(quiz_history[self.chat_id]) > 0 else []
        history_text = "\n".join(recent_questions) if recent_questions else "None"
        
        topics = ["Lịch sử Việt Nam", "Địa lý Việt Nam", "Văn hóa Việt Nam", "Ẩm thực Việt Nam", "Khoa học Việt Nam", "Thể thao Việt Nam"]
        topic = random.choice(topics)
        
        prompt = f"""Create a quiz question about {topic} with MAXIMUM ACCURACY.

CRITICAL REQUIREMENTS:
1. MUST be 100% factually accurate and verifiable
2. Different from previously asked questions
3. 4 options with ONLY 1 correct answer

Previously asked: {history_text}

Return ONLY valid JSON in Vietnamese:
{{
  "topic": "{topic}",
  "question": "question in Vietnamese",
  "options": ["A. option", "B. option", "C. option", "D. option"],
  "answer": "A or B or C or D",
  "explain": "explanation in Vietnamese"
}}"""

        messages = [
            {"role": "system", "content": "You are a Vietnamese education expert. Create only 100% accurate quiz questions."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await call_api(messages, model=CLAUDE_MODEL, max_tokens=500, temperature=0.2)
            
            if not response:
                return None
            
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start == -1 or json_end <= json_start:
                return None
                
            json_str = response[json_start:json_end]
            data = json.loads(json_str)
            
            quiz = {
                "topic": data.get("topic", topic),
                "question": data.get("question", ""),
                "options": data.get("options", []),
                "correct": data.get("answer", "")[0].upper() if data.get("answer") else "",
                "explanation": data.get("explain", "")
            }
            
            if quiz["question"] and len(quiz["options"]) == 4 and quiz["correct"] in ["A", "B", "C", "D"]:
                quiz_history[self.chat_id].append(quiz["question"][:100])
                try:
                    storage.add_quiz(quiz)
                except:
                    pass
                return quiz
                
        except Exception as e:
            logger.error(f"Generate quiz error: {e}")
        
        return None

class VietnameseQuiz2Game:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.attempts = 0
        self.max_attempts = 1
        self.current_quiz = None
        self.start_time = datetime.now()
        
    async def generate_quiz(self) -> dict:
        global quiz_history
        
        if self.chat_id not in quiz_history:
            quiz_history[self.chat_id] = []
        
        recent_questions = quiz_history[self.chat_id][-10:] if len(quiz_history[self.chat_id]) > 0 else []
        history_text = "\n".join(recent_questions) if recent_questions else "None"
        
        topics = ["Lịch sử Việt Nam", "Địa lý Việt Nam", "Văn hóa Việt Nam", "Ẩm thực Việt Nam", "Khoa học Việt Nam", "Thể thao Việt Nam"]
        topic = random.choice(topics)
        
        prompt = f"""Create a quiz question about {topic} with MAXIMUM ACCURACY.

CRITICAL REQUIREMENTS:
1. MUST be 100% factually accurate and verifiable
2. Different from previously asked questions
3. Question should have a SHORT answer (1-3 words maximum)
4. Answer should be simple and clear (city name, person name, food name, etc.)

Previously asked: {history_text}

Return ONLY valid JSON in Vietnamese:
{{
  "topic": "{topic}",
  "question": "question in Vietnamese (requiring short answer)",
  "answer": "short answer in Vietnamese (1-3 words)",
  "explanation": "brief explanation in Vietnamese"
}}"""

        messages = [
            {"role": "system", "content": "You are a Vietnamese education expert. Create quiz questions with SHORT, SIMPLE answers."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await call_api(messages, model=CLAUDE_MODEL, max_tokens=300, temperature=0.2)
            
            if not response:
                return None
            
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start == -1 or json_end <= json_start:
                return None
                
            json_str = response[json_start:json_end]
            data = json.loads(json_str)
            
            quiz = {
                "topic": data.get("topic", topic),
                "question": data.get("question", ""),
                "answer": data.get("answer", ""),
                "explanation": data.get("explanation", "")
            }
            
            if quiz["question"] and quiz["answer"]:
                quiz_history[self.chat_id].append(quiz["question"][:100])
                try:
                    storage.add_quiz(quiz)
                except:
                    pass
                return quiz
                
        except Exception as e:
            logger.error(f"Generate quiz error: {e}")
        
        return None
    
    def normalize_answer(self, text: str) -> str:
        text = text.lower().strip()
        text = text.replace(".", "").replace(",", "").replace("!", "").replace("?", "")
        text = " ".join(text.split())
        return text
    
    def check_answer(self, user_answer: str) -> Tuple[bool, str]:
        if not self.current_quiz:
            return False, "❌ Không có câu hỏi!"
            
        normalized_user = self.normalize_answer(user_answer)
        normalized_correct = self.normalize_answer(self.current_quiz["answer"])
        
        correct = False
        if normalized_user == normalized_correct:
            correct = True
        else:
            user_words = set(normalized_user.split())
            correct_words = set(normalized_correct.split())
            if len(correct_words) <= 3 and user_words & correct_words:
                correct = True
        
        if correct:
            points = 300
            self.score += points
            return True, f"✅ Chính xác! +{points} điểm\n\n{self.current_quiz['explanation']}"
        else:
            return False, f"❌ Sai! Đáp án: {self.current_quiz['answer']}\n\n{self.current_quiz['explanation']}"

async def call_api(messages: List[dict], model: str = None, max_tokens: int = 400, temperature: float = None) -> str:
    try:
        headers = {
            "Authorization": f"Bearer {VERCEL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        if temperature is None:
            temperature = 0.3 if model == CLAUDE_MODEL else 0.7
        
        data = {
            "model": model or CHAT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9
        }
        
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=25
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            logger.error(f"API error: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"API error: {e}")
        return None

async def periodic_save(app):
    while True:
        await asyncio.sleep(300)
        try:
            await storage.force_save_all()
            logger.info("Periodic save completed")
        except Exception as e:
            logger.error(f"Periodic save error: {e}")

async def goodnight_scheduler(app):
    while True:
        now = datetime.now()
        target_time = now.replace(hour=23, minute=0, second=0, microsecond=0)
        
        if now >= target_time:
            target_time += timedelta(days=1)
        
        wait_seconds = (target_time - now).total_seconds()
        logger.info(f"Waiting {wait_seconds} seconds until 23:00")
        
        await asyncio.sleep(wait_seconds)
        
        await send_goodnight_message(app)
        
        await asyncio.sleep(60)

async def send_goodnight_message(app):
    chats = get_all_chats()
    
    messages = [
        "Linh chúc các tình yêu ngủ ngon ❤️❤️",
        "23h rồi! Ngủ ngon nhé mọi người 😴💕",
        "Chúc cả nhà có giấc ngủ thật ngon 🌙✨",
        "Good night! Ngủ ngon và mơ đẹp nhé 💫❤️",
        "Linh chúc mọi người ngủ ngon! Mai gặp lại nha 😘"
    ]
    
    message = random.choice(messages)
    
    for chat in chats:
        try:
            chat_id = chat[0] if isinstance(chat, tuple) else chat
            await app.bot.send_message(chat_id=chat_id, text=message)
            logger.info(f"Sent goodnight to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send to {chat_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    save_chat_info(chat.id, chat.type, chat.title)
    user = update.effective_user
    balance = get_user_balance(user.id)
    
    await update.message.reply_text(f"""
👋 **Xin chào! Mình là Linh!**

💰 Số dư của bạn: **{_fmt_money(balance)}**

🎮 **Minigame:**
/minigame - Chơi ngẫu nhiên các minigame
/stopmini - Dừng minigame

📝 **Chơi riêng:**
/guessnumber - Đoán số 1-999
/quiz1 - Câu đố chọn đáp án
/quiz2 - Câu đố trả lời ngắn
/math - Toán học

📊 /leaderboard - BXH theo số dư
📈 /stats - Thống kê của bạn
💰 /bal - Xem số dư

💬 Chat với Linh (GPT)
💕 Mỗi 23h Linh sẽ chúc ngủ ngon!
""")

async def minigame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    if chat_id in minigame_sessions:
        await update.message.reply_text("⚠️ Đang có minigame chạy! Dùng /stopmini để dừng.")
        return
    
    minigame_sessions[chat_id] = {
        "active": True,
        "current_game": None,
        "total_score": 0,
        "games_played": 0,
        "start_time": datetime.now(),
        "username": user.username or user.first_name,
        "user_id": user.id
    }
    
    await start_random_minigame(chat_id, context)

async def start_random_minigame(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    if chat_id not in minigame_sessions or not minigame_sessions[chat_id]["active"]:
        return
    
    if chat_id in active_games:
        del active_games[chat_id]
    
    games = ["guessnumber", "quiz1", "quiz2", "math"]
    game_type = random.choice(games)
    
    session = minigame_sessions[chat_id]
    session["current_game"] = game_type
    session["games_played"] += 1
    
    await context.bot.send_message(
        chat_id, 
        f"🎲 **Minigame #{session['games_played']}**\nTổng điểm: {session['total_score']}\n\n⏳ Đang tải..."
    )
    
    await asyncio.sleep(1)
    
    if game_type == "guessnumber":
        game = GuessNumberGame(chat_id)
        active_games[chat_id] = {"type": "guessnumber", "game": game, "minigame": True}
        
        await context.bot.send_message(
            chat_id,
            f"""🎮 **ĐOÁN SỐ 1-999**

💡 {game.riddle}
📝 15 lần | 💰 5000đ
/hint - Gợi ý (-500đ, tối đa 4 lần)

Đoán đi!"""
        )
    
    elif game_type == "quiz1":
        game = VietnameseQuiz1Game(chat_id)
        quiz = await game.generate_quiz()
        
        if not quiz:
            await context.bot.send_message(chat_id, "❌ Lỗi tạo câu hỏi! Chuyển game khác...")
            await asyncio.sleep(2)
            await start_random_minigame(chat_id, context)
            return
        
        game.current_quiz = quiz
        active_games[chat_id] = {"type": "quiz1", "game": game, "minigame": True}
        
        keyboard = []
        for option in quiz["options"]:
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        topic_emojis = {
            "Lịch sử Việt Nam": "📜",
            "Địa lý Việt Nam": "🗺️",
            "Ẩm thực Việt Nam": "🍜",
            "Văn hóa Việt Nam": "🎭",
            "Khoa học Việt Nam": "🔬",
            "Thể thao Việt Nam": "⚽"
        }
        
        emoji = topic_emojis.get(quiz["topic"], "❓")
        
        await context.bot.send_message(
            chat_id,
            f"{emoji} **QUIZ 1.0 - {quiz['topic'].upper()}**\n\n{quiz['question']}",
            reply_markup=reply_markup
        )
    
    elif game_type == "quiz2":
        game = VietnameseQuiz2Game(chat_id)
        quiz = await game.generate_quiz()
        
        if not quiz:
            await context.bot.send_message(chat_id, "❌ Lỗi tạo câu hỏi! Chuyển game khác...")
            await asyncio.sleep(2)
            await start_random_minigame(chat_id, context)
            return
        
        game.current_quiz = quiz
        active_games[chat_id] = {"type": "quiz2", "game": game, "minigame": True}
        
        topic_emojis = {
            "Lịch sử Việt Nam": "📜",
            "Địa lý Việt Nam": "🗺️",
            "Ẩm thực Việt Nam": "🍜",
            "Văn hóa Việt Nam": "🎭",
            "Khoa học Việt Nam": "🔬",
            "Thể thao Việt Nam": "⚽"
        }
        
        emoji = topic_emojis.get(quiz["topic"], "❓")
        
        await context.bot.send_message(
            chat_id,
            f"""{emoji} **QUIZ 2.0 - {quiz["topic"].upper()}**

{quiz["question"]}

💡 Trả lời ngắn gọn (1-3 từ)
✍️ Gõ câu trả lời của bạn!"""
        )
    
    elif game_type == "math":
        game = MathQuizGame(chat_id)
        question = game.generate_question()
        active_games[chat_id] = {"type": "math", "game": game, "minigame": True}
        
        await context.bot.send_message(
            chat_id,
            f"""🧮 **TOÁN HỌC**

Tính: **{question} = ?**

📝 Bạn có {game.max_attempts} lần thử
✍️ Gõ đáp án!"""
        )

async def stop_minigame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in minigame_sessions:
        await update.message.reply_text("❌ Không có minigame nào đang chạy!")
        return
    
    session = minigame_sessions[chat_id]
    total_time = (datetime.now() - session["start_time"]).seconds
    
    if session["total_score"] > 0:
        update_user_balance(
            session["user_id"], 
            session["username"], 
            session["total_score"], 
            "minigame"
        )
    
    await update.message.reply_text(
        f"""🏁 **KẾT THÚC MINIGAME!**

👤 Người chơi: {session['username']}
🎮 Số game đã chơi: {session['games_played']}
💰 Tổng điểm kiếm được: {session['total_score']}
⏱️ Thời gian: {total_time}s

Cảm ơn bạn đã chơi! 💕"""
    )
    
    if chat_id in quiz_sessions:
        del quiz_sessions[chat_id]
    
    del minigame_sessions[chat_id]
    if chat_id in active_games:
        del active_games[chat_id]

async def start_guess_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
        
    game = GuessNumberGame(chat_id)
    active_games[chat_id] = {"type": "guessnumber", "game": game}
    
    await update.message.reply_text(f"""🎮 **ĐOÁN SỐ 1-999**

💡 {game.riddle}
📝 15 lần | 💰 5000đ
/hint - Gợi ý (-500đ, tối đa 4 lần)

Đoán đi!""")

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
        await update.message.reply_text("❌ Không trong game đoán số!")
        return
        
    game = active_games[chat_id]["game"]
    await update.message.reply_text(game.get_hint())

async def quiz1_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
    
    loading_msg = await update.message.reply_text("⏳ Claude AI đang tạo câu hỏi...")
    
    game = VietnameseQuiz1Game(chat_id)
    quiz = await game.generate_quiz()
    
    if not quiz:
        await loading_msg.edit_text("❌ Lỗi tạo câu hỏi! Thử lại /quiz1")
        return
    
    game.current_quiz = quiz
    quiz_sessions[chat_id] = quiz
    active_games[chat_id] = {"type": "quiz1", "game": game}
    
    keyboard = []
    for option in quiz["options"]:
        keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    topic_emojis = {
        "Lịch sử Việt Nam": "📜",
        "Địa lý Việt Nam": "🗺️",
        "Ẩm thực Việt Nam": "🍜",
        "Văn hóa Việt Nam": "🎭",
        "Khoa học Việt Nam": "🔬",
        "Thể thao Việt Nam": "⚽"
    }
    
    emoji = topic_emojis.get(quiz["topic"], "❓")
    
    await loading_msg.edit_text(
        f"{emoji} **QUIZ 1.0 - {quiz['topic'].upper()}**\n\n{quiz['question']}",
        reply_markup=reply_markup
    )

async def quiz2_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
    
    loading_msg = await update.message.reply_text("⏳ Claude AI đang tạo câu hỏi...")
    
    game = VietnameseQuiz2Game(chat_id)
    quiz = await game.generate_quiz()
    
    if not quiz:
        await loading_msg.edit_text("❌ Lỗi tạo câu hỏi! Thử lại /quiz2")
        return
    
    game.current_quiz = quiz
    active_games[chat_id] = {"type": "quiz2", "game": game}
    
    topic_emojis = {
        "Lịch sử Việt Nam": "📜",
        "Địa lý Việt Nam": "🗺️",
        "Ẩm thực Việt Nam": "🍜",
        "Văn hóa Việt Nam": "🎭",
        "Khoa học Việt Nam": "🔬",
        "Thể thao Việt Nam": "⚽"
    }
    
    emoji = topic_emojis.get(quiz["topic"], "❓")
    
    await loading_msg.edit_text(
        f"""{emoji} **QUIZ 2.0 - {quiz["topic"].upper()}**

{quiz["question"]}

💡 Trả lời ngắn gọn (1-3 từ)
✍️ Gõ câu trả lời của bạn!"""
    )

async def math_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
    
    game = MathQuizGame(chat_id)
    question = game.generate_question()
    active_games[chat_id] = {"type": "math", "game": game}
    
    await update.message.reply_text(
        f"""🧮 **TOÁN HỌC**

Tính: **{question} = ?**

📝 Bạn có {game.max_attempts} lần thử
✍️ Gõ đáp án!"""
    )

async def bal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    await update.message.reply_text(f"👛 Số dư của bạn: {_fmt_money(balance)}")

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaderboard = storage.get_leaderboard()
    
    if not leaderboard:
        await update.message.reply_text("Chưa có dữ liệu bảng xếp hạng.")
        return
        
    lines = ["🏆 **BẢNG XẾP HẠNG THEO SỐ DƯ**\n"]
    
    for i, (username, balance, games) in enumerate(leaderboard, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(f"{medal} {username} — {_fmt_money(balance)} ({games} games)")
        
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats = storage.get_user_stats(user.id)
    
    message = f"📊 **{user.first_name}**\n\n"
    message += f"💰 Số dư hiện tại: {_fmt_money(stats['balance'])}\n"
    message += f"📈 Tổng điểm kiếm được: {_fmt_money(stats['total'])}\n"
    
    if stats['games']:
        message += "\n**Thống kê game:**\n"
        for game_type, data in stats['games'].items():
            game_name = {
                "guessnumber": "Đoán số",
                "quiz1": "Quiz 1.0",
                "quiz2": "Quiz 2.0",
                "math": "Toán học",
                "minigame": "Minigame tổng hợp"
            }.get(game_type, game_type)
            message += f"• {game_name}: {data['played']} lần\n"
            
    await update.message.reply_text(message)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    if data.startswith("quiz_") and chat_id in quiz_sessions:
        quiz = quiz_sessions[chat_id]
        answer = data.split("_")[1]
        
        if answer == quiz["correct"]:
            points = 300
            result = f"✅ Chính xác! (+{points}đ)\n\n{quiz['explanation']}"
            
            if chat_id in active_games:
                game_info = active_games[chat_id]
                if game_info.get("minigame") and chat_id in minigame_sessions:
                    minigame_sessions[chat_id]["total_score"] += points
                else:
                    update_user_balance(user.id, username, points, "quiz1")
        else:
            result = f"❌ Sai rồi! Đáp án: {quiz['correct']}\n\n{quiz['explanation']}"
        
        del quiz_sessions[chat_id]
        await query.message.edit_text(result)
        
        if chat_id in active_games:
            game_info = active_games[chat_id]
            del active_games[chat_id]
            
            if game_info.get("minigame") and chat_id in minigame_sessions:
                await asyncio.sleep(3)
                await start_random_minigame(chat_id, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    chat = update.effective_chat
    save_chat_info(chat.id, chat.type, chat.title)
    
    if chat_id in active_games:
        game_info = active_games[chat_id]
        game = game_info["game"]
        is_minigame = game_info.get("minigame", False)
        
        if game_info["type"] == "guessnumber":
            try:
                guess = int(message)
                if 1 <= guess <= 999:
                    is_finished, response = game.make_guess(guess)
                    await update.message.reply_text(response)
                    
                    if is_finished:
                        if "Đúng" in response:
                            if is_minigame and chat_id in minigame_sessions:
                                minigame_sessions[chat_id]["total_score"] += game.score
                            else:
                                update_user_balance(user.id, username, game.score, "guessnumber")
                        
                        del active_games[chat_id]
                        
                        if is_minigame and chat_id in minigame_sessions:
                            await asyncio.sleep(3)
                            await start_random_minigame(chat_id, context)
                else:
                    await update.message.reply_text("❌ Từ 1-999 thôi!")
            except ValueError:
                pass
                
        elif game_info["type"] == "quiz2":
            is_finished, response = game.check_answer(message)
            await update.message.reply_text(response)
            
            if is_finished:
                if "Chính xác" in response:
                    if is_minigame and chat_id in minigame_sessions:
                        minigame_sessions[chat_id]["total_score"] += 300
                    else:
                        update_user_balance(user.id, username, 300, "quiz2")
                
                del active_games[chat_id]
                
                if is_minigame and chat_id in minigame_sessions:
                    await asyncio.sleep(3)
                    await start_random_minigame(chat_id, context)
                    
        elif game_info["type"] == "math":
            try:
                answer = int(message)
                is_correct, response = game.check_answer(answer)
                await update.message.reply_text(response)
                
                if is_correct or game.attempts >= game.max_attempts:
                    question = game.generate_question()
                    await asyncio.sleep(1)
                    
                    if game.score >= 1500 or (not is_correct and game.attempts >= game.max_attempts):
                        final_score = game.score
                        await update.message.reply_text(
                            f"🏁 Kết thúc! Tổng điểm: {final_score}"
                        )
                        
                        if is_minigame and chat_id in minigame_sessions:
                            minigame_sessions[chat_id]["total_score"] += final_score
                        else:
                            update_user_balance(user.id, username, final_score, "math")
                        
                        del active_games[chat_id]
                        
                        if is_minigame and chat_id in minigame_sessions:
                            await asyncio.sleep(3)
                            await start_random_minigame(chat_id, context)
                    else:
                        await update.message.reply_text(
                            f"📝 Câu tiếp theo:\n\n**{question} = ?**"
                        )
            except ValueError:
                pass
        return
    
    if chat_id not in chat_history:
        history = storage.get_chat_history(chat_id)
        chat_history[chat_id] = history if history else []
        
    chat_history[chat_id].append({"role": "user", "content": message})
    
    if len(chat_history[chat_id]) > CHAT_HISTORY_LIMIT:
        chat_history[chat_id] = chat_history[chat_id][-CHAT_HISTORY_LIMIT:]
    
    messages = [
        {"role": "system", "content": "Bạn là Linh - cô gái Việt Nam vui vẻ, thân thiện. Trả lời ngắn gọn."}
    ]
    messages.extend(chat_history[chat_id])
    
    response = await call_api(messages, max_tokens=300)
    
    if response:
        chat_history[chat_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response)
        
        try:
            storage.save_chat_history(chat_id, chat_history[chat_id])
        except:
            pass
    else:
        await update.message.reply_text("😅 Xin lỗi, mình đang gặp lỗi!")

async def post_init(application: Application) -> None:
    global goodnight_task, save_task
    goodnight_task = asyncio.create_task(goodnight_scheduler(application))
    save_task = asyncio.create_task(periodic_save(application))
    logger.info("Schedulers started!")

async def post_shutdown(application: Application) -> None:
    global goodnight_task, save_task
    
    if goodnight_task:
        goodnight_task.cancel()
        try:
            await goodnight_task
        except asyncio.CancelledError:
            pass
            
    if save_task:
        save_task.cancel()
        try:
            await save_task
        except asyncio.CancelledError:
            pass
    
    await storage.force_save_all()

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("minigame", minigame_cmd))
    application.add_handler(CommandHandler("stopmini", stop_minigame_cmd))
    application.add_handler(CommandHandler("guessnumber", start_guess_number))
    application.add_handler(CommandHandler("quiz1", quiz1_command))
    application.add_handler(CommandHandler("quiz2", quiz2_command))
    application.add_handler(CommandHandler("math", math_command))
    application.add_handler(CommandHandler("hint", hint_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("bal", bal_cmd))
    application.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot started! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
