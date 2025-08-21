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
QUIZ_GEN_MODEL = "alibaba/qwen-3-235b"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "htuananh1/Data-manager"

START_BALANCE = 1000
CHAT_HISTORY_LIMIT = 6
GAME_TIMEOUT = 600
MAX_GAME_MESSAGES = 5
CHAT_SAVE_INTERVAL = 300
QUIZ_CHECK_INTERVAL = 60
MAX_QUIZ_RETRY = 2
MAX_FILE_SIZE = 3 * 1024 * 1024
ADMIN_ID = 2026797305
VIETNAM_TZ = timezone(timedelta(hours=7))
NEXT_QUIZ_DELAY = 0
QUIZ_CREATION_TIMEOUT = 8
QUIZ_GEN_BATCH_SIZE = 5  # Giảm xuống để save thường xuyên hơn
QUIZ_GEN_DELAY = 1  # Giảm delay để tạo nhanh hơn

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

quiz_generation_active = False
quiz_generation_task = None
quiz_generation_stats = {"total": 0, "duplicates": 0, "errors": 0}

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
            self._full_quiz_pool = []
            self._last_pool_update = None
            self._file_sizes_cache = {}  # Cache file sizes
            logger.info("GitHub storage initialized successfully")
        except Exception as e:
            logger.error(f"Failed to init GitHub storage: {e}")
            raise
        
    def _get_file_content(self, path: str) -> Optional[dict]:
        try:
            file = self.repo.get_contents(path, ref=self.branch)
            content = base64.b64decode(file.content).decode('utf-8')
            data = json.loads(content)
            self._file_sizes_cache[path] = file.size  # Update cache
            return data
        except Exception as e:
            logger.warning(f"File {path} not found or error: {e}")
            return None
    
    def _get_file_size(self, path: str) -> int:
        # Check cache first
        if path in self._file_sizes_cache:
            return self._file_sizes_cache[path]
            
        try:
            file = self.repo.get_contents(path, ref=self.branch)
            self._file_sizes_cache[path] = file.size
            return file.size
        except:
            return 0
    
    def _estimate_json_size(self, data: dict) -> int:
        """Ước tính kích thước JSON"""
        json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        return len(json_str.encode('utf-8'))
    
    def _get_current_quiz_file(self) -> str:
        """Tìm file quiz hiện tại hoặc tạo file mới nếu cần"""
        base_path = "data/translated_quiz_pool"
        
        # Check file gốc
        main_file = f"{base_path}.json"
        main_size = self._get_file_size(main_file)
        
        if main_size == 0:
            # File chưa tồn tại, dùng luôn
            return main_file
        elif main_size < MAX_FILE_SIZE - 50000:  # Để buffer 50KB
            return main_file
        
        # Tìm file đánh số
        index = 1
        while True:
            file_path = f"{base_path}_{index}.json"
            size = self._get_file_size(file_path)
            
            if size == 0:
                # File chưa tồn tại
                logger.info(f"Creating new quiz file: {file_path}")
                return file_path
            elif size < MAX_FILE_SIZE - 50000:
                # File còn chỗ
                return file_path
            
            index += 1
            if index > 100:  # Safety limit
                logger.error("Too many quiz files!")
                break
        
        return f"{base_path}_last.json"
    
    def _get_all_quiz_files(self) -> List[str]:
        files = []
        base_path = "data/translated_quiz_pool"
        
        # File gốc
        if self._get_file_size(f"{base_path}.json") > 0:
            files.append(f"{base_path}.json")
        
        # Các file đánh số
        index = 1
        while True:
            file_path = f"{base_path}_{index}.json"
            if self._get_file_size(file_path) == 0:
                break
            files.append(file_path)
            index += 1
            if index > 100:  # Safety limit
                break
        
        return files
    
    def _save_file(self, path: str, data: dict, message: str):
        try:
            if "translated_quiz_pool" in path and "questions" in data:
                # Compact JSON format để tiết kiệm space
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
            
            content_size = len(content.encode('utf-8'))
            
            try:
                file = self.repo.get_contents(path, ref=self.branch)
                self.repo.update_file(path, message, content, file.sha, self.branch)
                logger.info(f"Updated file: {path} (size: {content_size:,} bytes)")
            except:
                self.repo.create_file(path, message, content, self.branch)
                logger.info(f"Created file: {path} (size: {content_size:,} bytes)")
            
            # Update cache
            self._file_sizes_cache[path] = content_size
                
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
    
    async def batch_save(self, force_quiz: bool = False):
        if not self._pending_updates and not self._chat_save_queue:
            return
            
        timestamp = get_vietnam_time().isoformat()
        
        # Save scores
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
        
        # Save group scores
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
        
        # Save quiz với smart file splitting
        if "translated_quiz" in self._pending_updates or force_quiz:
            added_total = 0
            duplicate_total = 0
            
            # Group quiz by files
            file_groups = {}
            
            for quiz in self._pending_updates.get("translated_quiz", []):
                normalized_question = self._normalize_question(quiz.get("question"))
                
                # Check duplicate
                if normalized_question in self._quiz_questions_cache:
                    duplicate_total += 1
                    logger.warning(f"Skipped duplicate quiz: {quiz['question'][:50]}...")
                    continue
                
                # Find appropriate file
                current_file = self._get_current_quiz_file()
                
                if current_file not in file_groups:
                    # Load existing data for this file
                    existing_data = self._get_file_content(current_file) or {"questions": []}
                    file_groups[current_file] = {
                        "questions": existing_data.get("questions", []),
                        "new_questions": []
                    }
                
                # Add to appropriate file group
                file_groups[current_file]["new_questions"].append(quiz)
                self._quiz_questions_cache.add(normalized_question)
                self._full_quiz_pool.append(quiz)
                added_total += 1
            
            # Save each file
            for file_path, file_data in file_groups.items():
                if file_data["new_questions"]:
                    # Merge existing and new questions
                    all_questions = file_data["questions"] + file_data["new_questions"]
                    
                    # Check if need to split
                    quiz_data = {
                        "questions": all_questions,
                        "total": len(all_questions),
                        "last_updated": timestamp
                    }
                    
                    estimated_size = self._estimate_json_size(quiz_data)
                    
                    if estimated_size > MAX_FILE_SIZE:
                        # Split into multiple files
                        logger.info(f"File {file_path} too large ({estimated_size:,} bytes), splitting...")
                        
                        # Keep existing questions in current file
                        quiz_data["questions"] = file_data["questions"]
                        quiz_data["total"] = len(file_data["questions"])
                        self._save_file(file_path, quiz_data, f"Keep existing {len(file_data['questions'])} quizzes")
                        
                        # Save new questions to new file
                        new_file = self._get_current_quiz_file()
                        new_quiz_data = {
                            "questions": file_data["new_questions"],
                            "total": len(file_data["new_questions"]),
                            "last_updated": timestamp
                        }
                        self._save_file(new_file, new_quiz_data, f"Added {len(file_data['new_questions'])} new quizzes")
                    else:
                        # Save all to current file
                        self._save_file(file_path, quiz_data, f"Added {len(file_data['new_questions'])} new quizzes")
            
            if added_total > 0:
                logger.info(f"Batch save completed: {added_total} added, {duplicate_total} duplicates")
                self._last_pool_update = get_vietnam_time()
        
        # Save chat history
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
        
        # Load cache if empty
        if not self._quiz_questions_cache:
            logger.info("Loading quiz cache...")
            for file_path in self._get_all_quiz_files():
                quiz_data = self._get_file_content(file_path)
                if quiz_data and "questions" in quiz_data:
                    for q in quiz_data["questions"]:
                        self._quiz_questions_cache.add(self._normalize_question(q.get("question", "")))
            logger.info(f"Loaded {len(self._quiz_questions_cache)} unique questions to cache")
        
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
        # Use cache if available and fresh
        if self._full_quiz_pool and self._last_pool_update:
            if (get_vietnam_time() - self._last_pool_update).seconds < 300:
                return self._full_quiz_pool
        
        # Reload from files
        all_quizzes = []
        for file_path in self._get_all_quiz_files():
            data = self._get_file_content(file_path)
            if data and "questions" in data:
                all_quizzes.extend(data["questions"])
                logger.info(f"Loaded {len(data['questions'])} quizzes from {file_path}")
        
        self._full_quiz_pool = all_quizzes
        self._last_pool_update = get_vietnam_time()
        logger.info(f"Total quiz pool: {len(all_quizzes)} questions")
        return all_quizzes
    
    def get_random_quiz(self) -> Optional[dict]:
        quiz_pool = self.get_translated_quiz_pool()
        if quiz_pool:
            return random.choice(quiz_pool)
        return None
    
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
    
    def get_quiz_stats(self) -> dict:
        """Lấy thống kê về quiz pool"""
        total_quizzes = 0
        files = self._get_all_quiz_files()
        
        for file_path in files:
            size = self._get_file_size(file_path)
            data = self._get_file_content(file_path)
            if data:
                total_quizzes += len(data.get("questions", []))
        
        return {
            "total_files": len(files),
            "total_quizzes": total_quizzes,
            "unique_quizzes": len(self._quiz_questions_cache)
        }

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

