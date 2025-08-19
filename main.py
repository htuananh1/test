import os
import random
import asyncio
import logging
import requests
import json
import base64
import unicodedata
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
from collections import deque
from github import Github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = "alibaba/qwen-3-235b"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "htuananh1/Data-manager"

START_BALANCE = 1000
CHAT_HISTORY_LIMIT = 6
GAME_TIMEOUT = 600
WRONG_ANSWER_COOLDOWN = 5
MAX_GAME_MESSAGES = 5
CHAT_SAVE_INTERVAL = 300
QUIZ_CHECK_INTERVAL = 60  # Check mỗi 60 giây xem có cần tạo quiz mới không

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
        
        if "quiz" in self._pending_updates:
            quiz_data = self._get_file_content("data/quiz_pool.json") or {"questions": []}
            
            for quiz in self._pending_updates["quiz"]:
                duplicate = False
                for existing in quiz_data["questions"]:
                    if existing.get("question") == quiz.get("question"):
                        duplicate = True
                        break
                if not duplicate:
                    quiz_data["questions"].append(quiz)
            
            quiz_data["total"] = len(quiz_data["questions"])
            quiz_data["last_updated"] = timestamp
            
            self._save_file("data/quiz_pool.json", quiz_data, f"Batch update quiz at {timestamp}")
        
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
    
    def get_quiz_pool(self) -> List[dict]:
        data = self._get_file_content("data/quiz_pool.json")
        if data and "questions" in data:
            return data["questions"]
        return []
    
    def add_quiz(self, quiz: dict):
        self.queue_update("quiz", quiz)
    
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
game_start_times: Dict[int, datetime] = {}  # Theo dõi thời gian bắt đầu game
wrong_answer_cooldowns: Dict[Tuple[int, int], datetime] = {}
minigame_groups: Set[int] = set()
user_answered: Dict[Tuple[int, int], bool] = {}

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
            "temperature": 0.3
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

class QuizGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.score = 0
        self.current_quiz = None
        
    async def generate_quiz(self) -> dict:
        existing_questions = []
        if storage:
            pool = storage.get_quiz_pool()
            existing_questions = [q.get("question", "") for q in pool]
        
        prompt = """Hãy tạo ra một câu hỏi trắc nghiệm bằng tiếng Việt (1–3 câu), thuộc một trong các chủ đề sau:
- Bóng đá thế giới
- Công nghệ và khoa học
- Địa danh nổi tiếng thế giới
- Động vật và thực vật
- Nghệ thuật và giải trí
- Lịch sử thế giới
- Thể thao Olympic
- Văn học và ngôn ngữ
- Ẩm thực thế giới
- Thiên nhiên và môi trường

Yêu cầu:
1. Câu hỏi có 4 đáp án lựa chọn A, B, C, D.  
2. Chỉ có duy nhất 1 đáp án đúng.  
3. Nội dung chính xác, rõ ràng, không mơ hồ.
4. Thêm giải thích chi tiết cho đáp án đúng.
5. Xuất ra theo định dạng:  

❓ [Chủ đề]  
[Câu hỏi]  

A. ...  
B. ...  
C. ...  
D. ...  

✅ Đáp án đúng: [Ký tự A/B/C/D]
💡 Giải thích: [Giải thích chi tiết tại sao đáp án này đúng]"""

        messages = [{"role": "user", "content": prompt}]
        
        max_retries = 5
        for retry in range(max_retries):
            try:
                response = await call_api(messages, model=CHAT_MODEL, max_tokens=600)
                
                if response:
                    lines = response.strip().split('\n')
                    
                    topic = ""
                    question = ""
                    options = []
                    correct = ""
                    explanation = ""
                    
                    for line in lines:
                        line = line.strip()
                        if line.startswith("❓"):
                            topic = line.replace("❓", "").strip()
                        elif line.startswith("A."):
                            options.append(line)
                        elif line.startswith("B."):
                            options.append(line)
                        elif line.startswith("C."):
                            options.append(line)
                        elif line.startswith("D."):
                            options.append(line)
                        elif line.startswith("✅"):
                            correct = line.split(":")[-1].strip()[0].upper()
                        elif line.startswith("💡"):
                            explanation = line.replace("💡 Giải thích:", "").strip()
                        elif line and not line.startswith(("❓", "A.", "B.", "C.", "D.", "✅", "💡")):
                            if not question:
                                question = line
                    
                    if question in existing_questions:
                        logger.info(f"Duplicate question found, retrying... (attempt {retry + 1})")
                        continue
                    
                    if topic and question and len(options) == 4 and correct in ["A", "B", "C", "D"]:
                        quiz = {
                            "topic": topic,
                            "question": question,
                            "options": options,
                            "correct": correct,
                            "explanation": explanation or f"Đáp án đúng là {correct}",
                            "created_at": datetime.now().isoformat()
                        }
                        
                        if storage:
                            storage.add_quiz(quiz)
                        
                        logger.info(f"Generated new quiz: {question[:50]}...")
                        return quiz
                    else:
                        logger.warning(f"Invalid quiz format, retrying... (attempt {retry + 1})")
                        
            except Exception as e:
                logger.error(f"Error generating quiz (retry {retry}): {e}")
        
        if storage:
            pool = storage.get_quiz_pool()
            if pool:
                fallback_quiz = random.choice(pool)
                logger.info("Using fallback quiz from pool")
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
    """Cleanup game data"""
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
    
    # Clear user answers for this chat
    keys_to_remove = [key for key in user_answered.keys() if key[0] == chat_id]
    for key in keys_to_remove:
        del user_answered[key]

