import os
import random
import asyncio
import logging
import requests
import json
import base64
import gc
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from github import Github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Config
BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-120b")
CLAUDE_MODEL = "anthropic/claude-3.5-sonnet"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "htuananh1/Data-manager"

START_BALANCE = 1000
CHAT_HISTORY_LIMIT = 20

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class GitHubStorage:
    def __init__(self, token: str, repo_name: str):
        try:
            self.g = Github(token)
            self.repo = self.g.get_repo(repo_name)
            self.branch = "main"
            self._cache = {}
            self._last_save = {}
            logger.info("GitHub storage initialized successfully")
        except Exception as e:
            logger.error(f"Failed to init GitHub storage: {e}")
            raise
        
    def _get_file_content(self, path: str) -> Optional[dict]:
        if path in self._cache:
            return self._cache[path]
            
        try:
            file = self.repo.get_contents(path, ref=self.branch)
            content = base64.b64decode(file.content).decode('utf-8')
            data = json.loads(content)
            self._cache[path] = data
            return data
        except Exception as e:
            logger.warning(f"File {path} not found or error: {e}")
            return None
    
    def _save_file(self, path: str, data: dict, message: str, force: bool = False):
        try:
            # Rate limiting
            if not force and path in self._last_save:
                if datetime.now().timestamp() - self._last_save[path] < 300:
                    self._cache[path] = data
                    return
                    
            content = json.dumps(data, ensure_ascii=False, indent=2)
            
            try:
                file = self.repo.get_contents(path, ref=self.branch)
                self.repo.update_file(path, message, content, file.sha, self.branch)
                logger.info(f"Updated file: {path}")
            except:
                self.repo.create_file(path, message, content, self.branch)
                logger.info(f"Created file: {path}")
            
            self._cache[path] = data
            self._last_save[path] = datetime.now().timestamp()
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")
    
    def get_user_balance(self, user_id: int) -> int:
        try:
            data = self._get_file_content("data/scores.json") or {"users": {}}
            user_data = data.get("users", {}).get(str(user_id), {})
            return user_data.get("balance", START_BALANCE)
        except:
            return START_BALANCE
    
    def update_user_balance(self, user_id: int, username: str, amount: int, game_type: str = None):
        try:
            data = self._get_file_content("data/scores.json") or {"users": {}}
            
            if "users" not in data:
                data["users"] = {}
                
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
            
            user = data["users"][user_key]
            user["balance"] = user.get("balance", START_BALANCE) + amount
            user["username"] = username
            user["last_updated"] = datetime.now().isoformat()
            
            if amount > 0:
                user["total_earned"] = user.get("total_earned", 0) + amount
                if game_type:
                    if "games_played" not in user:
                        user["games_played"] = {}
                    user["games_played"][game_type] = user["games_played"].get(game_type, 0) + 1
            
            self._save_file("data/scores.json", data, f"Update: {username} ({amount:+d})")
        except Exception as e:
            logger.error(f"Failed to update balance: {e}")
    
    def get_leaderboard(self, limit: int = 10) -> List[tuple]:
        try:
            data = self._get_file_content("data/scores.json") or {"users": {}}
            users = []
            
            for user_data in data.get("users", {}).values():
                username = user_data.get("username", "Unknown")
                total_earned = user_data.get("total_earned", 0)
                if total_earned > 0:  # Chỉ hiện người có điểm
                    users.append((username, total_earned))
                    
            users.sort(key=lambda x: x[1], reverse=True)
            return users[:limit]
        except Exception as e:
            logger.error(f"Failed to get leaderboard: {e}")
            return []
    
    def get_user_stats(self, user_id: int) -> dict:
        try:
            data = self._get_file_content("data/scores.json") or {"users": {}}
            user_data = data.get("users", {}).get(str(user_id), {})
            
            return {
                'balance': user_data.get("balance", START_BALANCE),
                'total_earned': user_data.get("total_earned", 0),
                'games_played': user_data.get("games_played", {})
            }
        except Exception as e:
            logger.error(f"Failed to get user stats: {e}")
            return {
                'balance': START_BALANCE,
                'total_earned': 0,
                'games_played': {}
            }
    
    def get_quiz1_pool(self) -> List[dict]:
        data = self._get_file_content("data/quiz1_pool.json")
        if data and "questions" in data:
            return data["questions"]
        # Return default questions
        return [
            {
                "topic": "Lịch sử Việt Nam",
                "question": "Vua nào đã đánh thắng quân Nguyên Mông 3 lần?",
                "options": ["A. Trần Nhân Tông", "B. Lý Thái Tông", "C. Lê Lợi", "D. Quang Trung"],
                "correct": "A",
                "explanation": "Trần Nhân Tông là vị vua đã lãnh đạo nhân dân đánh thắng quân Nguyên Mông 3 lần."
            }
        ]
    
    def add_quiz1(self, quiz: dict):
        try:
            data = self._get_file_content("data/quiz1_pool.json") or {"questions": []}
            if "questions" not in data:
                data["questions"] = []
            data["questions"].append(quiz)
            if len(data["questions"]) > 100:
                data["questions"] = data["questions"][-100:]
            self._save_file("data/quiz1_pool.json", data, "Add quiz1")
        except:
            pass
    
    def get_quiz2_pool(self) -> List[dict]:
        data = self._get_file_content("data/quiz2_pool.json")
        if data and "questions" in data:
            return data["questions"]
        # Return default questions
        return [
            {
                "topic": "Địa lý Việt Nam",
                "question": "Thủ đô của Việt Nam là gì?",
                "answer": "Hà Nội",
                "explanation": "Hà Nội là thủ đô của Việt Nam từ năm 1010."
            }
        ]
    
    def add_quiz2(self, quiz: dict):
        try:
            data = self._get_file_content("data/quiz2_pool.json") or {"questions": []}
            if "questions" not in data:
                data["questions"] = []
            data["questions"].append(quiz)
            if len(data["questions"]) > 100:
                data["questions"] = data["questions"][-100:]
            self._save_file("data/quiz2_pool.json", data, "Add quiz2")
        except:
            pass
    
    def get_math_pool(self) -> List[dict]:
        data = self._get_file_content("data/math_pool.json")
        if data and "questions" in data:
            return data["questions"]
        # Return default questions
        return [
            {"question": "25 + 37", "answer": 62},
            {"question": "84 - 29", "answer": 55},
            {"question": "12 × 8", "answer": 96}
        ]
    
    def add_math(self, math: dict):
        try:
            data = self._get_file_content("data/math_pool.json") or {"questions": []}
            if "questions" not in data:
                data["questions"] = []
            data["questions"].append(math)
            if len(data["questions"]) > 100:
                data["questions"] = data["questions"][-100:]
            self._save_file("data/math_pool.json", data, "Add math")
        except:
            pass