async def call_api(messages: List[dict], model: str = None, max_tokens: int = 400, retry: int = 2) -> str:
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
                "temperature": 0.8,  # Tăng để có variety
                "top_p": 0.9
            }
            
            response = requests.post(
                f"{BASE_URL}/chat/completions",
                headers=headers,
                json=data,
                timeout=10
            )
            
            if response.status_code == 429:
                wait_time = min(2 ** attempt, 5)
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

async def generate_quiz_with_qwen(topic: str, difficulty: str, variation: int = 0) -> Optional[dict]:
    """Tạo quiz với Qwen model với variation để tránh trùng"""
    try:
        difficulty_guide = {
            "bình thường": "dễ, kiến thức phổ thông",
            "khó": "khó, cần kiến thức sâu", 
            "cực khó": "rất khó, chỉ người am hiểu mới biết"
        }
        
        # Thêm variation prompts
        variations = [
            "Tạo câu hỏi độc đáo, chưa từng thấy",
            "Tạo câu hỏi về góc nhìn mới lạ",
            "Tạo câu hỏi về chi tiết ít người biết",
            "Tạo câu hỏi với fact thú vị",
            "Tạo câu hỏi về sự kiện gần đây",
            "Tạo câu hỏi về kỷ lục đặc biệt"
        ]
        
        var_prompt = variations[variation % len(variations)] if variation > 0 else ""
        
        prompt = f"""Tạo câu hỏi trắc nghiệm {difficulty_guide[difficulty]} về {topic}.
{var_prompt}

Format JSON ngắn gọn:
{{
  "question": "câu hỏi",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "correct": "A/B/C/D",
  "correct_answer": "đáp án",
  "explanation": "giải thích"
}}"""

        messages = [
            {"role": "user", "content": prompt}
        ]
        
        response = await call_api(messages, model=QUIZ_GEN_MODEL, max_tokens=400)
        
        if not response:
            return None
            
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
        
        quiz = json.loads(response)
        
        quiz["topic"] = f"{topic} ({difficulty.title()})"
        quiz["source"] = "Qwen AI"
        quiz["difficulty"] = difficulty
        quiz["created_at"] = get_vietnam_time().isoformat()
        quiz["generated"] = True
        
        return quiz
        
    except Exception as e:
        logger.error(f"Error generating quiz with Qwen: {e}")
        return None

