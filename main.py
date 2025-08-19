import os
import random
import asyncio
import logging
import requests
import json
import base64
import unicodedata
import re
import html
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
from collections import deque
from github import Github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = "google/gemini-2.5-flash-lite"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "htuananh1/Data-manager"

START_BALANCE = 1000
CHAT_HISTORY_LIMIT = 6
GAME_TIMEOUT = 600
WRONG_ANSWER_COOLDOWN = 5
MAX_GAME_MESSAGES = 5
CHAT_SAVE_INTERVAL = 300
QUIZ_CHECK_INTERVAL = 60
MAX_QUIZ_RETRY = 3  # Số lần thử tạo quiz mới nếu trùng

# Các đề tài quiz
QUIZ_TOPICS = [
    "Bóng đá",
    "Địa lý",
    "Lịch sử",
    "Kĩ năng sống",
    "Động vật",
    "Anime & Manga"
]

# Độ khó
DIFFICULTIES = ["bình thường", "khó", "cực khó"]

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
            self._chat_save_queue = {}
            self._quiz_questions_cache = set()  # Cache câu hỏi để check nhanh
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
            # Format đặc biệt cho translated_quiz_pool.json
            if path == "data/translated_quiz_pool.json" and "questions" in data:
                # Tạo JSON với mỗi quiz trên 1 dòng
                content = '{\n  "questions": [\n'
                questions = []
                for quiz in data["questions"]:
                    # Mỗi quiz thành 1 dòng JSON compact
                    quiz_json = json.dumps(quiz, ensure_ascii=False, separators=(',', ':'))
                    questions.append(f'    {quiz_json}')
                content += ',\n'.join(questions)
                content += '\n  ],\n'
                content += f'  "total": {data.get("total", len(data["questions"]))},\n'
                content += f'  "last_updated": "{data.get("last_updated", datetime.now().isoformat())}"\n'
                content += '}'
            else:
                # Format bình thường cho các file khác
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
    
    def queue_chat_save(self, chat_id: int, messages: List[dict]):
        self._chat_save_queue[chat_id] = {
            "messages": messages,
            "timestamp": datetime.now()
        }
    
    async def batch_save(self):
        if not self._pending_updates and not self._chat_save_queue:
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
        
        if "translated_quiz" in self._pending_updates:
            quiz_data = self._get_file_content("data/translated_quiz_pool.json") or {"questions": []}
            
            # Tạo set các câu hỏi đã có để check nhanh
            existing_questions = {self._normalize_question(q.get("question")) for q in quiz_data["questions"]}
            
            added_count = 0
            for quiz in self._pending_updates["translated_quiz"]:
                # Check trùng lặp với normalize
                normalized_question = self._normalize_question(quiz.get("question"))
                if normalized_question not in existing_questions:
                    quiz_data["questions"].append(quiz)
                    existing_questions.add(normalized_question)
                    self._quiz_questions_cache.add(normalized_question)
                    added_count += 1
                    logger.info(f"Added new quiz: {quiz['question'][:50]}...")
                else:
                    logger.warning(f"Skipped duplicate quiz: {quiz['question'][:50]}...")
            
            if added_count > 0:
                quiz_data["total"] = len(quiz_data["questions"])
                quiz_data["last_updated"] = timestamp
                
                self._save_file("data/translated_quiz_pool.json", quiz_data, f"Added {added_count} new quizzes")
        
        current_time = datetime.now()
        for chat_id, chat_data in list(self._chat_save_queue.items()):
            if (current_time - chat_data["timestamp"]).total_seconds() < CHAT_SAVE_INTERVAL:
                continue
                
            data = {
                "messages": chat_data["messages"][-CHAT_HISTORY_LIMIT:],
                "chat_id": chat_id,
                "saved_at": current_time.isoformat()
            }
            self._save_file(f"data/chat_history/{chat_id}.json", data, f"Save chat history: {chat_id}")
            del self._chat_save_queue[chat_id]
        
        self._pending_updates = {}
        self._last_batch_save = datetime.now()
        logger.info(f"Batch save completed at {timestamp}")
    
    def _normalize_question(self, question: str) -> str:
        """Normalize câu hỏi để so sánh (loại bỏ dấu, chữ thường, khoảng trắng thừa)"""
        if not question:
            return ""
        # Chuyển thành chữ thường
        normalized = question.lower()
        # Loại bỏ dấu tiếng Việt
        normalized = unicodedata.normalize('NFD', normalized)
        normalized = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
        # Loại bỏ các ký tự đặc biệt, chỉ giữ chữ và số
        normalized = re.sub(r'[^a-z0-9\s]', '', normalized)
        # Loại bỏ khoảng trắng thừa
        normalized = ' '.join(normalized.split())
        return normalized
    
    def is_duplicate_question(self, question: str) -> bool:
        """Kiểm tra câu hỏi có trùng không"""
        normalized = self._normalize_question(question)
        
        # Check trong cache trước
        if normalized in self._quiz_questions_cache:
            return True
        
        # Nếu cache chưa đầy đủ, load từ file
        if not self._quiz_questions_cache:
            quiz_data = self._get_file_content("data/translated_quiz_pool.json")
            if quiz_data and "questions" in quiz_data:
                for q in quiz_data["questions"]:
                    self._quiz_questions_cache.add(self._normalize_question(q.get("question", "")))
        
        return normalized in self._quiz_questions_cache
    
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
    
    def get_translated_quiz_pool(self) -> List[dict]:
        data = self._get_file_content("data/translated_quiz_pool.json")
        if data and "questions" in data:
            return data["questions"]
        return []
    
    def add_translated_quiz(self, quiz: dict):
        self.queue_update("translated_quiz", quiz)
    
    def get_minigame_groups(self) -> Set[int]:
        data = self._get_file_content("data/minigame_groups.json")
        if data and "groups" in data:
            return set(data["groups"])
        return set()
    
    def save_minigame_groups(self, groups: Set[int]):
        data = {
            "groups": list(groups),
            "updated": datetime.now().isoformat()
        }
        self._save_file("data/minigame_groups.json", data, "Update minigame groups")
    
    def add_minigame_group(self, chat_id: int):
        groups = self.get_minigame_groups()
        groups.add(chat_id)
        self.save_minigame_groups(groups)
    
    def remove_minigame_group(self, chat_id: int):
        groups = self.get_minigame_groups()
        groups.discard(chat_id)
        self.save_minigame_groups(groups)
    
    def get_chat_history(self, chat_id: int) -> List[dict]:
        data = self._get_file_content(f"data/chat_history/{chat_id}.json")
        if data:
            saved_at = datetime.fromisoformat(data.get("saved_at", datetime.now().isoformat()))
            if datetime.now() - saved_at > timedelta(hours=24):
                return []
            return data.get("messages", [])
        return []