# Initialize storage
try:
    storage = GitHubStorage(GITHUB_TOKEN, GITHUB_REPO)
except Exception as e:
    logger.error(f"Critical error initializing storage: {e}")
    storage = None

# Global variables
active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
minigame_sessions: Dict[int, dict] = {}
user_balances: Dict[int, int] = {}

def _fmt_money(x: int) -> str:
    return f"{x:,}".replace(",", ".")

def get_user_balance(user_id: int) -> int:
    if user_id not in user_balances:
        if storage:
            user_balances[user_id] = storage.get_user_balance(user_id)
        else:
            user_balances[user_id] = START_BALANCE
    return user_balances[user_id]

def update_user_balance(user_id: int, username: str, amount: int, game_type: str = None):
    try:
        if storage:
            storage.update_user_balance(user_id, username, amount, game_type)
        
        if user_id in user_balances:
            user_balances[user_id] += amount
        else:
            user_balances[user_id] = get_user_balance(user_id)
    except Exception as e:
        logger.error(f"Update balance error: {e}")

async def call_api(messages: List[dict], model: str = None, max_tokens: int = 400) -> str:
    try:
        headers = {
            "Authorization": f"Bearer {VERCEL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model or CHAT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3 if model == CLAUDE_MODEL else 0.7
        }
        
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=25
        )
        
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        return None
    except Exception as e:
        logger.error(f"API call error: {e}")
        return None

