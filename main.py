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

# Pool câu hỏi mặc định khi API lỗi
DEFAULT_QUIZ1_POOL = [
    {
        "topic": "Lịch sử Việt Nam",
        "question": "Vua nào đã đánh thắng quân Nguyên Mông 3 lần?",
        "options": ["A. Trần Nhân Tông", "B. Lý Thái Tông", "C. Lê Lợi", "D. Quang Trung"],
        "correct": "A",
        "explanation": "Trần Nhân Tông là vị vua đã lãnh đạo nhân dân đánh thắng quân Nguyên Mông 3 lần vào các năm 1258, 1285 và 1288."
    },
    {
        "topic": "Địa lý Việt Nam",
        "question": "Đỉnh núi cao nhất Việt Nam là?",
        "options": ["A. Phan Xi Păng", "B. Ngọc Linh", "C. Bà Đen", "D. Bà Nà"],
        "correct": "A",
        "explanation": "Phan Xi Păng cao 3.143m, là đỉnh núi cao nhất Việt Nam, nằm ở Lào Cai."
    },
    {
        "topic": "Ẩm thực Việt Nam",
        "question": "Món ăn nào được CNN bình chọn là một trong những món ăn ngon nhất thế giới?",
        "options": ["A. Phở", "B. Bún bò", "C. Bánh mì", "D. Cả A và C"],
        "correct": "D",
        "explanation": "Cả Phở và Bánh mì Việt Nam đều được CNN bình chọn trong danh sách món ăn ngon nhất thế giới."
    }
]

DEFAULT_QUIZ2_POOL = [
    {
        "topic": "Lịch sử Việt Nam",
        "question": "Thủ đô của Việt Nam thời Lý là gì?",
        "answer": "Thăng Long",
        "explanation": "Thăng Long (nay là Hà Nội) là thủ đô của Việt Nam từ năm 1010 dưới triều Lý."
    },
    {
        "topic": "Địa lý Việt Nam",
        "question": "Sông dài nhất Việt Nam là sông nào?",
        "answer": "Sông Hồng",
        "explanation": "Sông Hồng dài khoảng 1.149 km (tính cả phần chảy qua Trung Quốc), là sông dài nhất chảy qua Việt Nam."
    },
    {
        "topic": "Văn hóa Việt Nam",
        "question": "Nhạc cụ dân tộc độc đáo của Tây Nguyên là gì?",
        "answer": "Đàn T'rưng",
        "explanation": "Đàn T'rưng là nhạc cụ truyền thống đặc trưng của các dân tộc Tây Nguyên."
    }
]

DEFAULT_MATH_POOL = [
    {"question": "25 + 37", "answer": 62},
    {"question": "84 - 29", "answer": 55},
    {"question": "12 × 8", "answer": 96},
    {"question": "144 ÷ 12", "answer": 12},
    {"question": "45 + 78 - 23", "answer": 100},
    {"question": "15 × 6 + 10", "answer": 100},
    {"question": "200 - 75 + 25", "answer": 150},
    {"question": "9 × 9 + 19", "answer": 100}
]

