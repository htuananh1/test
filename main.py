import os
import random
import asyncio
import logging
import requests
import json
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from github import Github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-120b")
CLAUDE_MODEL = "anthropic/claude-3.7-sonnet"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "htuananh1/Data-manager"

START_BALANCE = 1000
AUTO_MINIGAME_INTERVAL = 3600
GAME_TIMEOUT = 300

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class GitHubStorage:
    def __init__(self, token: str, repo_name: str):
        try:
            self.g = Github(token)
            self.repo = self.g.get_repo(repo_name)
            self.branch = "main"
            self._pending_updates = {}
            self._last_batch_save = datetime.now()
            logger.info("GitHub storage initialized successfully")
        except Exception as e:
            logger.error(f"Failed to init GitHub storage: {e}")
            raise
        
    def _get_file_content(self, path: str) -> Optional[dict]:
        try:
            file = self.repo.get_contents(path, ref=self.branch)
            content = base64.b64decode(file.content).decode('utf-8')
            data = json.loads(content)
            return data
        except Exception as e:
            logger.warning(f"File {path} not found or error: {e}")
            return None
    
    def _save_file(self, path: str, data: dict, message: str):
        try:
            content = json.dumps(data, ensure_ascii=False, indent=2)
            
            try:
                file = self.repo.get_contents(path, ref=self.branch)
                self.repo.update_file(path, message, content, file.sha, self.branch)
                logger.info(f"Updated file: {path}")
            except:
                self.repo.create_file(path, message, content, self.branch)
                logger.info(f"Created file: {path}")
                
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")
    
    def queue_update(self, update_type: str, data: dict):
        if update_type not in self._pending_updates:
            self._pending_updates[update_type] = []
        self._pending_updates[update_type].append(data)
    
    async def batch_save(self):
        if not self._pending_updates:
            return
            
        timestamp = datetime.now().isoformat()
        
        if "scores" in self._pending_updates:
            scores_data = self._get_file_content("data/scores.json") or {"users": {}}
            
            for update in self._pending_updates["scores"]:
                user_key = str(update["user_id"])
                
                if user_key not in scores_data["users"]:
                    scores_data["users"][user_key] = {
                        "user_id": update["user_id"],
                        "username": update["username"],
                        "balance": START_BALANCE,
                        "total_earned": 0,
                        "games_played": {},
                        "created_at": timestamp,
                        "last_updated": timestamp
                    }
                
                user = scores_data["users"][user_key]
                user["balance"] += update["amount"]
                user["username"] = update["username"]
                user["last_updated"] = timestamp
                
                if update["amount"] > 0:
                    user["total_earned"] = user.get("total_earned", 0) + update["amount"]
                    if update.get("game_type"):
                        if "games_played" not in user:
                            user["games_played"] = {}
                        game_type = update["game_type"]
                        user["games_played"][game_type] = user["games_played"].get(game_type, 0) + 1
            
            self._save_file("data/scores.json", scores_data, f"Batch update scores at {timestamp}")
        
        if "quiz1" in self._pending_updates:
            quiz1_data = self._get_file_content("data/quiz1_pool.json") or {"questions": []}
            
            for quiz in self._pending_updates["quiz1"]:
                duplicate = False
                for existing in quiz1_data["questions"]:
                    if existing.get("question") == quiz.get("question"):
                        duplicate = True
                        break
                if not duplicate:
                    quiz1_data["questions"].append(quiz)
            
            quiz1_data["total"] = len(quiz1_data["questions"])
            quiz1_data["last_updated"] = timestamp
            
            self._save_file("data/quiz1_pool.json", quiz1_data, f"Batch update quiz1 at {timestamp}")
        
        if "quiz2" in self._pending_updates:
            quiz2_data = self._get_file_content("data/quiz2_pool.json") or {"questions": []}
            
            for quiz in self._pending_updates["quiz2"]:
                duplicate = False
                for existing in quiz2_data["questions"]:
                    if existing.get("question") == quiz.get("question"):
                        duplicate = True
                        break
                if not duplicate:
                    quiz2_data["questions"].append(quiz)
            
            quiz2_data["total"] = len(quiz2_data["questions"])
            quiz2_data["last_updated"] = timestamp
            
            self._save_file("data/quiz2_pool.json", quiz2_data, f"Batch update quiz2 at {timestamp}")
        
        if "math" in self._pending_updates:
            math_data = self._get_file_content("data/math_pool.json") or {"questions": []}
            
            for math in self._pending_updates["math"]:
                duplicate = False
                for existing in math_data["questions"]:
                    if existing.get("question") == math.get("question"):
                        duplicate = True
                        break
                if not duplicate:
                    math_data["questions"].append(math)
            
            math_data["total"] = len(math_data["questions"])
            math_data["last_updated"] = timestamp
            
            self._save_file("data/math_pool.json", math_data, f"Batch update math at {timestamp}")
        
        self._pending_updates = {}
        self._last_batch_save = datetime.now()
        logger.info(f"Batch save completed at {timestamp}")
    
    def get_user_balance(self, user_id: int) -> int:
        try:
            data = self._get_file_content("data/scores.json") or {"users": {}}
            user_data = data.get("users", {}).get(str(user_id), {})
            return user_data.get("balance", START_BALANCE)
        except:
            return START_BALANCE
    
    def update_user_balance(self, user_id: int, username: str, amount: int, game_type: str = None):
        self.queue_update("scores", {
            "user_id": user_id,
            "username": username,
            "amount": amount,
            "game_type": game_type
        })
    
    def get_leaderboard_direct(self, limit: int = 10) -> List[tuple]:
        try:
            data = self._get_file_content("data/scores.json")
            if not data or "users" not in data:
                return []
                
            users = []
            for user_data in data["users"].values():
                username = user_data.get("username", "Unknown")
                total_earned = user_data.get("total_earned", 0)
                if total_earned > 0:
                    users.append((username, total_earned))
                    
            users.sort(key=lambda x: x[1], reverse=True)
            return users[:limit]
        except Exception as e:
            logger.error(f"Failed to get leaderboard: {e}")
            return []
    
    def get_user_stats_direct(self, user_id: int) -> dict:
        try:
            data = self._get_file_content("data/scores.json")
            if not data or "users" not in data:
                return {
                    'balance': START_BALANCE,
                    'total_earned': 0,
                    'games_played': {}
                }
                
            user_data = data["users"].get(str(user_id), {})
            
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
        return []
    
    def add_quiz1(self, quiz: dict):
        self.queue_update("quiz1", quiz)
    
    def get_quiz2_pool(self) -> List[dict]:
        data = self._get_file_content("data/quiz2_pool.json")
        if data and "questions" in data:
            return data["questions"]
        return []
    
    def add_quiz2(self, quiz: dict):
        self.queue_update("quiz2", quiz)
    
    def get_math_pool(self) -> List[dict]:
        data = self._get_file_content("data/math_pool.json")
        if data and "questions" in data:
            return data["questions"]
        return []
    
    def add_math(self, math: dict):
        self.queue_update("math", math)
    
    def save_chat_info(self, chat_id: int, chat_type: str, title: str = None):
        data = self._get_file_content("data/chats.json") or {"chats": []}
        
        for i, chat in enumerate(data["chats"]):
            if chat.get("id") == chat_id:
                data["chats"][i] = {
                    "id": chat_id,
                    "type": chat_type,
                    "title": title,
                    "updated": datetime.now().isoformat()
                }
                self._save_file("data/chats.json", data, f"Update chat: {chat_id}")
                return
        
        data["chats"].append({
            "id": chat_id,
            "type": chat_type,
            "title": title,
            "updated": datetime.now().isoformat()
        })
        self._save_file("data/chats.json", data, f"Add chat: {chat_id}")
    
    def get_all_groups(self) -> List[dict]:
        data = self._get_file_content("data/chats.json")
        if not data or "chats" not in data:
            return []
        
        groups = []
        for chat in data["chats"]:
            if chat.get("type") in ["group", "supergroup"]:
                groups.append(chat)
        return groups