# Game classes (giữ nguyên)
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
        self.current_question = None
        self.current_answer = None
        
    async def generate_question(self) -> str:
        # Simple math generation
        difficulty = random.choice(["easy", "medium", "hard"])
        
        if difficulty == "easy":
            a = random.randint(10, 50)
            b = random.randint(10, 50)
            self.current_question = f"{a} + {b}"
            self.current_answer = a + b
        elif difficulty == "medium":
            a = random.randint(5, 20)
            b = random.randint(5, 20)
            self.current_question = f"{a} × {b}"
            self.current_answer = a * b
        else:
            a = random.randint(20, 50)
            b = random.randint(10, 30)
            c = random.randint(5, 15)
            self.current_question = f"{a} + {b} - {c}"
            self.current_answer = a + b - c
        
        return self.current_question
        
    def check_answer(self, answer: int) -> Tuple[bool, str]:
        self.attempts += 1
        
        if answer == self.current_answer:
            points = (self.max_attempts - self.attempts + 1) * 100
            self.score = points
            return True, f"✅ Đúng! +{points} điểm"
        
        if self.attempts >= self.max_attempts:
            return False, f"❌ Hết lượt! Đáp án: {self.current_answer}"
            
        remaining = self.max_attempts - self.attempts
        return False, f"❌ Sai! Còn {remaining} lần thử"

class VietnameseQuiz1Game:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.current_quiz = None
        
    async def generate_quiz(self) -> dict:
        try:
            # Get from pool
            if storage:
                pool = storage.get_quiz1_pool()
                if pool:
                    return random.choice(pool)
        except:
            pass
            
        # Default quiz
        return {
            "topic": "Lịch sử Việt Nam",
            "question": "Thủ đô đầu tiên của Việt Nam là gì?",
            "options": ["A. Hoa Lư", "B. Thăng Long", "C. Huế", "D. Sài Gòn"],
            "correct": "A",
            "explanation": "Hoa Lư là thủ đô đầu tiên của Việt Nam thời Đinh - Tiền Lê."
        }

class VietnameseQuiz2Game:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.current_quiz = None
        
    async def generate_quiz(self) -> dict:
        try:
            # Get from pool
            if storage:
                pool = storage.get_quiz2_pool()
                if pool:
                    return random.choice(pool)
        except:
            pass
            
        # Default quiz
        return {
            "topic": "Địa lý Việt Nam",
            "question": "Sông dài nhất Việt Nam?",
            "answer": "Sông Mekong",
            "explanation": "Sông Mekong (Cửu Long) là sông dài nhất chảy qua Việt Nam."
        }
    
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

# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        username = user.username or user.first_name
        balance = get_user_balance(user.id)
        
        message = f"""👋 Xin chào {username}! Mình là Linh Bot!

💰 Số dư của bạn: {_fmt_money(balance)}

🎮 **Minigame:**
/minigame - Chơi ngẫu nhiên các game
/stopmini - Dừng minigame

📝 **Chơi riêng lẻ:**
/guessnumber - Đoán số
/quiz1 - Quiz trắc nghiệm
/quiz2 - Quiz trả lời
/math - Toán học

📊 **Thông tin:**
/top - Bảng xếp hạng
/bal - Xem số dư
/stats - Thống kê cá nhân

💬 Hoặc chat trực tiếp với mình!"""
        
        await update.message.reply_text(message, parse_mode="Markdown")
        logger.info(f"Start command successful for user {user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text(
            "👋 Xin chào! Mình là Linh Bot!\n\n"
            "🎮 /minigame - Chơi game\n"
            "📊 /top - Bảng xếp hạng\n"
            "💰 /bal - Xem số dư"
        )

