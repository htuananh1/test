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
        if not force and path in self._last_save:
            if datetime.now().timestamp() - self._last_save[path] < 300:
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
    
    def get_user_data(self, user_id: int) -> dict:
        data = self._get_file_content("data/scores.json") or {"users": {}}
        return data["users"].get(str(user_id), {
            "balance": START_BALANCE,
            "total_earned": 0,
            "games_played": {}
        })
    
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
        
        self._save_file("data/scores.json", data, f"Update: {username} ({amount:+d})")
    
    def get_leaderboard(self, limit: int = 10) -> List[tuple]:
        data = self._get_file_content("data/scores.json") or {"users": {}}
        users = [(u["username"], u.get("total_earned", 0)) for u in data["users"].values()]
        return sorted(users, key=lambda x: x[1], reverse=True)[:limit]
    
    def save_chat_info(self, chat_id: int, chat_type: str, title: str = None):
        data = self._get_file_content("data/chats.json") or {"chats": []}
        
        # Check if chat exists
        for i, chat in enumerate(data["chats"]):
            if chat[0] == chat_id:
                data["chats"][i] = (chat_id, chat_type, title)
                self._save_file("data/chats.json", data, f"Update chat: {chat_id}")
                return
        
        data["chats"].append((chat_id, chat_type, title))
        self._save_file("data/chats.json", data, f"Add chat: {chat_id}")
    
    def get_chat_list(self) -> List[tuple]:
        data = self._get_file_content("data/chats.json")
        return data.get("chats", []) if data else []

storage = GitHubStorage(GITHUB_TOKEN, GITHUB_REPO)

# Global variables
active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
minigame_sessions: Dict[int, dict] = {}
user_cache: Dict[int, dict] = {}
chat_settings: Dict[int, dict] = {}

def _fmt_money(x: int) -> str:
    return f"{x:,}".replace(",", ".")

def get_user_balance(user_id: int) -> int:
    if user_id not in user_cache:
        user_cache[user_id] = storage.get_user_data(user_id)
    return user_cache[user_id]["balance"]

def update_user_balance(user_id: int, username: str, amount: int, game_type: str = None):
    try:
        storage.update_user_balance(user_id, username, amount, game_type)
        if user_id in user_cache:
            user_cache[user_id]["balance"] += amount
            if amount > 0:
                user_cache[user_id]["total_earned"] = user_cache[user_id].get("total_earned", 0) + amount
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
    except:
        return None

# Minigame classes (giữ nguyên)
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

# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    storage.save_chat_info(chat.id, chat.type, chat.title)
    balance = get_user_balance(user.id)
    
    message = f"""👋 Xin chào {user.first_name}! Mình là Linh!

💰 Số dư: {_fmt_money(balance)}

🎮 /minigame - Chơi minigame
📊 /top - Bảng xếp hạng
💰 /bal - Xem số dư
📈 /stats - Thống kê

💬 Chat với mình bất cứ lúc nào!"""
    
    await update.message.reply_text(message)

async def bal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    await update.message.reply_text(f"💰 Số dư: {_fmt_money(balance)}")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = storage.get_user_data(user.id)
    
    msg = f"📊 **Thống kê {user.first_name}**\n\n"
    msg += f"💰 Số dư: {_fmt_money(data['balance'])}\n"
    msg += f"⭐ Tổng điểm: {_fmt_money(data.get('total_earned', 0))}\n"
    
    games = data.get('games_played', {})
    if games:
        msg += "\n🎮 Đã chơi:\n"
        for game, count in games.items():
            msg += f"• {game}: {count} lần\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def minigame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    if chat_id in minigame_sessions:
        await update.message.reply_text("⚠️ Đang có minigame! Dùng /stopmini để dừng.")
        return
    
    minigame_sessions[chat_id] = {
        "active": True,
        "total_score": 0,
        "games_played": 0,
        "start_time": datetime.now(),
        "starter_id": user.id,
        "starter_name": user.username or user.first_name
    }
    
    await start_random_minigame(chat_id, context)

async def start_random_minigame(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    if chat_id not in minigame_sessions or not minigame_sessions[chat_id]["active"]:
        return
    
    session = minigame_sessions[chat_id]
    session["games_played"] += 1
    
    # Chỉ chơi đoán số trong minigame
    game = GuessNumberGame(chat_id)
    active_games[chat_id] = {"type": "guessnumber", "game": game, "minigame": True}
    
    await context.bot.send_message(
        chat_id,
        f"""🎮 Minigame #{session['games_played']} | Tổng: {session['total_score']} điểm

🎯 ĐOÁN SỐ 1-999
💡 {game.riddle}
📝 15 lần thử | /hint để gợi ý"""
    )

async def stop_minigame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
🎮 Đã chơi: {session['games_played']} game
💰 Tổng điểm: {session['total_score']}"""
    
    await update.message.reply_text(msg)
    
    del minigame_sessions[chat_id]
    if chat_id in active_games:
        del active_games[chat_id]

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
        await update.message.reply_text("❌ Không trong game đoán số!")
        return
        
    game = active_games[chat_id]["game"]
    await update.message.reply_text(game.get_hint())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    # Xử lý game đoán số
    if chat_id in active_games and active_games[chat_id]["type"] == "guessnumber":
        try:
            guess = int(message)
            if 1 <= guess <= 999:
                game_info = active_games[chat_id]
                game = game_info["game"]
                is_finished, response = game.make_guess(guess)
                await update.message.reply_text(response)
                
                if is_finished:
                    if "Đúng" in response:
                        if game_info.get("minigame") and chat_id in minigame_sessions:
                            minigame_sessions[chat_id]["total_score"] += game.score
                        else:
                            update_user_balance(user.id, username, game.score, "guessnumber")
                    
                    del active_games[chat_id]
                    
                    if game_info.get("minigame") and chat_id in minigame_sessions:
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

async def post_init(application: Application) -> None:
    logger.info("Bot started!")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = post_init
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("minigame", minigame_cmd))
    application.add_handler(CommandHandler("stopmini", stop_minigame_cmd))
    application.add_handler(CommandHandler("hint", hint_command))
    application.add_handler(CommandHandler("bal", bal_cmd))
    application.add_handler(CommandHandler("top", top_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    
    # Messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot is running! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