class GitHubStorage:
    def __init__(self, token: str, repo_name: str):
        self.g = Github(token)
        self.repo = self.g.get_repo(repo_name)
        self.branch = "main"
        self._cache = {}
        self._last_save = {}
        self._init_default_files()
        
    def _init_default_files(self):
        """Khởi tạo các file mặc định nếu chưa có"""
        default_files = {
            "data/scores.json": {"users": {}},
            "data/quiz1_pool.json": {"questions": DEFAULT_QUIZ1_POOL},
            "data/quiz2_pool.json": {"questions": DEFAULT_QUIZ2_POOL},
            "data/math_pool.json": {"questions": DEFAULT_MATH_POOL},
            "data/game_stats.json": {
                "total_games": 0,
                "games_by_type": {},
                "last_updated": datetime.now().isoformat()
            }
        }
        
        for path, default_data in default_files.items():
            try:
                self.repo.get_contents(path, ref=self.branch)
            except:
                try:
                    content = json.dumps(default_data, ensure_ascii=False, indent=2)
                    self.repo.create_file(path, f"Init {path}", content, self.branch)
                    logger.info(f"Created default file: {path}")
                except:
                    pass
        
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
            logger.error(f"Error reading {path}: {e}")
            return None
    
    def _save_file(self, path: str, data: dict, message: str, force: bool = False):
        # Kiểm tra thời gian lưu cuối
        if not force and path in self._last_save:
            if datetime.now().timestamp() - self._last_save[path] < 300:  # 5 phút
                self._cache[path] = data
                return
                
        content = json.dumps(data, ensure_ascii=False, indent=2)
        
        try:
            file = self.repo.get_contents(path, ref=self.branch)
            self.repo.update_file(path, message, content, file.sha, self.branch)
        except:
            self.repo.create_file(path, message, content, self.branch)
        
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
        
        user = data["users"][user_key]
        user["balance"] += amount
        user["username"] = username
        user["last_updated"] = datetime.now().isoformat()
        
        if amount > 0:
            user["total_earned"] += amount
            if game_type:
                user["games_played"][game_type] = user["games_played"].get(game_type, 0) + 1
                
                # Cập nhật thống kê game
                self._update_game_stats(game_type)
        
        self._save_file("data/scores.json", data, f"Update: {username} ({amount:+d})")
    
    def _update_game_stats(self, game_type: str):
        """Cập nhật thống kê tổng về các game"""
        stats = self._get_file_content("data/game_stats.json") or {
            "total_games": 0,
            "games_by_type": {},
            "last_updated": datetime.now().isoformat()
        }
        
        stats["total_games"] += 1
        stats["games_by_type"][game_type] = stats["games_by_type"].get(game_type, 0) + 1
        stats["last_updated"] = datetime.now().isoformat()
        
        self._save_file("data/game_stats.json", stats, f"Update game stats: {game_type}")
    
    def get_leaderboard(self, limit: int = 10) -> List[tuple]:
        data = self._get_file_content("data/scores.json") or {"users": {}}
        users = []
        for user_data in data["users"].values():
            users.append((
                user_data.get("username", "Unknown"),
                user_data.get("total_earned", 0)
            ))
        return sorted(users, key=lambda x: x[1], reverse=True)[:limit]
    
    def get_user_stats(self, user_id: int) -> dict:
        data = self._get_file_content("data/scores.json") or {"users": {}}
        user_data = data["users"].get(str(user_id), {})
        
        if not user_data:
            return {
                'balance': START_BALANCE,
                'total_earned': 0,
                'games_played': {}
            }
        
        return {
            'balance': user_data.get("balance", START_BALANCE),
            'total_earned': user_data.get("total_earned", 0),
            'games_played': user_data.get("games_played", {})
        }
    
    def get_quiz1_pool(self) -> List[dict]:
        data = self._get_file_content("data/quiz1_pool.json")
        if data and data.get("questions"):
            return data["questions"]
        return DEFAULT_QUIZ1_POOL
    
    def add_quiz1(self, quiz: dict):
        data = self._get_file_content("data/quiz1_pool.json") or {"questions": DEFAULT_QUIZ1_POOL}
        
        # Kiểm tra trùng lặp
        for existing in data["questions"]:
            if existing.get("question") == quiz.get("question"):
                return
                
        data["questions"].append(quiz)
        
        # Giới hạn số lượng câu hỏi
        if len(data["questions"]) > 100:
            data["questions"] = data["questions"][-100:]
            
        self._save_file("data/quiz1_pool.json", data, "Add quiz1")
    
    def get_quiz2_pool(self) -> List[dict]:
        data = self._get_file_content("data/quiz2_pool.json")
        if data and data.get("questions"):
            return data["questions"]
        return DEFAULT_QUIZ2_POOL
    
    def add_quiz2(self, quiz: dict):
        data = self._get_file_content("data/quiz2_pool.json") or {"questions": DEFAULT_QUIZ2_POOL}
        
        # Kiểm tra trùng lặp
        for existing in data["questions"]:
            if existing.get("question") == quiz.get("question"):
                return
                
        data["questions"].append(quiz)
        
        # Giới hạn số lượng câu hỏi
        if len(data["questions"]) > 100:
            data["questions"] = data["questions"][-100:]
            
        self._save_file("data/quiz2_pool.json", data, "Add quiz2")
    
    def get_math_pool(self) -> List[dict]:
        data = self._get_file_content("data/math_pool.json")
        if data and data.get("questions"):
            return data["questions"]
        return DEFAULT_MATH_POOL
    
    def add_math(self, math: dict):
        data = self._get_file_content("data/math_pool.json") or {"questions": DEFAULT_MATH_POOL}
        
        # Kiểm tra trùng lặp
        for existing in data["questions"]:
            if existing.get("question") == math.get("question"):
                return
                
        data["questions"].append(math)
        
        # Giới hạn số lượng câu hỏi
        if len(data["questions"]) > 100:
            data["questions"] = data["questions"][-100:]
            
        self._save_file("data/math_pool.json", data, "Add math")
    
    async def force_save_all(self):
        """Lưu tất cả cache xuống GitHub"""
        for path, data in self._cache.items():
            try:
                self._save_file(path, data, "Force save", force=True)
            except Exception as e:
                logger.error(f"Error saving {path}: {e}")