async def bal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        balance = get_user_balance(user.id)
        await update.message.reply_text(f"💰 Số dư của bạn: {_fmt_money(balance)}")
        
    except Exception as e:
        logger.error(f"Error in bal command: {e}", exc_info=True)
        await update.message.reply_text("💰 Số dư: 1.000 (mặc định)")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not storage:
            await update.message.reply_text("📊 Hệ thống đang bảo trì")
            return
            
        leaderboard = storage.get_leaderboard()
        
        if not leaderboard:
            await update.message.reply_text("📊 Chưa có dữ liệu bảng xếp hạng\n\nHãy chơi game để lên bảng!")
            return
        
        msg = "🏆 **BẢNG XẾP HẠNG**\n"
        msg += "────────────────\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, score) in enumerate(leaderboard):
            medal = medals[i] if i < 3 else f"{i+1}."
            msg += f"{medal} {name}: {_fmt_money(score)} điểm\n"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in top command: {e}", exc_info=True)
        await update.message.reply_text("📊 Không thể tải bảng xếp hạng")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        username = user.username or user.first_name
        
        if not storage:
            balance = get_user_balance(user.id)
            msg = f"📊 **{username}**\n\n💰 Số dư: {_fmt_money(balance)}"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return
            
        data = storage.get_user_stats(user.id)
        
        msg = f"📊 **Thống kê của {username}**\n"
        msg += "────────────────\n"
        msg += f"💰 Số dư: {_fmt_money(data['balance'])}\n"
        msg += f"⭐ Tổng điểm: {_fmt_money(data['total_earned'])}\n"
        
        games = data.get('games_played', {})
        if games:
            msg += "\n🎮 **Đã chơi:**\n"
            game_names = {
                "guessnumber": "Đoán số",
                "quiz1": "Quiz trắc nghiệm", 
                "quiz2": "Quiz trả lời",
                "math": "Toán học",
                "minigame": "Minigame"
            }
            for game, count in games.items():
                name = game_names.get(game, game)
                msg += f"• {name}: {count} lần\n"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in stats command: {e}", exc_info=True)
        user = update.effective_user
        username = user.username or user.first_name
        balance = get_user_balance(user.id)
        msg = f"📊 **{username}**\n\n💰 Số dư: {_fmt_money(balance)}"
        await update.message.reply_text(msg, parse_mode="Markdown")