try:
    storage = GitHubStorage(GITHUB_TOKEN, GITHUB_REPO)
except Exception as e:
    logger.error(f"Critical error initializing storage: {e}")
    storage = None

active_games: Dict[int, dict] = {}
autominigame_sessions: Dict[int, dict] = {}
auto_minigame_enabled: Dict[int, bool] = {}
game_messages: Dict[int, List[int]] = {}
game_timeouts: Dict[int, asyncio.Task] = {}

def _fmt_money(x: int) -> str:
    return f"{x:,}".replace(",", ".")

def get_user_balance(user_id: int) -> int:
    if storage:
        return storage.get_user_balance(user_id)
    return START_BALANCE

def update_user_balance(user_id: int, username: str, amount: int, game_type: str = None):
    try:
        if storage:
            storage.update_user_balance(user_id, username, amount, game_type)
            logger.info(f"Balance queued for {username}: {amount:+d} from {game_type}")
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
        difficulty = random.choice(["easy", "medium", "hard"])
        
        if difficulty == "easy":
            a = random.randint(10, 50)
            b = random.randint(10, 50)
            op = random.choice(["+", "-"])
            if op == "+":
                self.current_question = f"{a} + {b}"
                self.current_answer = a + b
            else:
                if a < b:
                    a, b = b, a
                self.current_question = f"{a} - {b}"
                self.current_answer = a - b
                
        elif difficulty == "medium":
            choice = random.choice(["multiply", "multi_add"])
            if choice == "multiply":
                a = random.randint(5, 20)
                b = random.randint(5, 20)
                self.current_question = f"{a} × {b}"
                self.current_answer = a * b
            else:
                a = random.randint(20, 50)
                b = random.randint(10, 30)
                c = random.randint(10, 30)
                self.current_question = f"{a} + {b} + {c}"
                self.current_answer = a + b + c
                
        else:
            choice = random.choice(["multi_op", "parentheses", "division"])
            if choice == "multi_op":
                a = random.randint(20, 50)
                b = random.randint(10, 30)
                c = random.randint(5, 15)
                self.current_question = f"{a} + {b} - {c}"
                self.current_answer = a + b - c
            elif choice == "parentheses":
                a = random.randint(5, 15)
                b = random.randint(5, 15)
                c = random.randint(2, 10)
                self.current_question = f"({a} + {b}) × {c}"
                self.current_answer = (a + b) * c
            else:
                divisor = random.randint(2, 10)
                quotient = random.randint(5, 20)
                dividend = divisor * quotient
                extra = random.randint(10, 50)
                self.current_question = f"{dividend} ÷ {divisor} + {extra}"
                self.current_answer = quotient + extra
        
        if storage:
            storage.add_math({
                "question": self.current_question,
                "answer": self.current_answer,
                "difficulty": difficulty,
                "created_at": datetime.now().isoformat()
            })
        
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
        topics = [
            "Bóng đá thế giới", 
            "Công nghệ và khoa học", 
            "Địa danh nổi tiếng thế giới", 
            "Động vật và thực vật",
            "Câu đố dân gian và logic", 
            "Nghệ thuật và giải trí",
            "Lịch sử thế giới",
            "Thể thao Olympic"
        ]
        topic = random.choice(topics)
        difficulty = random.choice(["trung bình", "khó", "cực khó"])
        
        prompt = f"""Tạo câu hỏi trắc nghiệm về {topic} với độ khó {difficulty}.

YÊU CẦU BẮT BUỘC:
1. Câu hỏi PHẢI 100% chính xác, có thể kiểm chứng
2. 4 lựa chọn với CHỈ 1 đáp án đúng
3. Câu hỏi bằng tiếng Việt chuẩn
4. Nếu độ khó "cực khó", câu hỏi phải thật sự khó và chi tiết
5. Tránh những câu hỏi quá phổ biến

Trả về JSON tiếng Việt:
{{
  "topic": "{topic}",
  "question": "câu hỏi bằng tiếng Việt",
  "options": ["A. lựa chọn", "B. lựa chọn", "C. lựa chọn", "D. lựa chọn"],
  "answer": "A hoặc B hoặc C hoặc D",
  "explain": "giải thích chi tiết bằng tiếng Việt"
}}"""

        messages = [
            {"role": "system", "content": "Bạn là chuyên gia tạo câu hỏi đố vui quốc tế. Tạo câu hỏi chính xác 100%, phù hợp độ khó được yêu cầu."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await call_api(messages, model=CLAUDE_MODEL, max_tokens=500)
            
            if response:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                
                if json_start != -1:
                    json_str = response[json_start:json_end]
                    data = json.loads(json_str)
                    
                    quiz = {
                        "topic": data.get("topic", topic),
                        "question": data.get("question", ""),
                        "options": data.get("options", []),
                        "correct": data.get("answer", "")[0].upper() if data.get("answer") else "",
                        "explanation": data.get("explain", ""),
                        "difficulty": difficulty,
                        "created_at": datetime.now().isoformat()
                    }
                    
                    if quiz["question"] and len(quiz["options"]) == 4:
                        if storage:
                            storage.add_quiz1(quiz)
                        return quiz
        except Exception as e:
            logger.error(f"Error generating quiz1: {e}")
        
        if storage:
            pool = storage.get_quiz1_pool()
            if pool:
                return random.choice(pool)
        
        return None

class VietnameseQuiz2Game:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.current_quiz = None
        
    async def generate_quiz(self) -> dict:
        topics = [
            "Bóng đá thế giới",
            "Công nghệ hiện đại",
            "Địa danh nổi tiếng",
            "Động vật và thực vật", 
            "Câu đố logic",
            "Điện ảnh và âm nhạc",
            "Khoa học vũ trụ",
            "Ẩm thực thế giới"
        ]
        topic = random.choice(topics)
        difficulty = random.choice(["trung bình", "khó", "cực khó"])
        
        prompt = f"""Tạo câu hỏi về {topic} với độ khó {difficulty}.

YÊU CẦU BẮT BUỘC:
1. Câu hỏi PHẢI 100% chính xác
2. Câu trả lời NGẮN (1-3 từ tối đa)
3. Đáp án phải rõ ràng, không mơ hồ
4. Câu hỏi bằng tiếng Việt chuẩn
5. Nếu độ khó "cực khó", hỏi về chi tiết ít người biết

Trả về JSON tiếng Việt:
{{
  "topic": "{topic}",
  "question": "câu hỏi tiếng Việt (yêu cầu trả lời ngắn)",
  "answer": "đáp án ngắn tiếng Việt (1-3 từ)",
  "explanation": "giải thích ngắn gọn tiếng Việt"
}}"""

        messages = [
            {"role": "system", "content": "Bạn là chuyên gia tạo câu đố quốc tế. Tạo câu hỏi có đáp án NGẮN, CHÍNH XÁC."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await call_api(messages, model=CLAUDE_MODEL, max_tokens=300)
            
            if response:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                
                if json_start != -1:
                    json_str = response[json_start:json_end]
                    data = json.loads(json_str)
                    
                    quiz = {
                        "topic": data.get("topic", topic),
                        "question": data.get("question", ""),
                        "answer": data.get("answer", ""),
                        "explanation": data.get("explanation", ""),
                        "difficulty": difficulty,
                        "created_at": datetime.now().isoformat()
                    }
                    
                    if quiz["question"] and quiz["answer"]:
                        if storage:
                            storage.add_quiz2(quiz)
                        return quiz
        except Exception as e:
            logger.error(f"Error generating quiz2: {e}")
        
        if storage:
            pool = storage.get_quiz2_pool()
            if pool:
                return random.choice(pool)
        
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

async def delete_old_messages(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    if chat_id not in game_messages:
        return
        
    messages = game_messages[chat_id]
    if len(messages) > 5:
        to_delete = messages[:-5]
        for msg_id in to_delete:
            try:
                await context.bot.delete_message(chat_id, msg_id)
            except:
                pass
        game_messages[chat_id] = messages[-5:]

async def add_game_message(chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE):
    if chat_id not in game_messages:
        game_messages[chat_id] = []
    game_messages[chat_id].append(message_id)
    await delete_old_messages(chat_id, context)

async def game_timeout_handler(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(GAME_TIMEOUT)
    
    if chat_id in active_games:
        del active_games[chat_id]
        
    if chat_id in autominigame_sessions and autominigame_sessions[chat_id]["active"]:
        msg = await context.bot.send_message(
            chat_id,
            "⏰ Hết giờ! Không ai chơi trong 5 phút.\n\n"
            "🎲 Đang chuyển sang game mới...",
            parse_mode="Markdown"
        )
        await add_game_message(chat_id, msg.message_id, context)
        
        if chat_id in game_timeouts:
            del game_timeouts[chat_id]
        
        await asyncio.sleep(2)
        await start_random_autominigame(chat_id, context)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        username = user.username or user.first_name
        balance = get_user_balance(user.id)
        
        chat = update.effective_chat
        if storage:
            storage.save_chat_info(chat.id, chat.type, chat.title)
        
        message = f"""👋 Xin chào {username}! Mình là Linh Bot!

💰 Số dư của bạn: {_fmt_money(balance)}

🎮 **Minigame:**
/autominigame - Bật/tắt minigame tự động
⚡ Ai trả lời đúng sẽ được điểm!

📝 **Chơi riêng lẻ:**
/guessnumber - Đoán số
/quiz1 - Quiz trắc nghiệm
/quiz2 - Quiz trả lời
/math - Toán học

📊 **Thông tin:**
/top - Bảng xếp hạng
/bal - Xem số dư
/stats - Thống kê cá nhân

💬 Chat riêng với mình để trò chuyện!"""
        
        await update.message.reply_text(message, parse_mode="Markdown")
        logger.info(f"Start command successful for user {user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text(
            "👋 Xin chào! Mình là Linh Bot!\n\n"
            "🎮 /autominigame - Minigame tự động\n"
            "📊 /top - Bảng xếp hạng\n"
            "💰 /bal - Xem số dư"
        )

async def autominigame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        chat = update.effective_chat
        
        if chat.type not in ["group", "supergroup"]:
            await update.message.reply_text("⚠️ Chỉ sử dụng được trong nhóm!")
            return
        
        if chat_id not in auto_minigame_enabled:
            auto_minigame_enabled[chat_id] = True
        else:
            auto_minigame_enabled[chat_id] = not auto_minigame_enabled[chat_id]
        
        status = "BẬT" if auto_minigame_enabled[chat_id] else "TẮT"
        
        if auto_minigame_enabled[chat_id]:
            if chat_id not in autominigame_sessions:
                autominigame_sessions[chat_id] = {
                    "active": True,
                    "current_game": None,
                    "games_played": 0,
                    "start_time": datetime.now()
                }
                await start_random_autominigame(chat_id, context)
        else:
            if chat_id in autominigame_sessions:
                del autominigame_sessions[chat_id]
            if chat_id in active_games:
                del active_games[chat_id]
            if chat_id in game_timeouts:
                game_timeouts[chat_id].cancel()
                del game_timeouts[chat_id]
        
        await update.message.reply_text(
            f"🎮 Autominigame đã được **{status}**\n\n"
            f"{'Minigame sẽ tự động chạy!' if auto_minigame_enabled[chat_id] else 'Đã dừng autominigame!'}",
            parse_mode="Markdown"
        )
        
        if storage:
            storage.save_chat_info(chat.id, chat.type, chat.title)
            
    except Exception as e:
        logger.error(f"Error in autominigame: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

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
            
        leaderboard = storage.get_leaderboard_direct()
        
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
            
        data = storage.get_user_stats_direct(user.id)
        
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
                "math": "Toán học"
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

async def guessnumber_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id not in autominigame_sessions:
            if chat_id in active_games:
                del active_games[chat_id]
            
            game = GuessNumberGame(chat_id)
            active_games[chat_id] = {"type": "guessnumber", "game": game}
            
            await update.message.reply_text(f"""🎮 ĐOÁN SỐ 1-999

💡 {game.riddle}
📝 15 lần | 💰 5000đ
/hint - Gợi ý (-500đ, tối đa 4 lần)

Đoán đi!""")
        else:
            await update.message.reply_text("⚠️ Đang trong autominigame!")
    except Exception as e:
        logger.error(f"Error in guessnumber: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def quiz1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id not in autominigame_sessions:
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
        else:
            await update.message.reply_text("⚠️ Đang trong autominigame!")
    except Exception as e:
        logger.error(f"Error in quiz1: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def quiz2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id not in autominigame_sessions:
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
        else:
            await update.message.reply_text("⚠️ Đang trong autominigame!")
    except Exception as e:
        logger.error(f"Error in quiz2: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def math_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id not in autominigame_sessions:
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
        else:
            await update.message.reply_text("⚠️ Đang trong autominigame!")
    except Exception as e:
        logger.error(f"Error in math: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def start_random_autominigame(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        if chat_id not in autominigame_sessions or not autominigame_sessions[chat_id]["active"]:
            return
        
        if chat_id in active_games:
            del active_games[chat_id]
        
        if chat_id in game_timeouts:
            game_timeouts[chat_id].cancel()
        
        games = ["guessnumber", "quiz1", "quiz2", "math"]
        game_type = random.choice(games)
        
        session = autominigame_sessions[chat_id]
        session["current_game"] = game_type
        session["games_played"] += 1
        
        game_names = {
            "guessnumber": "🎯 Đoán Số",
            "quiz1": "📝 Quiz Trắc Nghiệm",
            "quiz2": "✍️ Quiz Trả Lời",
            "math": "🧮 Toán Học"
        }
        
        msg = await context.bot.send_message(
            chat_id, 
            f"🎲 **Autominigame #{session['games_played']}**\n"
            f"🎮 Trò chơi: {game_names.get(game_type, game_type)}\n"
            f"⏰ Tự chuyển game sau 5 phút nếu không ai chơi\n\n"
            f"⏳ Đang tải...",
            parse_mode="Markdown"
        )
        await add_game_message(chat_id, msg.message_id, context)
        
        await asyncio.sleep(1)
        
        if game_type == "guessnumber":
            game = GuessNumberGame(chat_id)
            active_games[chat_id] = {"type": "guessnumber", "game": game, "autominigame": True}
            
            msg = await context.bot.send_message(
                chat_id,
                f"""🎮 ĐOÁN SỐ 1-999

💡 {game.riddle}
📝 15 lần | 💰 5000đ
/hint - Gợi ý (-500đ, tối đa 4 lần)

🏆 Ai đoán đúng sẽ được điểm!"""
            )
            await add_game_message(chat_id, msg.message_id, context)
        
        elif game_type == "quiz1":
            game = VietnameseQuiz1Game(chat_id)
            quiz = await game.generate_quiz()
            
            if not quiz:
                msg = await context.bot.send_message(chat_id, "❌ Lỗi! Chuyển game khác...")
                await add_game_message(chat_id, msg.message_id, context)
                await asyncio.sleep(2)
                await start_random_autominigame(chat_id, context)
                return
            
            game.current_quiz = quiz
            active_games[chat_id] = {"type": "quiz1", "game": game, "autominigame": True}
            
            keyboard = []
            for option in quiz["options"]:
                keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            difficulty_icon = {"trung bình": "⭐", "khó": "⭐⭐", "cực khó": "⭐⭐⭐"}
            
            msg = await context.bot.send_message(
                chat_id,
                f"❓ **{quiz['topic']}** {difficulty_icon.get(quiz.get('difficulty', 'trung bình'), '')}\n\n"
                f"{quiz['question']}\n\n"
                f"🏆 Ai trả lời đúng sẽ được 300 điểm!",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            await add_game_message(chat_id, msg.message_id, context)
        
        elif game_type == "quiz2":
            game = VietnameseQuiz2Game(chat_id)
            quiz = await game.generate_quiz()
            
            if not quiz:
                msg = await context.bot.send_message(chat_id, "❌ Lỗi! Chuyển game khác...")
                await add_game_message(chat_id, msg.message_id, context)
                await asyncio.sleep(2)
                await start_random_autominigame(chat_id, context)
                return
            
            game.current_quiz = quiz
            active_games[chat_id] = {"type": "quiz2", "game": game, "autominigame": True}
            
            difficulty_icon = {"trung bình": "⭐", "khó": "⭐⭐", "cực khó": "⭐⭐⭐"}
            
            msg = await context.bot.send_message(
                chat_id,
                f"❓ **{quiz['topic']}** {difficulty_icon.get(quiz.get('difficulty', 'trung bình'), '')}\n\n"
                f"{quiz['question']}\n\n"
                f"💡 Trả lời ngắn gọn!\n"
                f"🏆 Ai trả lời đúng sẽ được 300 điểm!",
                parse_mode="Markdown"
            )
            await add_game_message(chat_id, msg.message_id, context)
        
        elif game_type == "math":
            game = MathQuizGame(chat_id)
            question = await game.generate_question()
            
            if not question:
                msg = await context.bot.send_message(chat_id, "❌ Lỗi! Chuyển game khác...")
                await add_game_message(chat_id, msg.message_id, context)
                await asyncio.sleep(2)
                await start_random_autominigame(chat_id, context)
                return
            
            active_games[chat_id] = {"type": "math", "game": game, "autominigame": True}
            
            msg = await context.bot.send_message(
                chat_id,
                f"🧮 **TOÁN HỌC**\n\nTính: {question} = ?\n\n"
                f"📝 {game.max_attempts} lần thử\n"
                f"🏆 Ai trả lời đúng sẽ được điểm!",
                parse_mode="Markdown"
            )
            await add_game_message(chat_id, msg.message_id, context)
        
        game_timeouts[chat_id] = asyncio.create_task(game_timeout_handler(chat_id, context))
        
    except Exception as e:
        logger.error(f"Error in start_random_autominigame: {e}")

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
            await update.message.reply_text("❌ Không trong game đoán số!")
            return
            
        game = active_games[chat_id]["game"]
        response = game.get_hint()
        msg = await update.message.reply_text(response)
        
        if active_games[chat_id].get("autominigame"):
            await add_game_message(chat_id, msg.message_id, context)
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
                    result = f"✅ **{username}** trả lời chính xác! (+{points}đ)\n\n{quiz['explanation']}"
                    
                    update_user_balance(user.id, username, points, "quiz1")
                else:
                    result = f"❌ Sai rồi! Đáp án: {quiz['correct']}\n\n{quiz['explanation']}"
                
                msg = await context.bot.send_message(chat_id, result, parse_mode="Markdown")
                
                if game_info.get("autominigame"):
                    await add_game_message(chat_id, msg.message_id, context)
                
                del active_games[chat_id]
                
                if chat_id in game_timeouts:
                    game_timeouts[chat_id].cancel()
                    del game_timeouts[chat_id]
                
                if game_info.get("autominigame") and chat_id in autominigame_sessions:
                    await asyncio.sleep(3)
                    await start_random_autominigame(chat_id, context)
    except Exception as e:
        logger.error(f"Error in button callback: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message.text
        chat_id = update.effective_chat.id
        user = update.effective_user
        username = user.username or user.first_name
        
        chat = update.effective_chat
        if storage and chat.type in ["group", "supergroup"]:
            storage.save_chat_info(chat.id, chat.type, chat.title)
        
        message_handled = False
        
        if chat_id in active_games:
            game_info = active_games[chat_id]
            game = game_info["game"]
            is_autominigame = game_info.get("autominigame", False)
            
            if game_info["type"] == "guessnumber":
                try:
                    guess = int(message)
                    if 1 <= guess <= 999:
                        message_handled = True
                        is_finished, response = game.make_guess(guess)
                        
                        if is_finished and "Đúng" in response:
                            response = f"🎉 **{username}** {response}"
                            update_user_balance(user.id, username, game.score, "guessnumber")
                        
                        msg = await update.message.reply_text(response, parse_mode="Markdown")
                        
                        if is_autominigame:
                            await add_game_message(chat_id, msg.message_id, context)
                        
                        if is_finished:
                            del active_games[chat_id]
                            
                            if chat_id in game_timeouts:
                                game_timeouts[chat_id].cancel()
                                del game_timeouts[chat_id]
                            
                            if is_autominigame and chat_id in autominigame_sessions:
                                await asyncio.sleep(3)
                                await start_random_autominigame(chat_id, context)
                    else:
                        message_handled = True
                        msg = await update.message.reply_text("❌ Từ 1-999 thôi!")
                        if is_autominigame:
                            await add_game_message(chat_id, msg.message_id, context)
                except ValueError:
                    pass
                    
            elif game_info["type"] == "quiz2":
                message_handled = True
                is_finished, response = game.check_answer(message)
                
                if "Chính xác" in response:
                    response = f"✅ **{username}** trả lời chính xác! +300 điểm\n\n{game.current_quiz['explanation']}"
                    update_user_balance(user.id, username, 300, "quiz2")
                
                msg = await update.message.reply_text(response, parse_mode="Markdown")
                
                if is_autominigame:
                    await add_game_message(chat_id, msg.message_id, context)
                
                del active_games[chat_id]
                
                if chat_id in game_timeouts:
                    game_timeouts[chat_id].cancel()
                    del game_timeouts[chat_id]
                
                if is_autominigame and chat_id in autominigame_sessions:
                    await asyncio.sleep(3)
                    await start_random_autominigame(chat_id, context)
                        
            elif game_info["type"] == "math":
                try:
                    answer = int(message)
                    message_handled = True
                    is_correct, response = game.check_answer(answer)
                    
                    if is_correct:
                        response = f"✅ **{username}** {response}"
                        update_user_balance(user.id, username, game.score, "math")
                    
                    msg = await update.message.reply_text(response, parse_mode="Markdown")
                    
                    if is_autominigame:
                        await add_game_message(chat_id, msg.message_id, context)
                    
                    if is_correct or game.attempts >= game.max_attempts:
                        del active_games[chat_id]
                        
                        if chat_id in game_timeouts:
                            game_timeouts[chat_id].cancel()
                            del game_timeouts[chat_id]
                        
                        if is_autominigame and chat_id in autominigame_sessions:
                            await asyncio.sleep(3)
                            await start_random_autominigame(chat_id, context)
                            
                except ValueError:
                    pass
            
            if message_handled:
                return
        
        # Chat AI - chỉ hoạt động ở chat riêng
        if chat.type == "private":
            messages = [
                {"role": "system", "content": "Bạn là Linh - cô gái Việt Nam vui vẻ, thân thiện. Trả lời ngắn gọn."},
                {"role": "user", "content": message}
            ]
            
            response = await call_api(messages, max_tokens=300)
            
            if response:
                await update.message.reply_text(response)
            else:
                await update.message.reply_text("😊 Mình đang nghĩ... Thử lại nhé!")
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

async def periodic_batch_save(application: Application):
    while True:
        await asyncio.sleep(60)
        try:
            if storage:
                await storage.batch_save()
        except Exception as e:
            logger.error(f"Batch save error: {e}")

async def auto_minigame_scheduler(application: Application):
    while True:
        await asyncio.sleep(AUTO_MINIGAME_INTERVAL)
        try:
            if not storage:
                continue
                
            groups = storage.get_all_groups()
            
            for group in groups:
                chat_id = group.get("id")
                if chat_id and auto_minigame_enabled.get(chat_id, False):
                    if chat_id not in autominigame_sessions:
                        autominigame_sessions[chat_id] = {
                            "active": True,
                            "current_game": None,
                            "games_played": 0,
                            "start_time": datetime.now()
                        }
                        
                        msg = await application.bot.send_message(
                            chat_id,
                            "🎮 **AUTOMINIGAME TỰ ĐỘNG BẮT ĐẦU!**\n\nCùng chơi game nào! 🎉",
                            parse_mode="Markdown"
                        )
                        
                        if chat_id not in game_messages:
                            game_messages[chat_id] = []
                        game_messages[chat_id].append(msg.message_id)
                        
                        await start_random_autominigame(chat_id, application)
                        
                        logger.info(f"Started auto minigame in group {chat_id}")
                        
        except Exception as e:
            logger.error(f"Auto minigame scheduler error: {e}")

async def post_init(application: Application) -> None:
    asyncio.create_task(periodic_batch_save(application))
    asyncio.create_task(auto_minigame_scheduler(application))
    logger.info("Bot started successfully!")

async def post_shutdown(application: Application) -> None:
    if storage:
        await storage.batch_save()
    logger.info("Bot shutdown - data saved!")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("autominigame", autominigame_cmd))
    application.add_handler(CommandHandler("guessnumber", guessnumber_cmd))
    application.add_handler(CommandHandler("quiz1", quiz1_cmd))
    application.add_handler(CommandHandler("quiz2", quiz2_cmd))
    application.add_handler(CommandHandler("math", math_cmd))
    application.add_handler(CommandHandler("hint", hint_command))
    application.add_handler(CommandHandler("bal", bal_cmd))
    application.add_handler(CommandHandler("top", top_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot is running! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