async def schedule_next_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, delay: int = 3):
    """Schedule next quiz với error handling"""
    try:
        await asyncio.sleep(delay)
        if chat_id in minigame_groups:
            logger.info(f"Creating new quiz for chat {chat_id}")
            await start_random_minigame(chat_id, context)
    except Exception as e:
        logger.error(f"Error scheduling next quiz for {chat_id}: {e}")

async def game_timeout_handler(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Improved timeout handler với error handling"""
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
        
        # Cleanup current game
        await cleanup_game(chat_id)
        
        # Schedule next quiz
        if chat_id in minigame_groups:
            asyncio.create_task(schedule_next_quiz(chat_id, context))
            
    except asyncio.CancelledError:
        logger.info(f"Timeout handler cancelled for chat {chat_id}")
    except Exception as e:
        logger.error(f"Error in timeout handler for {chat_id}: {e}")
        # Fallback: cleanup và tạo quiz mới
        await cleanup_game(chat_id)
        if chat_id in minigame_groups:
            asyncio.create_task(schedule_next_quiz(chat_id, context, 5))

async def start_random_minigame(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info(f"Starting minigame for chat {chat_id}")
        
        if chat_id not in minigame_groups:
            logger.info(f"Chat {chat_id} not in minigame groups")
            return
        
        # Cleanup any existing game
        await cleanup_game(chat_id)
        
        loading_msg = await context.bot.send_message(
            chat_id, 
            f"🎲 **MINIGAME**\n"
            f"🎮 📝 Quiz Trắc Nghiệm\n"
            f"⏰ Tự đổi câu mới sau 10 phút\n\n"
            f"⏳ Đang tải...",
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
            # Retry after 30 seconds
            asyncio.create_task(schedule_next_quiz(chat_id, context, 30))
            return
        
        game.current_quiz = quiz
        active_games[chat_id] = {"type": "quiz", "game": game, "minigame": True}
        game_start_times[chat_id] = datetime.now()
        
        keyboard = []
        for option in quiz["options"]:
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        quiz_msg = await context.bot.send_message(
            chat_id,
            f"❓ **{quiz['topic']}**\n\n"
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
        
        # Create timeout task
        game_timeouts[chat_id] = asyncio.create_task(game_timeout_handler(chat_id, context))
        logger.info(f"Quiz created successfully for chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Error in start_random_minigame for {chat_id}: {e}")
        await cleanup_game(chat_id)
        # Retry after 60 seconds
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
        
        message = f"""👋 Xin chào {username}! Mình là Linh Bot!

💰 Số dư của bạn: {_fmt_money(balance)}

🎮 **Minigame tự động trong nhóm**
Bot sẽ tự động tạo quiz liên tục!

📝 **Chơi riêng lẻ:**
/quiz - Quiz trắc nghiệm

📊 **Thông tin:**
/top - Bảng xếp hạng
/bal - Xem số dư
/stats - Thống kê cá nhân

🛠️ **Admin:**
/clean - Dọn dẹp bot (chỉ admin)
/stopminigame - Dừng minigame trong nhóm

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
        
        # Cleanup all games
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
                    msg += f"• Quiz trắc nghiệm: {count} lần\n"
        
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
        
        loading_msg = await update.message.reply_text("⏳ Đang tạo câu hỏi...")
        
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
        
        await loading_msg.edit_text(
            f"❓ **{quiz['topic']}**\n\n{quiz['question']}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in quiz: {e}")
        await update.message.reply_text("😅 Xin lỗi, có lỗi xảy ra!")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        data = query.data
        chat_id = update.effective_chat.id
        user = update.effective_user
        username = user.username or user.first_name
        
        user_key = (chat_id, user.id)
        if user_key in user_answered:
            await query.answer("⚠️ Bạn đã trả lời rồi!", show_alert=True)
            return
        
        if chat_id in active_games:
            game_info = active_games[chat_id]
            game = game_info["game"]
            
            user_answered[user_key] = True
            
            if data.startswith("quiz_") and game_info["type"] == "quiz":
                quiz = game.current_quiz
                answer = data.split("_")[1]
                
                if answer == quiz["correct"]:
                    points = 300
                    result = f"🎉 **{username}** trả lời chính xác! (+{points}đ)\n\n"
                    result += f"✅ Đáp án: **{quiz['correct']}**\n"
                    result += f"💡 {quiz.get('explanation', '')}"
                    
                    update_user_balance(user.id, username, points, "quiz")
                else:
                    result = f"❌ **{username}** - Chưa đúng!\n\n"
                    result += f"✅ Đáp án đúng: **{quiz['correct']}**\n"
                    result += f"💡 {quiz.get('explanation', '')}"
                
                msg = await context.bot.send_message(chat_id, result, parse_mode="Markdown")
                
                if game_info.get("minigame"):
                    await add_game_message(chat_id, msg.message_id, context)
                
                # Cleanup current game
                await cleanup_game(chat_id)
                
                # Schedule next quiz if in minigame group
                if chat_id in minigame_groups:
                    asyncio.create_task(schedule_next_quiz(chat_id, context))
                        
    except Exception as e:
        logger.error(f"Error in button callback: {e}")

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
                {"role": "system", "content": "Bạn là Linh - cô gái Việt Nam vui vẻ, thân thiện. Trả lời ngắn gọn."}
            ]
            messages.extend(list(chat_history[user_id]))
            
            response = await call_api(messages, max_tokens=200)
            
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
    """Health check để đảm bảo quiz luôn chạy"""
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
                    
                    # Check if game is stuck (running too long)
                    if chat_id in game_start_times:
                        game_duration = (current_time - game_start_times[chat_id]).total_seconds()
                        if game_duration > GAME_TIMEOUT + 60:  # 1 minute grace period
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
        
        for chat_id in minigame_groups:
            try:
                await start_random_minigame(chat_id, application)
                await asyncio.sleep(2)  # Tăng delay để tránh spam
            except Exception as e:
                logger.error(f"Error starting minigame for {chat_id}: {e}")

async def post_init(application: Application) -> None:
    asyncio.create_task(periodic_batch_save(application))
    asyncio.create_task(cleanup_memory(application))
    asyncio.create_task(quiz_health_check(application))  # Health check mới
    asyncio.create_task(load_minigame_groups(application))
    logger.info("Bot started successfully!")

async def post_shutdown(application: Application) -> None:
    # Cleanup all tasks
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
    
    logger.info("Linh Bot is running! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