# Các command game (giữ nguyên code cũ)
async def guessnumber_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id in active_games:
            del active_games[chat_id]
            
        game = GuessNumberGame(chat_id)
        active_games[chat_id] = {"type": "guessnumber", "game": game}
        
        await update.message.reply_text(f"""🎮 ĐOÁN SỐ 1-999

💡 {game.riddle}
📝 15 lần | 💰 5000đ
/hint - Gợi ý (-500đ, tối đa 4 lần)

Đoán đi!""")
    except Exception as e:
        logger.error(f"Error in guessnumber: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def quiz1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id in active_games:
            del active_games[chat_id]
        
        loading_msg = await update.message.reply_text("⏳ Đang tạo câu hỏi...")
        
        game = VietnameseQuiz1Game(chat_id)
        quiz = await game.generate_quiz()
        
        if not quiz:
            await loading_msg.edit_text("❌ Lỗi tạo câu hỏi!")
            return
        
        game.current_quiz = quiz
        active_games[chat_id] = {"type": "quiz1", "game": game}
        
        keyboard = []
        for option in quiz["options"]:
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await loading_msg.edit_text(
            f"❓ **{quiz['topic']}**\n\n{quiz['question']}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in quiz1: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def quiz2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id in active_games:
            del active_games[chat_id]
        
        loading_msg = await update.message.reply_text("⏳ Đang tạo câu hỏi...")
        
        game = VietnameseQuiz2Game(chat_id)
        quiz = await game.generate_quiz()
        
        if not quiz:
            await loading_msg.edit_text("❌ Lỗi tạo câu hỏi!")
            return
        
        game.current_quiz = quiz
        active_games[chat_id] = {"type": "quiz2", "game": game}
        
        await loading_msg.edit_text(
            f"❓ **{quiz['topic']}**\n\n{quiz['question']}\n\n💡 Trả lời ngắn gọn (1-3 từ)",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in quiz2: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def math_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id in active_games:
            del active_games[chat_id]
        
        loading_msg = await update.message.reply_text("⏳ Đang tạo bài toán...")
        
        game = MathQuizGame(chat_id)
        question = await game.generate_question()
        
        if not question:
            await loading_msg.edit_text("❌ Lỗi tạo câu hỏi!")
            return
        
        active_games[chat_id] = {"type": "math", "game": game}
        
        await loading_msg.edit_text(
            f"🧮 **TOÁN HỌC**\n\nTính: {question} = ?\n\n📝 Bạn có {game.max_attempts} lần thử",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in math: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def minigame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        user = update.effective_user
        
        if chat_id in minigame_sessions:
            await update.message.reply_text("⚠️ Đang có minigame! Dùng /stopmini để dừng.")
            return
        
        minigame_sessions[chat_id] = {
            "active": True,
            "current_game": None,
            "total_score": 0,
            "games_played": 0,
            "start_time": datetime.now(),
            "starter_id": user.id,
            "starter_name": user.username or user.first_name
        }
        
        await start_random_minigame(chat_id, context)
    except Exception as e:
        logger.error(f"Error in minigame: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

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
        f"🎲 Minigame #{session['games_played']}\nTổng điểm: {session['total_score']}\n\n⏳ Đang tải..."
    )
    
    await asyncio.sleep(1)
    
    try:
        if game_type == "guessnumber":
            game = GuessNumberGame(chat_id)
            active_games[chat_id] = {"type": "guessnumber", "game": game, "minigame": True}
            
            await context.bot.send_message(
                chat_id,
                f"""🎮 ĐOÁN SỐ 1-999

💡 {game.riddle}
📝 15 lần | 💰 5000đ
/hint - Gợi ý (-500đ, tối đa 4 lần)

Đoán đi!"""
            )
        
        elif game_type == "quiz1":
            game = VietnameseQuiz1Game(chat_id)
            quiz = await game.generate_quiz()
            
            if not quiz:
                await context.bot.send_message(chat_id, "❌ Lỗi! Chuyển game khác...")
                await asyncio.sleep(2)
                await start_random_minigame(chat_id, context)
                return
            
            game.current_quiz = quiz
            active_games[chat_id] = {"type": "quiz1", "game": game, "minigame": True}
            
            keyboard = []
            for option in quiz["options"]:
                keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id,
                f"❓ **{quiz['topic']}**\n\n{quiz['question']}",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        elif game_type == "quiz2":
            game = VietnameseQuiz2Game(chat_id)
            quiz = await game.generate_quiz()
            
            if not quiz:
                await context.bot.send_message(chat_id, "❌ Lỗi! Chuyển game khác...")
                await asyncio.sleep(2)
                await start_random_minigame(chat_id, context)
                return
            
            game.current_quiz = quiz
            active_games[chat_id] = {"type": "quiz2", "game": game, "minigame": True}
            
            await context.bot.send_message(
                chat_id,
                f"❓ **{quiz['topic']}**\n\n{quiz['question']}\n\n💡 Trả lời ngắn gọn!",
                parse_mode="Markdown"
            )
        
        elif game_type == "math":
            game = MathQuizGame(chat_id)
            question = await game.generate_question()
            
            if not question:
                await context.bot.send_message(chat_id, "❌ Lỗi! Chuyển game khác...")
                await asyncio.sleep(2)
                await start_random_minigame(chat_id, context)
                return
            
            active_games[chat_id] = {"type": "math", "game": game, "minigame": True}
            
            await context.bot.send_message(
                chat_id,
                f"🧮 **TOÁN HỌC**\n\nTính: {question} = ?\n\n📝 {game.max_attempts} lần thử",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in start_random_minigame: {e}")

async def stop_minigame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id not in minigame_sessions:
            await update.message.reply_text("❌ Không có minigame!")
            return
        
        session = minigame_sessions[chat_id]
        
        if session["total_score"] > 0:
            update_user_balance(
                session["starter_id"], 
                session["starter_name"], 
                session["total_score"], 
                "minigame"
            )
        
        msg = f"""🏁 KẾT THÚC!

👤 Người chơi: {session['starter_name']}
🎮 Đã chơi: {session['games_played']} game
💰 Tổng điểm: {session['total_score']}"""
        
        await update.message.reply_text(msg)
        
        del minigame_sessions[chat_id]
        if chat_id in active_games:
            del active_games[chat_id]
    except Exception as e:
        logger.error(f"Error in stopmini: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
            await update.message.reply_text("❌ Không trong game đoán số!")
            return
            
        game = active_games[chat_id]["game"]
        await update.message.reply_text(game.get_hint())
    except Exception as e:
        logger.error(f"Error in hint: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        data = query.data
        chat_id = update.effective_chat.id
        user = update.effective_user
        username = user.username or user.first_name
        
        if data.startswith("quiz_") and chat_id in active_games:
            game_info = active_games[chat_id]
            
            if game_info["type"] == "quiz1":
                game = game_info["game"]
                quiz = game.current_quiz
                answer = data.split("_")[1]
                
                if answer == quiz["correct"]:
                    points = 300
                    result = f"✅ Chính xác! (+{points}đ)\n\n{quiz['explanation']}"
                    
                    if game_info.get("minigame") and chat_id in minigame_sessions:
                        minigame_sessions[chat_id]["total_score"] += points
                    else:
                        update_user_balance(user.id, username, points, "quiz1")
                else:
                    result = f"❌ Sai rồi! Đáp án: {quiz['correct']}\n\n{quiz['explanation']}"
                
                await query.message.edit_text(result)
                
                del active_games[chat_id]
                
                if game_info.get("minigame") and chat_id in minigame_sessions:
                    await asyncio.sleep(3)
                    await start_random_minigame(chat_id, context)
    except Exception as e:
        logger.error(f"Error in button callback: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message.text
        chat_id = update.effective_chat.id
        user = update.effective_user
        username = user.username or user.first_name
        
        # Handle active games
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
                
                del active_games[chat_id]
                
                if "Chính xác" in response:
                    if is_minigame and chat_id in minigame_sessions:
                        minigame_sessions[chat_id]["total_score"] += 300
                    else:
                        update_user_balance(user.id, username, 300, "quiz2")
                
                if is_minigame and chat_id in minigame_sessions:
                    await asyncio.sleep(3)
                    await start_random_minigame(chat_id, context)
                        
            elif game_info["type"] == "math":
                try:
                    answer = int(message)
                    is_correct, response = game.check_answer(answer)
                    await update.message.reply_text(response)
                    
                    if is_correct:
                        if is_minigame and chat_id in minigame_sessions:
                            minigame_sessions[chat_id]["total_score"] += game.score
                        else:
                            update_user_balance(user.id, username, game.score, "math")
                    
                    if is_correct or game.attempts >= game.max_attempts:
                        del active_games[chat_id]
                        
                        if is_minigame and chat_id in minigame_sessions:
                            await asyncio.sleep(3)
                            await start_random_minigame(chat_id, context)
                            
                except ValueError:
                    pass
            return
        
        # Chat AI
        if chat_id not in chat_history:
            chat_history[chat_id] = []
            
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
        else:
            await update.message.reply_text("😊 Mình đang nghĩ... Thử lại nhé!")
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

async def post_init(application: Application) -> None:
    logger.info("Bot started successfully!")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = post_init
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("minigame", minigame_cmd))
    application.add_handler(CommandHandler("stopmini", stop_minigame_cmd))
    application.add_handler(CommandHandler("guessnumber", guessnumber_cmd))
    application.add_handler(CommandHandler("quiz1", quiz1_cmd))
    application.add_handler(CommandHandler("quiz2", quiz2_cmd))
    application.add_handler(CommandHandler("math", math_cmd))
    application.add_handler(CommandHandler("hint", hint_command))
    application.add_handler(CommandHandler("bal", bal_cmd))
    application.add_handler(CommandHandler("top", top_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    
    # Callbacks
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot is running! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