storage = GitHubStorage(GITHUB_TOKEN, GITHUB_REPO)

# Global variables
active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
minigame_sessions: Dict[int, dict] = {}
user_balances: Dict[int, int] = {}
quiz_history: Dict[int, List[str]] = {}

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

# Game classes
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
        # Thử gọi API trước
        difficulty = random.choice(["easy", "medium", "hard"])
        
        prompt = f"""Tạo một bài toán với độ khó: {difficulty}

Yêu cầu:
- Easy: phép cộng/trừ đơn giản (2 số, kết quả < 200)
- Medium: phép nhân hoặc cộng/trừ nhiều bước
- Hard: tính toán phức tạp với nhiều phép tính

Trả về JSON bằng tiếng Việt:
{{
  "question": "biểu thức toán học (VD: 45 + 67)",
  "answer": đáp_án_số
}}"""

        messages = [
            {"role": "system", "content": "Bạn là giáo viên toán. Tạo bài toán rõ ràng bằng tiếng Việt."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await call_api(messages, model=CLAUDE_MODEL, max_tokens=150)
            
            if response:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                
                if json_start != -1:
                    json_str = response[json_start:json_end]
                    data = json.loads(json_str)
                    
                    self.current_question = data.get("question", "")
                    self.current_answer = int(data.get("answer", 0))
                    
                    # Lưu câu hỏi mới vào pool
                    try:
                        storage.add_math({
                            "question": self.current_question,
                            "answer": self.current_answer
                        })
                    except:
                        pass
                    
                    return self.current_question
        except:
            pass
        
        # Nếu API lỗi, lấy từ pool
        pool = storage.get_math_pool()
        if pool:
            math_q = random.choice(pool)
            self.current_question = math_q.get("question", "")
            self.current_answer = int(math_q.get("answer", 0))
            return self.current_question
        
        # Tạo câu hỏi mặc định nếu không có gì
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
        global quiz_history
        
        if self.chat_id not in quiz_history:
            quiz_history[self.chat_id] = []
            
        recent_questions = quiz_history[self.chat_id][-10:] if len(quiz_history[self.chat_id]) > 0 else []
        
        # Thử API trước
        topics = ["Lịch sử Việt Nam", "Địa lý Việt Nam", "Văn hóa Việt Nam", "Ẩm thực Việt Nam", "Khoa học Việt Nam", "Thể thao Việt Nam"]
        topic = random.choice(topics)
        
        prompt = f"""Create a quiz question about {topic} with MAXIMUM ACCURACY.

CRITICAL REQUIREMENTS:
1. MUST be 100% factually accurate and verifiable
2. 4 options with ONLY 1 correct answer
3. Different from these recent questions: {', '.join(recent_questions[:3])}

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
                        "explanation": data.get("explain", "")
                    }
                    
                    if quiz["question"] and len(quiz["options"]) == 4:
                        quiz_history[self.chat_id].append(quiz["question"][:50])
                        try:
                            storage.add_quiz1(quiz)
                        except:
                            pass
                        return quiz
        except:
            pass
        
        # Nếu API lỗi, lấy từ pool
        pool = storage.get_quiz1_pool()
        if pool:
            # Lọc các câu chưa hỏi gần đây
            available_quiz = [q for q in pool if q.get("question", "")[:50] not in recent_questions]
            if available_quiz:
                quiz = random.choice(available_quiz)
                quiz_history[self.chat_id].append(quiz["question"][:50])
                return quiz
            else:
                # Nếu hết câu mới thì reset history và chọn lại
                quiz_history[self.chat_id] = []
                quiz = random.choice(pool)
                quiz_history[self.chat_id].append(quiz["question"][:50])
                return quiz
        
        return None

class VietnameseQuiz2Game:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.current_quiz = None
        
    async def generate_quiz(self) -> dict:
        global quiz_history
        
        if self.chat_id not in quiz_history:
            quiz_history[self.chat_id] = []
            
        recent_questions = quiz_history[self.chat_id][-10:] if len(quiz_history[self.chat_id]) > 0 else []
        
        # Thử API trước
        topics = ["Lịch sử Việt Nam", "Địa lý Việt Nam", "Văn hóa Việt Nam", "Ẩm thực Việt Nam", "Khoa học Việt Nam", "Thể thao Việt Nam"]
        topic = random.choice(topics)
        
        prompt = f"""Create a quiz question about {topic} with MAXIMUM ACCURACY.

CRITICAL REQUIREMENTS:
1. MUST be 100% factually accurate and verifiable
2. Question should have a SHORT answer (1-3 words maximum)
3. Answer should be simple and clear (city name, person name, food name, etc.)
4. Different from these recent questions: {', '.join(recent_questions[:3])}

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
                        "explanation": data.get("explanation", "")
                    }
                    
                    if quiz["question"] and quiz["answer"]:
                        quiz_history[self.chat_id].append(quiz["question"][:50])
                        try:
                            storage.add_quiz2(quiz)
                        except:
                            pass
                        return quiz
        except:
            pass
        
        # Nếu API lỗi, lấy từ pool
        pool = storage.get_quiz2_pool()
        if pool:
            # Lọc các câu chưa hỏi gần đây
            available_quiz = [q for q in pool if q.get("question", "")[:50] not in recent_questions]
            if available_quiz:
                quiz = random.choice(available_quiz)
                quiz_history[self.chat_id].append(quiz["question"][:50])
                return quiz
            else:
                # Nếu hết câu mới thì reset history và chọn lại
                quiz_history[self.chat_id] = []
                quiz = random.choice(pool)
                quiz_history[self.chat_id].append(quiz["question"][:50])
                return quiz
        
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

# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        balance = get_user_balance(user.id)
        
        message = f"""👋 Xin chào {user.first_name}! Mình là Linh!

💰 Số dư: {_fmt_money(balance)}

🎮 Minigame:
/minigame - Chơi ngẫu nhiên các minigame
/stopmini - Dừng minigame

📝 Chơi riêng:
/guessnumber - Đoán số 1-999
/quiz1 - Câu đố chọn đáp án
/quiz2 - Câu đố trả lời ngắn
/math - Toán học

📊 /top - Bảng xếp hạng
💰 /bal - Xem số dư
📈 /stats - Thống kê

💬 Chat với mình bất cứ lúc nào!"""
        
        await update.message.reply_text(message)
        logger.info(f"Start command from {user.id}")
    except Exception as e:
        logger.error(f"Error in start: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def bal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        balance = get_user_balance(user.id)
        await update.message.reply_text(f"💰 Số dư: {_fmt_money(balance)}")
        logger.info(f"Bal command from {user.id}: {balance}")
    except Exception as e:
        logger.error(f"Error in bal_cmd: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        leaderboard = storage.get_leaderboard()
        
        if not leaderboard:
            await update.message.reply_text("📊 Chưa có dữ liệu")
            return
        
        msg = "🏆 **BẢNG XẾP HẠNG**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        
        for i, (name, score) in enumerate(leaderboard):
            medal = medals[i] if i < 3 else f"{i+1}."
            msg += f"{medal} {name}: {_fmt_money(score)} điểm\n"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        logger.info("Top command executed")
    except Exception as e:
        logger.error(f"Error in top_cmd: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        data = storage.get_user_stats(user.id)
        
        msg = f"📊 **Thống kê {user.first_name}**\n\n"
        msg += f"💰 Số dư: {_fmt_money(data['balance'])}\n"
        msg += f"⭐ Tổng điểm: {_fmt_money(data['total_earned'])}\n"
        
        games = data.get('games_played', {})
        if games:
            msg += "\n🎮 Đã chơi:\n"
            game_names = {
                "guessnumber": "Đoán số",
                "quiz1": "Quiz 1.0",
                "quiz2": "Quiz 2.0",
                "math": "Toán học",
                "minigame": "Minigame tổng"
            }
            for game, count in games.items():
                name = game_names.get(game, game)
                msg += f"• {name}: {count} lần\n"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        logger.info(f"Stats command from {user.id}")
    except Exception as e:
        logger.error(f"Error in stats_cmd: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

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
        logger.error(f"Error in guessnumber_cmd: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def quiz1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
            f"{emoji} QUIZ 1.0 - {quiz['topic'].upper()}\n\n{quiz['question']}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in quiz1_cmd: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def quiz2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
            f"""{emoji} QUIZ 2.0 - {quiz["topic"].upper()}

{quiz["question"]}

💡 Trả lời ngắn gọn (1-3 từ)
✍️ Gõ câu trả lời của bạn!"""
        )
    except Exception as e:
        logger.error(f"Error in quiz2_cmd: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def math_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id in active_games:
            del active_games[chat_id]
        
        loading_msg = await update.message.reply_text("⏳ Claude AI đang tạo bài toán...")
        
        game = MathQuizGame(chat_id)
        question = await game.generate_question()
        
        if not question:
            await loading_msg.edit_text("❌ Lỗi tạo câu hỏi! Thử lại /math")
            return
        
        active_games[chat_id] = {"type": "math", "game": game}
        
        await loading_msg.edit_text(
            f"""🧮 TOÁN HỌC

Tính: {question} = ?

📝 Bạn có {game.max_attempts} lần thử
✍️ Gõ đáp án!"""
        )
    except Exception as e:
        logger.error(f"Error in math_cmd: {e}")
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
        logger.error(f"Error in minigame_cmd: {e}")
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
                f"{emoji} QUIZ 1.0 - {quiz['topic'].upper()}\n\n{quiz['question']}",
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
                f"""{emoji} QUIZ 2.0 - {quiz["topic"].upper()}

{quiz["question"]}

💡 Trả lời ngắn gọn (1-3 từ)
✍️ Gõ câu trả lời của bạn!"""
            )
        
        elif game_type == "math":
            game = MathQuizGame(chat_id)
            question = await game.generate_question()
            
            if not question:
                await context.bot.send_message(chat_id, "❌ Lỗi tạo câu hỏi! Chuyển game khác...")
                await asyncio.sleep(2)
                await start_random_minigame(chat_id, context)
                return
            
            active_games[chat_id] = {"type": "math", "game": game, "minigame": True}
            
            await context.bot.send_message(
                chat_id,
                f"""🧮 TOÁN HỌC

Tính: {question} = ?

📝 Bạn có {game.max_attempts} lần thử
✍️ Gõ đáp án!"""
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
        logger.error(f"Error in stop_minigame_cmd: {e}")
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
        logger.error(f"Error in hint_command: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

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
        logger.error(f"Error in button_callback: {e}")

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
            await update.message.reply_text("😅 Xin lỗi, mình đang bận!")
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

async def post_init(application: Application) -> None:
    logger.info("Bot started!")

async def post_shutdown(application: Application) -> None:
    await storage.force_save_all()
    logger.info("Bot shutdown - data saved!")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
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
