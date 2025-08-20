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
from datetime import datetime, timedelta, timezone
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
MAX_QUIZ_RETRY = 3
MAX_FILE_SIZE = 3 * 1024 * 1024
ADMIN_ID = 2026797305
VIETNAM_TZ = timezone(timedelta(hours=7))

QUIZ_TOPICS = [
    "Bóng đá",
    "Địa lý",
    "Lịch sử",
    "Kĩ năng sống",
    "Động vật",
    "Anime & Manga"
]

DIFFICULTIES = ["bình thường", "khó", "cực khó"]

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def get_vietnam_time():
    return datetime.now(VIETNAM_TZ)

class GitHubStorage:
    def __init__(self, token: str, repo_name: str):
        try:
            self.g = Github(token)
            self.repo = self.g.get_repo(repo_name)
            self.branch = "main"
            self._pending_updates = {}
            self._last_batch_save = get_vietnam_time()
            self._chat_save_queue = {}
            self._quiz_questions_cache = set()
            self._quiz_file_index = 0
            self._current_file_cache = None
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
    
    def _get_file_size(self, path: str) -> int:
        try:
            file = self.repo.get_contents(path, ref=self.branch)
            return file.size
        except:
            return 0
    
    def _get_current_quiz_file(self) -> str:
        if self._current_file_cache:
            cache_time, file_path = self._current_file_cache
            if (get_vietnam_time() - cache_time).seconds < 60:
                if self._get_file_size(file_path) < MAX_FILE_SIZE:
                    return file_path
        
        base_path = "data/translated_quiz_pool"
        
        if self._get_file_size(f"{base_path}.json") < MAX_FILE_SIZE:
            result = f"{base_path}.json"
        else:
            index = 1
            while True:
                file_path = f"{base_path}_{index}.json"
                size = self._get_file_size(file_path)
                if size == 0 or size < MAX_FILE_SIZE:
                    result = file_path
                    break
                index += 1
        
        self._current_file_cache = (get_vietnam_time(), result)
        return result
    
    def _get_all_quiz_files(self) -> List[str]:
        files = []
        base_path = "data/translated_quiz_pool"
        
        if self._get_file_size(f"{base_path}.json") > 0:
            files.append(f"{base_path}.json")
        
        index = 1
        while True:
            file_path = f"{base_path}_{index}.json"
            if self._get_file_size(file_path) == 0:
                break
            files.append(file_path)
            index += 1
        
        return files
    
    def _save_file(self, path: str, data: dict, message: str):
        try:
            if "translated_quiz_pool" in path and "questions" in data:
                content = '{\n  "questions": [\n'
                questions = []
                for quiz in data["questions"]:
                    quiz_json = json.dumps(quiz, ensure_ascii=False, separators=(',', ':'))
                    questions.append(f'    {quiz_json}')
                content += ',\n'.join(questions)
                content += '\n  ],\n'
                content += f'  "total": {data.get("total", len(data["questions"]))},\n'
                content += f'  "last_updated": "{data.get("last_updated", get_vietnam_time().isoformat())}"\n'
                content += '}'
            else:
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
            "timestamp": get_vietnam_time()
        }
    
    async def batch_save(self):
        if not self._pending_updates and not self._chat_save_queue:
            return
            
        timestamp = get_vietnam_time().isoformat()
        
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
        
        if "group_scores" in self._pending_updates:
            for update in self._pending_updates["group_scores"]:
                chat_id = update["chat_id"]
                file_path = f"data/group_scores/{chat_id}.json"
                
                group_data = self._get_file_content(file_path) or {"users": {}, "chat_id": chat_id}
                user_key = str(update["user_id"])
                
                if user_key not in group_data["users"]:
                    group_data["users"][user_key] = {
                        "user_id": update["user_id"],
                        "username": update["username"],
                        "score": 0,
                        "games_won": 0,
                        "created_at": timestamp
                    }
                
                user = group_data["users"][user_key]
                user["score"] += update["amount"]
                user["username"] = update["username"]
                user["last_updated"] = timestamp
                
                if update["amount"] > 0:
                    user["games_won"] = user.get("games_won", 0) + 1
                
                group_data["last_updated"] = timestamp
                self._save_file(file_path, group_data, f"Update group {chat_id} scores")
        
        if "translated_quiz" in self._pending_updates:
            current_file = self._get_current_quiz_file()
            quiz_data = self._get_file_content(current_file) or {"questions": []}
            
            existing_questions = {self._normalize_question(q.get("question")) for q in quiz_data["questions"]}
            
            added_count = 0
            for quiz in self._pending_updates["translated_quiz"]:
                normalized_question = self._normalize_question(quiz.get("question"))
                if normalized_question not in existing_questions:
                    quiz_data["questions"].append(quiz)
                    existing_questions.add(normalized_question)
                    self._quiz_questions_cache.add(normalized_question)
                    added_count += 1
                    logger.info(f"Added new quiz to {current_file}: {quiz['question'][:50]}...")
                else:
                    logger.warning(f"Skipped duplicate quiz: {quiz['question'][:50]}...")
            
            if added_count > 0:
                quiz_data["total"] = len(quiz_data["questions"])
                quiz_data["last_updated"] = timestamp
                
                self._save_file(current_file, quiz_data, f"Added {added_count} new quizzes")
        
        current_time = get_vietnam_time()
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
        self._last_batch_save = get_vietnam_time()
        logger.info(f"Batch save completed at {timestamp}")
    
    def _normalize_question(self, question: str) -> str:
        if not question:
            return ""
        normalized = question.lower()
        normalized = unicodedata.normalize('NFD', normalized)
        normalized = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
        normalized = re.sub(r'[^a-z0-9\s]', '', normalized)
        normalized = ' '.join(normalized.split())
        return normalized
    
    def is_duplicate_question(self, question: str) -> bool:
        normalized = self._normalize_question(question)
        
        if normalized in self._quiz_questions_cache:
            return True
        
        if not self._quiz_questions_cache:
            for file_path in self._get_all_quiz_files():
                quiz_data = self._get_file_content(file_path)
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
    
    def update_group_score(self, chat_id: int, user_id: int, username: str, amount: int):
        self.queue_update("group_scores", {
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "amount": amount
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
    
    def get_group_leaderboard(self, chat_id: int, limit: int = 10) -> List[tuple]:
        try:
            file_path = f"data/group_scores/{chat_id}.json"
            data = self._get_file_content(file_path)
            if not data or "users" not in data:
                return []
            
            users = []
            for user_data in data["users"].values():
                username = user_data.get("username", "Unknown")
                score = user_data.get("score", 0)
                if score > 0:
                    users.append((username, score))
            
            users.sort(key=lambda x: x[1], reverse=True)
            return users[:limit]
        except Exception as e:
            logger.error(f"Failed to get group leaderboard: {e}")
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
    
    def get_user_group_stats(self, chat_id: int, user_id: int) -> dict:
        try:
            file_path = f"data/group_scores/{chat_id}.json"
            data = self._get_file_content(file_path)
            if not data or "users" not in data:
                return {'score': 0, 'games_won': 0}
            
            user_data = data["users"].get(str(user_id), {})
            return {
                'score': user_data.get("score", 0),
                'games_won': user_data.get("games_won", 0)
            }
        except:
            return {'score': 0, 'games_won': 0}
    
    def get_translated_quiz_pool(self) -> List[dict]:
        all_quizzes = []
        for file_path in self._get_all_quiz_files():
            data = self._get_file_content(file_path)
            if data and "questions" in data:
                all_quizzes.extend(data["questions"])
        return all_quizzes
    
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
            "updated": get_vietnam_time().isoformat()
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
            saved_at = datetime.fromisoformat(data.get("saved_at", get_vietnam_time().isoformat()))
            if get_vietnam_time() - saved_at > timedelta(hours=24):
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
quiz_scheduling: Dict[int, datetime] = {}
quiz_creation_locks: Dict[int, asyncio.Lock] = {}

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

async def call_api(messages: List[dict], model: str = None, max_tokens: int = 400, retry: int = 3) -> str:
    for attempt in range(retry):
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
                timeout=10
            )
            
            if response.status_code == 429:
                wait_time = min(2 ** attempt, 10)
                await asyncio.sleep(wait_time)
                continue
                
            if response.status_code == 200:
                return response.json()['choices'][0]['message']['content']
                
        except requests.Timeout:
            if attempt < retry - 1:
                await asyncio.sleep(1)
                continue
        except Exception as e:
            logger.error(f"API call error attempt {attempt + 1}: {e}")
            
    return None

async def generate_quiz_with_gemini(topic: str, difficulty: str, retry_count: int = 0) -> Optional[dict]:
    try:
        difficulty_guide = {
            "bình thường": "phù hợp với kiến thức phổ thông, không quá chuyên sâu",
            "khó": "đòi hỏi kiến thức sâu hơn, có thể là những chi tiết ít người biết",
            "cực khó": "cực kỳ khó, chỉ người am hiểu sâu mới biết, có thể là những chi tiết rất cụ thể"
        }
        
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
        
        variation_prompts = [
            "Tạo câu hỏi mới lạ, chưa từng thấy",
            "Tạo câu hỏi với góc nhìn độc đáo", 
            "Tạo câu hỏi về chi tiết thú vị ít ai biết",
            "Tạo câu hỏi với fact bất ngờ"
        ]
        
        variation = random.choice(variation_prompts) if retry_count > 0 else ""
        avoid_duplicate = f"\n{variation}" if retry_count > 0 else ""
        
        global_emphasis = ""
        if topic in ["Địa lý", "Lịch sử"]:
            global_emphasis = "\n\n⚠️ QUAN TRỌNG: Câu hỏi PHẢI về phạm vi THẾ GIỚI/QUỐC TẾ, KHÔNG chỉ riêng về Việt Nam!"
        
        football_variety = ""
        if topic == "Bóng đá":
            football_variety = "\n\n⚠️ QUAN TRỌNG: Tạo câu hỏi ĐA DẠNG về nhiều khía cạnh của bóng đá, KHÔNG CHỈ về World Cup!"
        
        prompt = f"""Tạo 1 câu hỏi trắc nghiệm về chủ đề "{topic}" với độ khó "{difficulty}" ({difficulty_guide[difficulty]}).

Chủ đề cụ thể: {topic_guide.get(topic, topic)}{global_emphasis}{football_variety}{avoid_duplicate}

Yêu cầu:
1. Câu hỏi phải thú vị, có giá trị kiến thức
2. 4 đáp án phải hợp lý, không quá dễ loại trừ
3. Giải thích phải chi tiết, có thông tin bổ ích
4. Hoàn toàn bằng tiếng Việt
5. Câu hỏi phải CỤ THỂ và ĐỘC ĐÁO

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
                "content": "Bạn là chuyên gia tạo câu hỏi trắc nghiệm chất lượng cao về các chủ đề toàn cầu. Chỉ trả về JSON, không giải thích thêm."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        response = await call_api(messages, max_tokens=600)
        
        if not response:
            return None
            
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
        
        quiz = json.loads(response)
        
        if storage and storage.is_duplicate_question(quiz["question"]):
            logger.warning(f"Duplicate question detected: {quiz['question'][:50]}...")
            if retry_count < MAX_QUIZ_RETRY:
                logger.info(f"Retrying to generate new quiz (attempt {retry_count + 2}/{MAX_QUIZ_RETRY + 1})")
                await asyncio.sleep(1)
                return await generate_quiz_with_gemini(topic, difficulty, retry_count + 1)
            else:
                logger.error(f"Max retries reached, using duplicate quiz")
        
        quiz["topic"] = f"{topic} ({difficulty.title()})"
        quiz["source"] = "Gemini AI"
        quiz["difficulty"] = difficulty
        quiz["created_at"] = get_vietnam_time().isoformat()
        quiz["generated"] = True
        
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
        topic = random.choice(QUIZ_TOPICS)
        difficulty = random.choice(DIFFICULTIES)
        
        logger.info(f"Generating new quiz: {topic} - {difficulty}")
        quiz = await generate_quiz_with_gemini(topic, difficulty)
        
        if quiz:
            if storage:
                storage.add_translated_quiz(quiz)
            return quiz
        
        if storage:
            quiz_pool = storage.get_translated_quiz_pool()
            if quiz_pool:
                filtered_pool = [
                    q for q in quiz_pool 
                    if topic in q.get('topic', '') and difficulty in q.get('topic', '')
                ]
                
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
    for msg_id in messages[:-MAX_GAME_MESSAGES]:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except:
            pass
    game_messages[chat_id] = messages[-MAX_GAME_MESSAGES:] if len(messages) > MAX_GAME_MESSAGES else messages

async def add_game_message(chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE):
    if chat_id not in game_messages:
        game_messages[chat_id] = []
    game_messages[chat_id].append(message_id)
    await delete_old_messages(chat_id, context)

async def cleanup_game(chat_id: int, keep_active: bool = False):
    if not keep_active and chat_id in active_games:
        del active_games[chat_id]
    
    if chat_id in game_timeouts:
        try:
            game_timeouts[chat_id].cancel()
        except:
            pass
        del game_timeouts[chat_id]
    
    if chat_id in game_start_times:
        del game_start_times[chat_id]
    
    if chat_id in quiz_scheduling:
        del quiz_scheduling[chat_id]
    
    if chat_id in game_messages and len(game_messages[chat_id]) > MAX_GAME_MESSAGES:
        game_messages[chat_id] = game_messages[chat_id][-MAX_GAME_MESSAGES:]
    
    keys_to_remove = [key for key in user_answered.keys() if key[0] == chat_id]
    for key in keys_to_remove:
        del user_answered[key]

async def schedule_next_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, delay: int = 5):
    try:
        if chat_id in quiz_scheduling:
            last_schedule = quiz_scheduling[chat_id]
            if (get_vietnam_time() - last_schedule).total_seconds() < delay + 2:
                logger.warning(f"Quiz already scheduled recently for chat {chat_id}, skipping")
                return
        
        quiz_scheduling[chat_id] = get_vietnam_time()
        logger.info(f"Scheduled next quiz for chat {chat_id} after {delay}s delay")
        
        await asyncio.sleep(delay)
        
        if chat_id not in minigame_groups:
            logger.info(f"Chat {chat_id} no longer in minigame groups")
            return
            
        if chat_id in active_games:
            logger.warning(f"Game already active for chat {chat_id} after delay")
            return
        
        logger.info(f"Creating new quiz for chat {chat_id}")
        await start_random_minigame(chat_id, context)
        
    except Exception as e:
        logger.error(f"Error scheduling next quiz for {chat_id}: {e}")
    finally:
        if chat_id in quiz_scheduling:
            del quiz_scheduling[chat_id]

async def game_timeout_handler(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.sleep(GAME_TIMEOUT)
        
        logger.info(f"Game timeout for chat {chat_id}")
        
        if chat_id in active_games:
            game_info = active_games[chat_id]
            game = game_info.get("game")
            
            try:
                msg = f"⏰ **Hết 10 phút! Chuyển câu mới...**\n\n"
                if game_info["type"] == "quiz" and game and game.current_quiz:
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
    if chat_id not in quiz_creation_locks:
        quiz_creation_locks[chat_id] = asyncio.Lock()
    
    if chat_id in active_games or chat_id in quiz_scheduling:
        logger.warning(f"Game already active/scheduling for chat {chat_id}")
        return
    
    async with quiz_creation_locks[chat_id]:
        try:
            logger.info(f"Starting minigame for chat {chat_id}")
            
            if chat_id not in minigame_groups:
                logger.info(f"Chat {chat_id} not in minigame groups")
                return
            
            if chat_id in active_games:
                logger.warning(f"Game already active for chat {chat_id}, skipping")
                return
            
            active_games[chat_id] = {"type": "quiz", "game": None, "minigame": True, "creating": True}
            quiz_scheduling[chat_id] = get_vietnam_time()
            
            await cleanup_game(chat_id, keep_active=True)
            
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
                
                if chat_id in active_games:
                    del active_games[chat_id]
                if chat_id in quiz_scheduling:
                    del quiz_scheduling[chat_id]
                
                asyncio.create_task(schedule_next_quiz(chat_id, context, 30))
                return
            
            game.current_quiz = quiz
            active_games[chat_id] = {"type": "quiz", "game": game, "minigame": True}
            game_start_times[chat_id] = get_vietnam_time()
            
            keyboard = []
            for option in quiz["options"]:
                keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            source_text = ""
            if quiz.get("generated"):
                source_text = " ✨"
            
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
            
            if chat_id in quiz_scheduling:
                del quiz_scheduling[chat_id]
                
            game_timeouts[chat_id] = asyncio.create_task(game_timeout_handler(chat_id, context))
            logger.info(f"Quiz created successfully for chat {chat_id}")
            
        except Exception as e:
            logger.error(f"Error in start_random_minigame for {chat_id}: {e}")
            if chat_id in active_games:
                del active_games[chat_id]
            if chat_id in quiz_scheduling:
                del quiz_scheduling[chat_id]
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
/top - BXH toàn cầu
/gtop - BXH nhóm này
/bal - Xem số dư
/stats - Thống kê cá nhân

🛠️ **Admin:**
/clean - Dọn dẹp bot (chỉ admin)
/stopminigame - Dừng minigame trong nhóm

📚 **Quiz pool:** {quiz_count} câu ({unique_count} unique)
📁 **Auto split files at 3MB**
🏆 **Mỗi nhóm có BXH riêng!**

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

async def gtop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        
        if chat.type == "private":
            await update.message.reply_text("⚠️ Lệnh này chỉ dùng được trong nhóm!")
            return
        
        if not storage:
            await update.message.reply_text("📊 Hệ thống đang bảo trì")
            return
        
        group_name = chat.title or "Nhóm này"
        leaderboard = storage.get_group_leaderboard(chat.id)
        
        if not leaderboard:
            await update.message.reply_text(f"📊 **BXH {group_name}**\n\nChưa có dữ liệu!\nHãy chơi quiz để lên bảng!")
            return
        
        msg = f"🏆 **BXH {group_name}**\n"
        msg += "────────────────\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, score) in enumerate(leaderboard):
            medal = medals[i] if i < 3 else f"{i+1}."
            msg += f"{medal} {name}: {_fmt_money(score)} điểm\n"
        
        user = update.effective_user
        user_stats = storage.get_user_group_stats(chat.id, user.id)
        if user_stats['score'] > 0:
            msg += f"\n📊 **Điểm của bạn:** {_fmt_money(user_stats['score'])}"
            msg += f"\n🏅 **Số lần thắng:** {user_stats['games_won']}"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in gtop command: {e}", exc_info=True)
        await update.message.reply_text("📊 Không thể tải bảng xếp hạng nhóm")

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
        
        if user.id != ADMIN_ID:
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
        
        msg = "🏆 **BẢNG XẾP HẠNG TOÀN CẦU**\n"
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
        
        await query.answer(cache_time=5)
        
        data = query.data
        chat_id = update.effective_chat.id
        user = update.effective_user
        username = user.username or user.first_name
        
        if chat_id not in active_games:
            await query.answer("⏰ Quiz đã kết thúc!", show_alert=True)
            return
        
        user_key = (chat_id, user.id)
        if user_key in user_answered:
            await query.answer("⚠️ Bạn đã trả lời rồi!", show_alert=True)
            return
        
        game_info = active_games[chat_id]
        
        if game_info.get("creating"):
            await query.answer("⏳ Quiz đang được tạo...", show_alert=True)
            return
            
        game = game_info["game"]
        
        user_answered[user_key] = True
        
        if data.startswith("quiz_") and game_info["type"] == "quiz":
            quiz = game.current_quiz
            answer = data.split("_")[1]
            
            correct_option = quiz['correct']
            correct_answer_text = quiz.get('correct_answer', '')
            
            if answer == correct_option:
                points = 300
                result = f"🎉 **{username}** trả lời chính xác! (+{points}đ)\n\n"
                result += f"✅ Đáp án: **{correct_option}**"
                if correct_answer_text:
                    result += f" - {correct_answer_text}"
                result += f"\n💡 {quiz.get('explanation', '')}"
                
                update_user_balance(user.id, username, points, "quiz")
                
                chat = update.effective_chat
                if chat.type in ["group", "supergroup"] and storage:
                    storage.update_group_score(chat.id, user.id, username, points)
                    
            else:
                result = f"❌ **{username}** - Chưa đúng!\n\n"
                result += f"✅ Đáp án đúng: **{correct_option}**"
                if correct_answer_text:
                    result += f" - {correct_answer_text}"
                result += f"\n💡 {quiz.get('explanation', '')}"
            
            try:
                await query.delete_message()
            except:
                pass
            
            msg = await context.bot.send_message(chat_id, result, parse_mode="Markdown")
            
            if game_info.get("minigame"):
                await add_game_message(chat_id, msg.message_id, context)
            
            await asyncio.sleep(1)
            
            await cleanup_game(chat_id)
            
            if chat_id in minigame_groups and chat_id not in quiz_scheduling:
                asyncio.create_task(schedule_next_quiz(chat_id, context, 5))
        
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
            stuck_games = []
            current_time = get_vietnam_time()
            
            for chat_id in list(minigame_groups):
                try:
                    should_restart = False
                    
                    if chat_id not in active_games:
                        should_restart = True
                    elif chat_id in game_start_times:
                        duration = (current_time - game_start_times[chat_id]).total_seconds()
                        if duration > GAME_TIMEOUT + 60:
                            should_restart = True
                    
                    if chat_id in active_games:
                        game = active_games[chat_id]
                        if game.get("creating") and not game.get("game"):
                            should_restart = True
                    
                    if should_restart:
                        stuck_games.append(chat_id)
                        
                except Exception as e:
                    logger.error(f"Check failed for {chat_id}: {e}")
            
            for chat_id in stuck_games:
                logger.warning(f"Restarting stuck game for chat {chat_id}")
                await cleanup_game(chat_id)
                await asyncio.sleep(2)
                asyncio.create_task(start_random_minigame(chat_id, application))
                    
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
            
            inactive_chats = []
            for chat_id in list(quiz_creation_locks.keys()):
                if chat_id not in minigame_groups and chat_id not in active_games:
                    inactive_chats.append(chat_id)
            
            for chat_id in inactive_chats:
                del quiz_creation_locks[chat_id]
            
            inactive_users = []
            for user_id in list(chat_history.keys()):
                if len(chat_history[user_id]) == 0:
                    inactive_users.append(user_id)
            
            for user_id in inactive_users:
                del chat_history[user_id]
            
            logger.info(f"Memory cleanup completed. Active chats: {len(chat_history)}, Active games: {len(active_games)}, Locks: {len(quiz_creation_locks)}")
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
    logger.info("Bot started successfully - Optimized version!")

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
    application.add_handler(CommandHandler("gtop", gtop_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("clean", clean_cmd))
    application.add_handler(CommandHandler("stopminigame", stopminigame_cmd))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot - Optimized Version! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