async def continuous_quiz_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tạo quiz liên tục với tốc độ nhanh"""
    global quiz_generation_active, quiz_generation_stats
    
    chat_id = update.effective_chat.id if update else None
    variation_counter = 0
    
    while quiz_generation_active:
        try:
            # Random topic và difficulty
            topic = random.choice(QUIZ_TOPICS)
            difficulty = random.choice(DIFFICULTIES)
            
            # Tạo quiz với variation
            quiz = await generate_quiz_with_qwen(topic, difficulty, variation_counter)
            variation_counter += 1
            
            if quiz:
                # Check trùng lặp
                if storage and not storage.is_duplicate_question(quiz["question"]):
                    storage.add_translated_quiz(quiz)
                    quiz_generation_stats["total"] += 1
                    logger.info(f"Generated quiz #{quiz_generation_stats['total']}: {quiz['question'][:50]}...")
                    
                    # Update status mỗi 10 quiz (thay vì 5)
                    if quiz_generation_stats["total"] % 10 == 0:
                        # Force save
                        await storage.batch_save(force_quiz=True)
                        
                        # Send status
                        if chat_id:
                            stats = storage.get_quiz_stats()
                            status_msg = f"🎯 **Tiến độ tạo quiz:**\n"
                            status_msg += f"✅ Đã tạo: {quiz_generation_stats['total']}\n"
                            status_msg += f"❌ Trùng: {quiz_generation_stats['duplicates']}\n"
                            status_msg += f"⚠️ Lỗi: {quiz_generation_stats['errors']}\n\n"
                            status_msg += f"📊 **Tổng trong pool:**\n"
                            status_msg += f"📁 Files: {stats['total_files']}\n"
                            status_msg += f"📝 Total: {stats['total_quizzes']}"
                            
                            try:
                                await context.bot.send_message(chat_id, status_msg, parse_mode="Markdown")
                            except:
                                pass
                else:
                    quiz_generation_stats["duplicates"] += 1
                    logger.warning(f"Duplicate quiz detected")
            else:
                quiz_generation_stats["errors"] += 1
                logger.error("Failed to generate quiz")
            
            # Save batch mỗi 5 quiz
            if quiz_generation_stats["total"] % QUIZ_GEN_BATCH_SIZE == 0 and storage:
                await storage.batch_save(force_quiz=True)
            
            # Delay ngắn
            await asyncio.sleep(QUIZ_GEN_DELAY)
            
        except Exception as e:
            logger.error(f"Error in continuous quiz generation: {e}")
            quiz_generation_stats["errors"] += 1
            await asyncio.sleep(3)
    
    # Final save
    if storage:
        await storage.batch_save(force_quiz=True)
    
    # Send final stats
    if chat_id:
        stats = storage.get_quiz_stats() if storage else {}
        final_msg = f"✅ **Đã dừng tạo quiz!**\n\n"
        final_msg += f"📊 **Kết quả:**\n"
        final_msg += f"✅ Tạo mới: {quiz_generation_stats['total']}\n"
        final_msg += f"❌ Trùng: {quiz_generation_stats['duplicates']}\n"
        final_msg += f"⚠️ Lỗi: {quiz_generation_stats['errors']}\n\n"
        if stats:
            final_msg += f"📚 **Tổng quiz pool:**\n"
            final_msg += f"📁 Files: {stats.get('total_files', 0)}\n"
            final_msg += f"📝 Total: {stats.get('total_quizzes', 0)}"
        
        try:
            await context.bot.send_message(chat_id, final_msg, parse_mode="Markdown")
        except:
            pass

class QuizGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.current_quiz = None
        
    async def get_quiz_from_pool(self) -> dict:
        if storage:
            quiz = storage.get_random_quiz()
            if quiz:
                logger.info(f"Using quiz from pool: {quiz['question'][:50]}...")
                return quiz
        
        logger.error("No quiz available in pool")
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

async def start_random_minigame(chat_id: int, context: ContextTypes.DEFAULT_TYPE, show_loading: bool = False):
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
            
            game = QuizGame(chat_id)
            quiz = await game.get_quiz_from_pool()
            
            if not quiz:
                logger.error(f"No quiz available for chat {chat_id}")
                error_msg = await context.bot.send_message(
                    chat_id, 
                    "❌ Không có quiz trong dữ liệu!\n"
                    "Admin vui lòng dùng /genquiz để tạo thêm quiz."
                )
                await add_game_message(chat_id, error_msg.message_id, context)
                
                if chat_id in active_games:
                    del active_games[chat_id]
                if chat_id in quiz_scheduling:
                    del quiz_scheduling[chat_id]
                
                return
            
            game.current_quiz = quiz
            active_games[chat_id] = {"type": "quiz", "game": game, "minigame": True}
            game_start_times[chat_id] = get_vietnam_time()
            
            keyboard = []
            for option in quiz["options"]:
                keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            source_text = f" [{quiz.get('source', 'Pool')}]"
            
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
            
            if chat_id in quiz_scheduling:
                del quiz_scheduling[chat_id]
                
            game_timeouts[chat_id] = asyncio.create_task(game_timeout_handler(chat_id, context))
            logger.info(f"Quiz started successfully for chat {chat_id}")
            
        except Exception as e:
            logger.error(f"Error in start_random_minigame for {chat_id}: {e}")
            if chat_id in active_games:
                del active_games[chat_id]
            if chat_id in quiz_scheduling:
                del quiz_scheduling[chat_id]
            await cleanup_game(chat_id)

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
            asyncio.create_task(start_random_minigame(chat_id, context, False))
            
    except asyncio.CancelledError:
        logger.info(f"Timeout handler cancelled for chat {chat_id}")
    except Exception as e:
        logger.error(f"Error in timeout handler for {chat_id}: {e}")
        await cleanup_game(chat_id)
        if chat_id in minigame_groups:
            await asyncio.sleep(5)
            asyncio.create_task(start_random_minigame(chat_id, context, False))

async def genquiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global quiz_generation_active, quiz_generation_task, quiz_generation_stats
    
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Chỉ admin mới dùng được lệnh này!")
        return
    
    if quiz_generation_active:
        await update.message.reply_text("⚠️ Đang tạo quiz rồi! Dùng /stopgen để dừng.")
        return
    
    quiz_generation_active = True
    quiz_generation_stats = {"total": 0, "duplicates": 0, "errors": 0}
    
    await update.message.reply_text(
        "🚀 **Bắt đầu tạo quiz với Qwen-3-235B!**\n\n"
        "⚡ Tốc độ: 1 quiz/giây\n"
        "📊 Update tiến độ mỗi 10 quiz\n"
        "💾 Auto save mỗi 5 quiz\n"
        "🛑 Dùng /stopgen để dừng",
        parse_mode="Markdown"
    )
    
    quiz_generation_task = asyncio.create_task(continuous_quiz_generation(update, context))

async def stopgen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global quiz_generation_active, quiz_generation_task
    
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Chỉ admin mới dùng được lệnh này!")
        return
    
    if not quiz_generation_active:
        await update.message.reply_text("⚠️ Không có tiến trình tạo quiz nào đang chạy!")
        return
    
    quiz_generation_active = False
    
    if quiz_generation_task:
        quiz_generation_task.cancel()
        quiz_generation_task = None
    
    await update.message.reply_text("⏸️ **Đang dừng và lưu quiz...**", parse_mode="Markdown")

# ... (phần còn lại của code giữ nguyên như trước)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer(cache_time=1)
        
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
            
            try:
                await query.delete_message()
            except:
                pass
            
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
            
            msg = await context.bot.send_message(chat_id, result, parse_mode="Markdown")
            
            if game_info.get("minigame"):
                await add_game_message(chat_id, msg.message_id, context)
            
            await cleanup_game(chat_id)
            
            if chat_id in minigame_groups and chat_id not in quiz_scheduling:
                asyncio.create_task(start_random_minigame(chat_id, context, False))
        
        elif data.startswith("disabled_"):
            await query.answer("⚠️ Bạn đã trả lời rồi!", show_alert=True)
            return
                        
    except Exception as e:
        logger.error(f"Error in button callback: {e}")
        try:
            await query.answer("❌ Có lỗi xảy ra!", show_alert=True)
        except:
            pass

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
            
            if chat_id not in active_games:
                asyncio.create_task(start_random_minigame(chat.id, context))
        
        quiz_stats = {"total_quizzes": 0, "total_files": 0}
        if storage:
            quiz_stats = storage.get_quiz_stats()
        
        message = f"""👋 Xin chào {username}! Mình là Linh Bot!