try:
    storage = GitHubStorage(GITHUB_TOKEN, GITHUB_REPO)
except Exception as e:
    logger.error(f"Critical error initializing storage: {e}")
    storage = None

active_games: Dict[int, dict] = {}
chat_history: Dict[int, deque] = {}
game_messages: Dict[int, List[int]] = {}
game_timeouts: Dict[int, asyncio.Task] = {}
game_start_times: Dict[int, datetime] = {}
wrong_answer_cooldowns: Dict[Tuple[int, int], datetime] = {}
minigame_groups: Set[int] = set()
user_answered: Dict[Tuple[int, int], bool] = {}
quiz_scheduling: Dict[int, datetime] = {}  # Track quiz scheduling

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
            "temperature": 0.7
        }
        
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        return None
    except Exception as e:
        logger.error(f"API call error: {e}")
        return None

async def generate_quiz_with_gemini(topic: str, difficulty: str, retry_count: int = 0) -> Optional[dict]:
    """Tạo quiz mới bằng Gemini với check trùng lặp"""
    try:
        # Điều chỉnh prompt theo độ khó
        difficulty_guide = {
            "bình thường": "phù hợp với kiến thức phổ thông, không quá chuyên sâu",
            "khó": "đòi hỏi kiến thức sâu hơn, có thể là những chi tiết ít người biết",
            "cực khó": "cực kỳ khó, chỉ người am hiểu sâu mới biết, có thể là những chi tiết rất cụ thể"
        }
        
        # Hướng dẫn đặc biệt cho từng chủ đề
        topic_guide = {
            "Bóng đá": """về bóng đá thế giới bao gồm:
- Các giải đấu: World Cup, Euro, Copa America, Champions League, Europa League, Premier League, La Liga, Serie A, Bundesliga, Ligue 1
- Câu lạc bộ nổi tiếng: Real Madrid, Barcelona, Manchester United, Liverpool, Bayern Munich, Juventus, PSG, v.v.
- Cầu thủ huyền thoại và hiện tại: Pele, Maradona, Messi, Ronaldo, Neymar, Mbappe, Haaland, v.v.
- Huấn luyện viên nổi tiếng: Pep Guardiola, Jurgen Klopp, Jose Mourinho, Carlo Ancelotti, v.v.
- Lịch sử bóng đá: các kỷ lục, thành tích, sự kiện quan trọng
- Luật bóng đá, công nghệ VAR, các vị trí trong sân
- Chuyển nhượng kỷ lục, derby nổi tiếng, sân vận động lớn""",
            "Địa lý": "về địa lý THẾ GIỚI - các quốc gia, thủ đô, dãy núi, sông ngòi, đại dương, sa mạc, hồ, eo biển, quần đảo trên TOÀN THẾ GIỚI",
            "Lịch sử": "về lịch sử THẾ GIỚI - các nền văn minh cổ đại, đế chế, chiến tranh, nhân vật lịch sử, sự kiện quan trọng của TOÀN THẾ GIỚI",
            "Kĩ năng sống": "về kỹ năng sống, tâm lý học, giao tiếp, phát triển bản thân, sức khỏe tinh thần",
            "Động vật": "về động vật trên khắp thế giới, đặc điểm sinh học, môi trường sống, hành vi, các loài quý hiếm",
            "Anime & Manga": "về anime và manga Nhật Bản, các series nổi tiếng, nhân vật, tác giả, studio"
        }
        
        # Thêm hướng dẫn để tránh tạo câu hỏi trùng
        avoid_duplicate = ""
        if retry_count > 0:
            avoid_duplicate = f"\nLưu ý: Đây là lần thử thứ {retry_count + 1}, hãy tạo câu hỏi HOÀN TOÀN MỚI và KHÁC BIỆT."
        
        # Nhấn mạnh phạm vi toàn cầu cho lịch sử và địa lý
        global_emphasis = ""
        if topic in ["Địa lý", "Lịch sử"]:
            global_emphasis = "\n\n⚠️ QUAN TRỌNG: Câu hỏi PHẢI về phạm vi THẾ GIỚI/QUỐC TẾ, KHÔNG chỉ riêng về Việt Nam!"
        
        # Thêm hướng dẫn đa dạng cho bóng đá
        football_variety = ""
        if topic == "Bóng đá":
            football_variety = "\n\n⚠️ QUAN TRỌNG: Tạo câu hỏi ĐA DẠNG về nhiều khía cạnh của bóng đá, KHÔNG CHỈ về World Cup!"
        
        # Ví dụ cụ thể cho bóng đá
        football_examples = ""
        if topic == "Bóng đá":
            football_examples = """

Ví dụ câu hỏi tốt về Bóng đá:
- Câu lạc bộ nào vô địch Champions League nhiều nhất?
- Ai là cầu thủ ghi nhiều bàn nhất lịch sử Premier League?
- Derby nào được gọi là "El Clasico"?
- Sân vận động nào có sức chứa lớn nhất châu Âu?
- Cầu thủ nào giữ kỷ lục chuyển nhượng đắt nhất?
- Đội tuyển nào vô địch Euro 2020?
- Ai được mệnh danh là "The Special One"?
- Luật việt vị được thay đổi như thế nào năm 2022?"""
        
        prompt = f"""Tạo 1 câu hỏi trắc nghiệm về chủ đề "{topic}" với độ khó "{difficulty}" ({difficulty_guide[difficulty]}).

Chủ đề cụ thể: {topic_guide.get(topic, topic)}{global_emphasis}{football_variety}{avoid_duplicate}

Yêu cầu:
1. Câu hỏi phải thú vị, có giá trị kiến thức
2. 4 đáp án phải hợp lý, không quá dễ loại trừ
3. Giải thích phải chi tiết, có thông tin bổ ích
4. Hoàn toàn bằng tiếng Việt
5. Câu hỏi phải CỤ THỂ và ĐỘC ĐÁO
6. Với Địa lý và Lịch sử: tập trung vào các quốc gia, sự kiện, địa điểm TRÊN TOÀN THẾ GIỚI
7. Với Bóng đá: ĐA DẠNG các khía cạnh - giải đấu, CLB, cầu thủ, HLV, kỷ lục, luật, sân vận động, v.v.{football_examples}

Ví dụ câu hỏi tốt về Địa lý thế giới:
- Eo biển nào ngăn cách châu Âu và châu Phi?
- Thành phố nào là thủ đô của Argentina?
- Sa mạc Sahara nằm ở châu lục nào?

Ví dụ câu hỏi tốt về Lịch sử thế giới:
- Ai là hoàng đế đầu tiên của đế chế La Mã?
- Chiến tranh thế giới thứ nhất bắt đầu năm nào?
- Nền văn minh Maya phát triển ở khu vực nào?

Trả về JSON với format:
{{
  "question": "câu hỏi",
  "options": ["A. đáp án 1", "B. đáp án 2", "C. đáp án 3", "D. đáp án 4"],
  "correct": "A/B/C/D",
  "correct_answer": "nội dung đáp án đúng",
  "explanation": "giải thích chi tiết về đáp án đúng và thông tin thêm"
}}"""

        messages = [
            {
                "role": "system",
                "content": "Bạn là chuyên gia tạo câu hỏi trắc nghiệm chất lượng cao về các chủ đề toàn cầu. Với Bóng đá, hãy tạo câu hỏi ĐA DẠNG về mọi khía cạnh: các giải đấu khác nhau, CLB, cầu thủ, HLV, lịch sử, kỷ lục, luật, công nghệ, sân vận động - KHÔNG CHỈ World Cup. Chỉ trả về JSON, không giải thích thêm."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        response = await call_api(messages, max_tokens=600)
        
        if not response:
            return None
            
        # Parse response
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
        
        quiz = json.loads(response)
        
        # Kiểm tra trùng lặp
        if storage and storage.is_duplicate_question(quiz["question"]):
            logger.warning(f"Duplicate question detected: {quiz['question'][:50]}...")
            if retry_count < MAX_QUIZ_RETRY:
                logger.info(f"Retrying to generate new quiz (attempt {retry_count + 2}/{MAX_QUIZ_RETRY + 1})")
                await asyncio.sleep(1)  # Delay nhỏ trước khi retry
                return await generate_quiz_with_gemini(topic, difficulty, retry_count + 1)
            else:
                logger.error(f"Max retries reached, using duplicate quiz")
        
        # Thêm metadata
        quiz["topic"] = f"{topic} ({difficulty.title()})"
        quiz["source"] = "Gemini AI"
        quiz["difficulty"] = difficulty
        quiz["created_at"] = datetime.now().isoformat()
        quiz["generated"] = True  # Đánh dấu là quiz mới tạo
        
        return quiz
        
    except Exception as e:
        logger.error(f"Error generating quiz with Gemini: {e}")
        return None

class QuizGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.current_quiz = None
        
    async def generate_quiz(self) -> dict:
        # Random topic và difficulty
        topic = random.choice(QUIZ_TOPICS)
        difficulty = random.choice(DIFFICULTIES)
        
        # Thử tạo quiz mới bằng Gemini
        logger.info(f"Generating new quiz: {topic} - {difficulty}")
        quiz = await generate_quiz_with_gemini(topic, difficulty)
        
        if quiz:
            # Lưu quiz mới vào pool
            if storage:
                storage.add_translated_quiz(quiz)
            return quiz
        
        # Fallback về pool quiz cũ nếu lỗi
        if storage:
            quiz_pool = storage.get_translated_quiz_pool()
            if quiz_pool:
                # Lọc theo topic và difficulty nếu có
                filtered_pool = [
                    q for q in quiz_pool 
                    if topic in q.get('topic', '') and difficulty in q.get('topic', '')
                ]
                
                # Nếu không có quiz phù hợp, dùng toàn bộ pool
                if not filtered_pool:
                    filtered_pool = quiz_pool
                
                if filtered_pool:
                    fallback_quiz = random.choice(filtered_pool)
                    logger.info(f"Using quiz from pool (filtered: {len(filtered_pool)}, total: {len(quiz_pool)})")
                    return fallback_quiz
        
        logger.error("Failed to generate or find any quiz")
        return None

async def delete_old_messages(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    if chat_id not in game_messages:
        return
        
    messages = game_messages[chat_id]
    if len(messages) > MAX_GAME_MESSAGES:
        to_delete = messages[:-MAX_GAME_MESSAGES]
        for msg_id in to_delete:
            try:
                await context.bot.delete_message(chat_id, msg_id)
            except:
                pass
        game_messages[chat_id] = messages[-MAX_GAME_MESSAGES:]

async def add_game_message(chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE):
    if chat_id not in game_messages:
        game_messages[chat_id] = []
    game_messages[chat_id].append(message_id)
    await delete_old_messages(chat_id, context)

async def cleanup_game(chat_id: int):
    if chat_id in active_games:
        del active_games[chat_id]
    
    if chat_id in game_timeouts:
        try:
            game_timeouts[chat_id].cancel()
        except:
            pass
        del game_timeouts[chat_id]
    
    if chat_id in game_start_times:
        del game_start_times[chat_id]
    
    # Cleanup quiz scheduling tracker
    if chat_id in quiz_scheduling:
        del quiz_scheduling[chat_id]
    
    keys_to_remove = [key for key in user_answered.keys() if key[0] == chat_id]
    for key in keys_to_remove:
        del user_answered[key]

async def schedule_next_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, delay: int = 5):
    try:
        # Check xem có đang schedule quiz không
        if chat_id in quiz_scheduling:
            last_schedule = quiz_scheduling[chat_id]
            if (datetime.now() - last_schedule).total_seconds() < delay:
                logger.warning(f"Quiz already scheduled recently for chat {chat_id}")
                return
        
        quiz_scheduling[chat_id] = datetime.now()
        
        await asyncio.sleep(delay)
        
        if chat_id in minigame_groups:
            logger.info(f"Creating new quiz for chat {chat_id}")
            await start_random_minigame(chat_id, context)
            
        # Cleanup scheduling tracker
        if chat_id in quiz_scheduling:
            del quiz_scheduling[chat_id]
            
    except Exception as e:
        logger.error(f"Error scheduling next quiz for {chat_id}: {e}")
        if chat_id in quiz_scheduling:
            del quiz_scheduling[chat_id]

async def game_timeout_handler(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.sleep(GAME_TIMEOUT)
        
        logger.info(f"Game timeout for chat {chat_id}")
        
        if chat_id in active_games:
            game_info = active_games[chat_id]
            game = game_info["game"]
            
            try:
                msg = f"⏰ **Hết 10 phút! Chuyển câu mới...**\n\n"
                if game_info["type"] == "quiz" and game.current_quiz:
                    msg += f"✅ Đáp án: **{game.current_quiz['correct']}**\n"
                    msg += f"💡 {game.current_quiz.get('explanation', '')}"
                
                timeout_msg = await context.bot.send_message(chat_id, msg, parse_mode="Markdown")
                await add_game_message(chat_id, timeout_msg.message_id, context)
            except Exception as e:
                logger.error(f"Error sending timeout message to {chat_id}: {e}")
        
        await cleanup_game(chat_id)
        
        if chat_id in minigame_groups:
            asyncio.create_task(schedule_next_quiz(chat_id, context))
            
    except asyncio.CancelledError:
        logger.info(f"Timeout handler cancelled for chat {chat_id}")
    except Exception as e:
        logger.error(f"Error in timeout handler for {chat_id}: {e}")
        await cleanup_game(chat_id)
        if chat_id in minigame_groups:
            asyncio.create_task(schedule_next_quiz(chat_id, context, 5))

async def start_random_minigame(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info(f"Starting minigame for chat {chat_id}")
        
        if chat_id not in minigame_groups:
            logger.info(f"Chat {chat_id} not in minigame groups")
            return
        
        # Kiểm tra xem có đang có game không
        if chat_id in active_games:
            logger.warning(f"Game already active for chat {chat_id}, skipping")
            return
        
        await cleanup_game(chat_id)
        
        loading_msg = await context.bot.send_message(
            chat_id, 
            f"🎲 **MINIGAME**\n"
            f"🎮 📝 Quiz Trắc Nghiệm\n"
            f"⏰ Tự đổi câu mới sau 10 phút\n\n"
            f"⏳ Đang tạo quiz mới với Gemini...",
            parse_mode="Markdown"
        )
        await add_game_message(chat_id, loading_msg.message_id, context)
        
        await asyncio.sleep(1)
        
        game = QuizGame(chat_id)
        quiz = await game.generate_quiz()
        
        if not quiz:
            logger.error(f"Failed to generate quiz for chat {chat_id}")
            error_msg = await context.bot.send_message(chat_id, "❌ Lỗi! Thử lại sau...")
            await add_game_message(chat_id, error_msg.message_id, context)
            asyncio.create_task(schedule_next_quiz(chat_id, context, 30))
            return
        
        game.current_quiz = quiz
        active_games[chat_id] = {"type": "quiz", "game": game, "minigame": True}
        game_start_times[chat_id] = datetime.now()
        
        keyboard = []
        for option in quiz["options"]:
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Hiển thị source
        source_text = ""
        if quiz.get("generated"):
            source_text = " ✨"  # Icon cho quiz mới tạo
        
        quiz_msg = await context.bot.send_message(
            chat_id,
            f"❓ **{quiz['topic']}{source_text}**\n\n"
            f"{quiz['question']}\n\n"
            f"🏆 Ai trả lời đúng sẽ được 300 điểm!\n"
            f"⚠️ Mỗi người chỉ được chọn 1 lần!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        await add_game_message(chat_id, quiz_msg.message_id, context)
        
        try:
            await context.bot.delete_message(chat_id, loading_msg.message_id)
        except:
            pass
        
        game_timeouts[chat_id] = asyncio.create_task(game_timeout_handler(chat_id, context))
        logger.info(f"Quiz created successfully for chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Error in start_random_minigame for {chat_id}: {e}")
        await cleanup_game(chat_id)
        if chat_id in minigame_groups:
            asyncio.create_task(schedule_next_quiz(chat_id, context, 60))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        username = user.username or user.first_name
        balance = get_user_balance(user.id)
        
        chat = update.effective_chat
        
        if chat.type in ["group", "supergroup"]:
            minigame_groups.add(chat.id)
            if storage:
                storage.add_minigame_group(chat.id)
            
            if chat.id not in active_games:
                asyncio.create_task(start_random_minigame(chat.id, context))
        
        quiz_count = 0
        unique_count = 0
        if storage:
            quiz_pool = storage.get_translated_quiz_pool()
            quiz_count = len(quiz_pool)
            # Đếm số câu hỏi unique
            unique_questions = set()
            for q in quiz_pool:
                unique_questions.add(storage._normalize_question(q.get("question", "")))
            unique_count = len(unique_questions)
        
        message = f"""👋 Xin chào {username}! Mình là Linh Bot!

💰 Số dư của bạn: {_fmt_money(balance)}

🎮 **Minigame tự động trong nhóm**
Bot tự động tạo quiz với Gemini AI!

📚 **Các chủ đề:**
⚽ Bóng đá - Giải đấu, CLB, cầu thủ, HLV, kỷ lục
🌍 Địa lý thế giới - Các quốc gia, thủ đô, địa hình toàn cầu
📜 Lịch sử thế giới - Sự kiện, nhân vật lịch sử toàn cầu  
💡 Kĩ năng sống - Phát triển bản thân, tâm lý
🦁 Động vật - Các loài động vật trên thế giới
🎌 Anime & Manga - Văn hóa Nhật Bản

⚡ **Độ khó:** Bình thường, Khó, Cực khó

📝 **Chơi riêng lẻ:**
/quiz - Tạo quiz ngẫu nhiên

📊 **Thông tin:**
/top - Bảng xếp hạng
/bal - Xem số dư
/stats - Thống kê cá nhân

🛠️ **Admin:**
/clean - Dọn dẹp bot (chỉ admin)
/stopminigame - Dừng minigame trong nhóm

📚 **Quiz pool:** {quiz_count} câu ({unique_count} unique)
🔄 **Auto check duplicate questions**

💬 Chat riêng với mình để trò chuyện!"""
        
        await update.message.reply_text(message, parse_mode="Markdown")
        logger.info(f"Start command successful for user {user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text(
            "👋 Xin chào! Mình là Linh Bot!\n\n"
            "📊 /top - Bảng xếp hạng\n"
            "💰 /bal - Xem số dư"
        )

async def stopminigame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text("⚠️ Chỉ admin nhóm mới dùng được lệnh này!")
            return
        
        if chat.id in minigame_groups:
            minigame_groups.discard(chat.id)
            if storage:
                storage.remove_minigame_group(chat.id)
            
            await cleanup_game(chat.id)
            
            await update.message.reply_text("🛑 Đã dừng minigame trong nhóm này!")
        else:
            await update.message.reply_text("⚠️ Minigame chưa được bật trong nhóm này!")
            
    except Exception as e:
        logger.error(f"Error in stopminigame: {e}")
        await update.message.reply_text("❌ Lỗi khi dừng minigame!")

async def clean_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        
        if user.id not in [1234567890]:
            await update.message.reply_text("⚠️ Chỉ admin mới dùng được lệnh này!")
            return
        
        await update.message.reply_text("🧹 Đang dọn dẹp bot...")
        
        if storage:
            await storage.batch_save()
        
        for chat_id in list(active_games.keys()):
            await cleanup_game(chat_id)
        
        game_messages.clear()
        wrong_answer_cooldowns.clear()
        chat_history.clear()
        
        await update.message.reply_text("✅ Đã dọn dẹp xong! Bot đã được làm mới.")
        
    except Exception as e:
        logger.error(f"Error in clean command: {e}")
        await update.message.reply_text("❌ Lỗi khi dọn dẹp!")

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
            for game, count in games.items():
                if game == "quiz":
                    msg += f"• Quiz Gemini: {count} lần\n"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in stats command: {e}", exc_info=True)
        user = update.effective_user
        username = user.username or user.first_name
        balance = get_user_balance(user.id)
        msg = f"📊 **{username}**\n\n💰 Số dư: {_fmt_money(balance)}"
        await update.message.reply_text(msg, parse_mode="Markdown")

async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id in active_games:
            await update.message.reply_text("⚠️ Đang có game khác!")
            return
        
        loading_msg = await update.message.reply_text("⏳ Đang tạo quiz mới với Gemini...")
        
        game = QuizGame(chat_id)
        quiz = await game.generate_quiz()
        
        if not quiz:
            await loading_msg.edit_text("❌ Lỗi tạo câu hỏi!")
            return
        
        game.current_quiz = quiz
        active_games[chat_id] = {"type": "quiz", "game": game}
        
        keyboard = []
        for option in quiz["options"]:
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        source_text = ""
        if quiz.get("generated"):
            source_text = " ✨"
        
        await loading_msg.edit_text(
            f"❓ **{quiz['topic']}{source_text}**\n\n{quiz['question']}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in quiz: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        
        # Answer với cache_time để tránh spam click
        await query.answer(cache_time=5)
        
        data = query.data
        chat_id = update.effective_chat.id
        user = update.effective_user
        username = user.username or user.first_name
        
        # Check game còn active không
        if chat_id not in active_games:
            await query.answer("⏰ Quiz đã kết thúc!", show_alert=True)
            return
        
        # Check user đã trả lời chưa
        user_key = (chat_id, user.id)
        if user_key in user_answered:
            await query.answer("⚠️ Bạn đã trả lời rồi!", show_alert=True)
            return
        
        game_info = active_games[chat_id]
        game = game_info["game"]
        
        # Đánh dấu user đã trả lời NGAY LẬP TỨC
        user_answered[user_key] = True
        
        if data.startswith("quiz_") and game_info["type"] == "quiz":
            quiz = game.current_quiz
            answer = data.split("_")[1]
            
            correct_option = quiz['correct']
            correct_answer_text = quiz.get('correct_answer', '')
            
            # Disable tất cả buttons ngay lập tức cho user này
            try:
                # Edit message để disable buttons
                keyboard = []
                for option in quiz["options"]:
                    # Thêm emoji cho option user chọn
                    if option[0] == answer:
                        if answer == correct_option:
                            text = f"✅ {option}"
                        else:
                            text = f"❌ {option}"
                    else:
                        text = option
                    keyboard.append([InlineKeyboardButton(text, callback_data=f"disabled_{option[0]}")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Update message với buttons đã disable cho user này
                source_text = ""
                if quiz.get("generated"):
                    source_text = " ✨"
                
                await query.edit_message_text(
                    f"❓ **{quiz['topic']}{source_text}**\n\n"
                    f"{quiz['question']}\n\n"
                    f"🏆 Ai trả lời đúng sẽ được 300 điểm!\n"
                    f"⚠️ Mỗi người chỉ được chọn 1 lần!\n\n"
                    f"👤 **{username}** đã chọn: {answer}",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"Cannot edit message for user {user.id}: {e}")
            
            # Delay nhỏ để tránh spam
            await asyncio.sleep(0.5)
            
            # Tạo kết quả
            if answer == correct_option:
                points = 300
                result = f"🎉 **{username}** trả lời chính xác! (+{points}đ)\n\n"
                result += f"✅ Đáp án: **{correct_option}**"
                if correct_answer_text:
                    result += f" - {correct_answer_text}"
                result += f"\n💡 {quiz.get('explanation', '')}"
                
                update_user_balance(user.id, username, points, "quiz")
            else:
                result = f"❌ **{username}** - Chưa đúng!\n\n"
                result += f"✅ Đáp án đúng: **{correct_option}**"
                if correct_answer_text:
                    result += f" - {correct_answer_text}"
                result += f"\n💡 {quiz.get('explanation', '')}"
            
            msg = await context.bot.send_message(chat_id, result, parse_mode="Markdown")
            
            if game_info.get("minigame"):
                await add_game_message(chat_id, msg.message_id, context)
            
            # Đợi 1 chút trước khi cleanup để tránh race condition
            await asyncio.sleep(1)
            
            # Cleanup game
            await cleanup_game(chat_id)
            
            # Schedule next quiz nếu là minigame
            if chat_id in minigame_groups:
                asyncio.create_task(schedule_next_quiz(chat_id, context, 5))
        
        # Handle disabled buttons
        elif data.startswith("disabled_"):
            await query.answer("⚠️ Bạn đã trả lời rồi!", show_alert=True)
            return
                        
    except Exception as e:
        logger.error(f"Error in button callback: {e}")
        try:
            await query.answer("❌ Có lỗi xảy ra!", show_alert=True)
        except:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message.text
        chat_id = update.effective_chat.id
        user = update.effective_user
        username = user.username or user.first_name
        
        chat = update.effective_chat
        
        if chat.type in ["group", "supergroup"] and chat_id not in minigame_groups:
            minigame_groups.add(chat_id)
            if storage:
                storage.add_minigame_group(chat_id)
            
            if chat_id not in active_games:
                asyncio.create_task(start_random_minigame(chat_id, context))
        
        if chat.type == "private":
            user_id = user.id
            
            if user_id not in chat_history:
                if storage:
                    history = storage.get_chat_history(user_id)
                    chat_history[user_id] = deque(history, maxlen=CHAT_HISTORY_LIMIT)
                else:
                    chat_history[user_id] = deque(maxlen=CHAT_HISTORY_LIMIT)
            
            chat_history[user_id].append({"role": "user", "content": message})
            
            messages = [
                {"role": "system", "content": "You are Linh, a cheerful Vietnamese girl. Reply in Vietnamese, keep responses short and friendly."}
            ]
            messages.extend(list(chat_history[user_id]))
            
            response = await call_api(messages, max_tokens=150)
            
            if response:
                chat_history[user_id].append({"role": "assistant", "content": response})
                
                await update.message.reply_text(response)
                
                if storage:
                    storage.queue_chat_save(user_id, list(chat_history[user_id]))
            else:
                await update.message.reply_text("😊 Mình đang nghĩ... Thử lại nhé!")
    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)

async def periodic_batch_save(application: Application):
    while True:
        await asyncio.sleep(60)
        try:
            if storage:
                await storage.batch_save()
        except Exception as e:
            logger.error(f"Batch save error: {e}")

async def quiz_health_check(application: Application):
    while True:
        await asyncio.sleep(QUIZ_CHECK_INTERVAL)
        try:
            current_time = datetime.now()
            
            for chat_id in list(minigame_groups):
                try:
                    if chat_id not in active_games:
                        logger.warning(f"No active game for minigame group {chat_id}, creating new quiz")
                        asyncio.create_task(start_random_minigame(chat_id, application))
                        continue
                    
                    if chat_id in game_start_times:
                        game_duration = (current_time - game_start_times[chat_id]).total_seconds()
                        if game_duration > GAME_TIMEOUT + 60:
                            logger.warning(f"Game stuck for chat {chat_id}, restarting...")
                            await cleanup_game(chat_id)
                            asyncio.create_task(start_random_minigame(chat_id, application))
                            
                except Exception as e:
                    logger.error(f"Error in health check for chat {chat_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in quiz health check: {e}")

async def cleanup_memory(application: Application):
    while True:
        await asyncio.sleep(1800)
        try:
            wrong_answer_cooldowns.clear()
            
            current_games = set(active_games.keys())
            keys_to_remove = [key for key in user_answered.keys() if key[0] not in current_games]
            for key in keys_to_remove:
                del user_answered[key]
            
            inactive_users = []
            for user_id in list(chat_history.keys()):
                if len(chat_history[user_id]) == 0:
                    inactive_users.append(user_id)
            
            for user_id in inactive_users:
                del chat_history[user_id]
            
            logger.info(f"Memory cleanup completed. Active chats: {len(chat_history)}, Active games: {len(active_games)}")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

async def load_minigame_groups(application: Application):
    global minigame_groups
    
    if storage:
        minigame_groups = storage.get_minigame_groups()
        logger.info(f"Loaded {len(minigame_groups)} minigame groups")
        
        for i, chat_id in enumerate(minigame_groups):
            try:
                await start_random_minigame(chat_id, application)
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error starting minigame for {chat_id}: {e}")

async def post_init(application: Application) -> None:
    asyncio.create_task(periodic_batch_save(application))
    asyncio.create_task(cleanup_memory(application))
    asyncio.create_task(quiz_health_check(application))
    asyncio.create_task(load_minigame_groups(application))
    logger.info("Bot started successfully - Gemini Quiz Generator with Extended Football Topics!")

async def post_shutdown(application: Application) -> None:
    for task in game_timeouts.values():
        try:
            task.cancel()
        except:
            pass
    
    if storage:
        await storage.batch_save()
    logger.info("Bot shutdown - data saved!")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("quiz", quiz_cmd))
    application.add_handler(CommandHandler("bal", bal_cmd))
    application.add_handler(CommandHandler("top", top_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("clean", clean_cmd))
    application.add_handler(CommandHandler("stopminigame", stopminigame_cmd))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot - Gemini Quiz Generator with Extended Football Topics! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