💰 Số dư của bạn: {_fmt_money(balance)}

🎮 **Minigame tự động trong nhóm**
Bot dùng quiz từ pool có sẵn (không tạo mới)

📚 **Các chủ đề:**
⚽ Bóng đá | 🌍 Địa lý | 📜 Lịch sử
💡 Kĩ năng sống | 🦁 Động vật | 🎌 Anime & Manga

📝 **Chơi riêng lẻ:**
/quiz - Quiz ngẫu nhiên từ pool

🔧 **Admin Commands:**
/genquiz - Tạo quiz liên tục với Qwen-3-235B
/stopgen - Dừng tạo quiz

📊 **Thông tin:**
/top - BXH toàn cầu
/gtop - BXH nhóm này
/bal - Xem số dư
/stats - Thống kê cá nhân

🛠️ **Quản lý:**
/clean - Dọn dẹp bot (chỉ admin)
/stopminigame - Dừng minigame trong nhóm

📚 **Quiz pool:** {quiz_stats['total_quizzes']} câu ({quiz_stats['total_files']} files)
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

async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        
        if chat_id in active_games:
            await update.message.reply_text("⚠️ Đang có game khác!")
            return
        
        game = QuizGame(chat_id)
        quiz = await game.get_quiz_from_pool()
        
        if not quiz:
            await update.message.reply_text("❌ Không có quiz trong pool! Vui lòng tạo thêm quiz bằng /genquiz")
            return
        
        game.current_quiz = quiz
        active_games[chat_id] = {"type": "quiz", "game": game}
        
        keyboard = []
        for option in quiz["options"]:
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        source_text = f" [{quiz.get('source', 'Pool')}]"
        
        await update.message.reply_text(
            f"❓ **{quiz['topic']}{source_text}**\n\n{quiz['question']}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in quiz: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

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
            await update.message.reply_text(f"📊 **BXH {group_name}**\n\nChưa có dữ liệu!\nHãy chơi quiz để lên bảng!", parse_mode="Markdown")
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
                    msg += f"• Quiz: {count} lần\n"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in stats command: {e}", exc_info=True)
        user = update.effective_user
        username = user.username or user.first_name
        balance = get_user_balance(user.id)
        msg = f"📊 **{username}**\n\n💰 Số dư: {_fmt_money(balance)}"
        await update.message.reply_text(msg, parse_mode="Markdown")

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
                            create_time = quiz_scheduling.get(chat_id)
                            if create_time and (current_time - create_time).total_seconds() > 30:
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
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Error starting minigame for {chat_id}: {e}")

async def post_init(application: Application) -> None:
    asyncio.create_task(periodic_batch_save(application))
    asyncio.create_task(cleanup_memory(application))
    asyncio.create_task(quiz_health_check(application))
    asyncio.create_task(load_minigame_groups(application))
    logger.info("Bot started - Optimized file splitting version!")

async def post_shutdown(application: Application) -> None:
    global quiz_generation_active, quiz_generation_task
    
    quiz_generation_active = False
    if quiz_generation_task:
        quiz_generation_task.cancel()
    
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
    application.add_handler(CommandHandler("genquiz", genquiz_cmd))
    application.add_handler(CommandHandler("stopgen", stopgen_cmd))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot - Fixed file splitting! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
