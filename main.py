import os
import random
import asyncio
import logging
import requests
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "anthropic/claude-3-haiku")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "5"))  # Giảm để tiết kiệm memory

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER,
            username TEXT,
            game_type TEXT,
            score INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Giảm memory usage
active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
quiz_sessions: Dict[int, dict] = {}
quiz_mode: Dict[int, bool] = {}  # Track quiz mode

# Tối ưu từ điển - chỉ load khi cần
def check_vietnamese_word(word: str) -> bool:
    try:
        response = requests.get(
            "https://raw.githubusercontent.com/undertheseanlp/dictionary/refs/heads/hongocduc/data/Viet74K.txt",
            timeout=5
        )
        if response.status_code == 200:
            words = response.text.lower().strip().split('\n')
            return word.lower() in words
        return False
    except:
        return False

def save_score(user_id: int, username: str, game_type: str, score: int):
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('INSERT INTO scores (user_id, username, game_type, score) VALUES (?, ?, ?, ?)',
              (user_id, username, game_type, score))
    conn.commit()
    conn.close()

def get_leaderboard_24h(limit: int = 10) -> List[tuple]:
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    yesterday = datetime.now() - timedelta(days=1)
    c.execute('''
        SELECT username, SUM(score) as total_score, COUNT(DISTINCT game_type) as games_played
        FROM scores
        WHERE timestamp >= ?
        GROUP BY user_id
        ORDER BY total_score DESC
        LIMIT ?
    ''', (yesterday, limit))
    results = c.fetchall()
    conn.close()
    return results

def get_user_stats_24h(user_id: int) -> dict:
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    yesterday = datetime.now() - timedelta(days=1)
    
    c.execute('''
        SELECT game_type, COUNT(*) as games_played, SUM(score) as total_score, MAX(score) as best_score
        FROM scores
        WHERE user_id = ? AND timestamp >= ?
        GROUP BY game_type
    ''', (user_id, yesterday))
    results = c.fetchall()
    
    stats = {
        'total': 0,
        'games': {}
    }
    
    for game_type, games_played, total_score, best_score in results:
        stats['games'][game_type] = {
            'played': games_played,
            'total': total_score,
            'best': best_score
        }
        stats['total'] += total_score
        
    conn.close()
    return stats

class GuessNumberGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.attempts = 0
        self.max_attempts = 10
        self.hints_used = 0
        self.max_hints = 3
        self.start_time = datetime.now()
        self.score = 1000
        self.secret_number = random.randint(1, 100)
        self.riddle = self.generate_riddle()
            
    def generate_riddle(self) -> str:
        riddles = []
        
        if self.secret_number % 2 == 0:
            riddles.append("số chẵn")
        else:
            riddles.append("số lẻ")
            
        if self.secret_number < 50:
            riddles.append("nhỏ hơn 50")
        else:
            riddles.append("lớn hơn hoặc bằng 50")
            
        return f"Số bí mật là {' và '.join(riddles)}"
        
    def get_hint(self) -> str:
        if self.hints_used >= self.max_hints:
            return "❌ Hết gợi ý rồi!"
            
        self.hints_used += 1
        self.score -= 100
        
        if self.hints_used == 1:
            tens = self.secret_number // 10
            hint = f"💡 Gợi ý 1: {'Số có 1 chữ số' if tens == 0 else f'Chữ số hàng chục là {tens}'}"
        elif self.hints_used == 2:
            digit_sum = sum(int(d) for d in str(self.secret_number))
            hint = f"💡 Gợi ý 2: Tổng các chữ số là {digit_sum}"
        else:
            lower = (self.secret_number // 10) * 10
            upper = lower + 9 if lower > 0 else 9
            hint = f"💡 Gợi ý 3: Số từ {max(1, lower)} đến {upper}"
                
        return f"{hint}\n🎯 Còn {self.max_hints - self.hints_used} gợi ý"
        
    def make_guess(self, guess: int) -> Tuple[bool, str]:
        self.attempts += 1
        self.score -= 50
        
        if guess == self.secret_number:
            time_taken = (datetime.now() - self.start_time).seconds
            final_score = max(self.score, 100)
            return True, f"🎉 Đúng rồi! Số {self.secret_number}!\n⏱️ {time_taken}s | 🏆 {final_score} điểm"
            
        if self.attempts >= self.max_attempts:
            return True, f"😤 Hết lượt! Số là {self.secret_number}\n💡 {self.riddle}"
            
        hint = "📈 cao hơn" if guess < self.secret_number else "📉 thấp hơn"
        remaining = self.max_attempts - self.attempts
        return False, f"{guess} {hint}! Còn {remaining} lượt | 💰 {self.score}đ | /hint"

class NoiTuGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.history = []
        self.score = 0
        self.current_word = ""
        self.start_time = datetime.now()
        self.player_words = 0
        self.bot_words = 0
        
    def start(self) -> str:
        start_words = ["trong sạch", "sạch sẽ", "đẹp đẽ", "vui vẻ", "mạnh mẽ"]
        self.current_word = random.choice(start_words)
        self.history = [self.current_word]
        last_word = self.current_word.split()[1]
        
        return f"""🎮 **Nối Từ với Linh!**

Luật: Nối từ ghép 2 từ tiếng Việt
VD: trong sạch → sạch sẽ

🎯 **{self.current_word}**
Nối với '{last_word}' | Gõ 'thua' kết thúc"""
        
    def check_compound(self, word: str) -> bool:
        parts = word.split()
        if len(parts) != 2:
            return False
        # Simplified check for memory optimization
        return len(parts[0]) > 1 and len(parts[1]) > 1
        
    def play_word(self, word: str) -> Tuple[bool, str]:
        word = word.lower().strip()
        
        if word == "thua":
            return True, f"📊 Điểm: {self.score} | {len(self.history)} từ"
        
        parts = word.split()
        if len(parts) != 2:
            return False, "❌ Phải 2 từ ghép!"
        
        last_word = self.current_word.split()[1]
        if parts[0] != last_word:
            return False, f"❌ Phải bắt đầu '{last_word}'"
            
        if word in self.history:
            return False, "❌ Từ đã dùng!"
        
        if not self.check_compound(word):
            return False, "❌ Từ không hợp lệ!"
            
        self.history.append(word)
        self.current_word = word
        self.player_words += 1
        self.score += 100
        
        # Bot turn - simplified
        bot_options = ["sẽ sàng", "đẹp đẽ", "vui vẻ", "tốt đẹp", "mạnh mẽ"]
        bot_word = None
        for option in bot_options:
            if option.split()[0] == parts[1] and option not in self.history:
                bot_word = option
                break
                
        if bot_word:
            self.history.append(bot_word)
            self.current_word = bot_word
            self.bot_words += 1
            return False, f"✅ +100đ\n🤖 Linh: **{bot_word}**\n📊 {self.score}đ | Nối '{bot_word.split()[1]}'"
        else:
            self.score += 500
            return True, f"🏆 Thắng! +500đ\n📊 Tổng: {self.score} điểm"

async def call_vercel_api(messages: List[dict], max_tokens: int = 700) -> str:
    try:
        headers = {
            "Authorization": f"Bearer {VERCEL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": CHAT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.8
        }
        
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            return "Lỗi rồi! Thử lại nhé!"
            
    except Exception as e:
        return "Lỗi kết nối!"

async def generate_quiz() -> dict:
    prompt = """Tạo 1 câu đố về Việt Nam:

Câu hỏi: [câu hỏi]
A. [đáp án A]
B. [đáp án B]
C. [đáp án C]
D. [đáp án D]
Đáp án: [A/B/C/D]
Giải thích: [1 câu ngắn]"""

    messages = [
        {"role": "system", "content": "Tạo câu đố về Việt Nam. Mỗi đáp án viết 1 lần."},
        {"role": "user", "content": prompt}
    ]
    
    response = await call_vercel_api(messages, max_tokens=300)
    
    lines = response.strip().split('\n')
    quiz = {"question": "", "options": [], "correct": "", "explanation": ""}
    
    for line in lines:
        line = line.strip()
        if line.startswith("Câu hỏi:"):
            quiz["question"] = line[8:].strip()
        elif line[:2] in ["A.", "B.", "C.", "D."] and len(quiz["options"]) < 4:
            quiz["options"].append(line)
        elif line.startswith("Đáp án:"):
            ans = line[7:].strip()
            if ans and ans[0] in "ABCD":
                quiz["correct"] = ans[0]
        elif line.startswith("Giải thích:"):
            quiz["explanation"] = line[11:].strip()
            
    return quiz

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
👋 **Xin chào! Mình là Linh!**

🎮 **Game:**
/guessnumber - Đoán số
/noitu - Nối từ  
/quiz - Câu đố (liên tục)
/stopquiz - Dừng câu đố

🏆 /leaderboard - BXH 24h
📊 /stats - Điểm của bạn
""")

async def start_guess_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
        
    game = GuessNumberGame(chat_id)
    active_games[chat_id] = {"type": "guessnumber", "game": game}
    
    await update.message.reply_text(f"""🎮 **ĐOÁN SỐ 1-100**

💡 {game.riddle}
📝 10 lần | 💰 1000đ
/hint - Gợi ý (-100đ)

Đoán đi!""")

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
        await update.message.reply_text("❌ Không trong game đoán số!")
        return
        
    game = active_games[chat_id]["game"]
    await update.message.reply_text(game.get_hint())

async def start_noitu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
        
    game = NoiTuGame(chat_id)
    active_games[chat_id] = {"type": "noitu", "game": game}
    
    await update.message.reply_text(game.start())

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    quiz_mode[chat_id] = True  # Bật chế độ quiz liên tục
    
    await send_quiz(chat_id, update)

async def stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in quiz_mode:
        del quiz_mode[chat_id]
    if chat_id in quiz_sessions:
        del quiz_sessions[chat_id]
    await update.message.reply_text("✅ Đã dừng câu đố!")

async def send_quiz(chat_id: int, update_or_query):
    quiz = await generate_quiz()
    
    if quiz["question"] and len(quiz["options"]) == 4:
        quiz_sessions[chat_id] = quiz
        
        keyboard = []
        for option in quiz["options"]:
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
        keyboard.append([InlineKeyboardButton("⏭️ Câu khác", callback_data="quiz_next")])
        keyboard.append([InlineKeyboardButton("❌ Dừng", callback_data="quiz_stop")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = f"❓ **CÂU ĐỐ**\n\n{quiz['question']}"
        
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(message, reply_markup=reply_markup)
        else:
            await update_or_query.edit_text(message, reply_markup=reply_markup)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_leaderboard_24h()
    
    message = "🏆 **BXH 24H**\n\n"
    
    if scores:
        for i, (username, total_score, games_played) in enumerate(scores, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            message += f"{medal} {username}: {total_score:,}đ\n"
    else:
        message += "Chưa có ai chơi!"
        
    await update.message.reply_text(message)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats = get_user_stats_24h(user.id)
    
    message = f"📊 **{user.first_name} (24H)**\n\n"
    message += f"💰 Tổng: {stats['total']:,}đ\n"
    
    if stats['games']:
        message += "\n"
        for game_type, data in stats['games'].items():
            game_name = {"guessnumber": "Đoán số", "noitu": "Nối từ", "quiz": "Câu đố"}.get(game_type, game_type)
            message += f"{game_name}: {data['total']:,}đ ({data['played']} lần)\n"
            
    await update.message.reply_text(message)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    if data.startswith("quiz_"):
        if data == "quiz_stop":
            if chat_id in quiz_mode:
                del quiz_mode[chat_id]
            if chat_id in quiz_sessions:
                del quiz_sessions[chat_id]
            await query.message.edit_text("✅ Đã dừng câu đố!")
            return
            
        if data == "quiz_next":
            await send_quiz(chat_id, query.message)
            return
            
        if chat_id not in quiz_sessions:
            await query.message.edit_text("❌ Hết giờ!")
            return
            
        quiz = quiz_sessions[chat_id]
        answer = data.split("_")[1]
        
        if answer == quiz["correct"]:
            save_score(user.id, username, "quiz", 200)
            result = f"✅ Đúng! (+200đ)\n{quiz['explanation']}"
        else:
            result = f"❌ Sai! Đáp án: {quiz['correct']}\n{quiz['explanation']}"
        
        del quiz_sessions[chat_id]
        
        # Nếu đang ở chế độ quiz liên tục
        if chat_id in quiz_mode:
            keyboard = [[InlineKeyboardButton("➡️ Câu tiếp", callback_data="quiz_continue")],
                       [InlineKeyboardButton("❌ Dừng", callback_data="quiz_stop")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(result, reply_markup=reply_markup)
        else:
            await query.message.edit_text(result)
            
    elif data == "quiz_continue":
        await send_quiz(chat_id, query.message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    # Xử lý game đang chơi
    if chat_id in active_games:
        game_info = active_games[chat_id]
        
        if game_info["type"] == "guessnumber":
            try:
                guess = int(message)
                if 1 <= guess <= 100:
                    is_finished, response = game_info["game"].make_guess(guess)
                    await update.message.reply_text(response)
                    
                    if is_finished and "Đúng" in response:
                        save_score(user.id, username, "guessnumber", game_info["game"].score)
                        
                    if is_finished:
                        del active_games[chat_id]
                else:
                    await update.message.reply_text("❌ Từ 1-100 thôi!")
            except ValueError:
                await update.message.reply_text("❌ Nhập số!")
                
        elif game_info["type"] == "noitu":
            is_finished, response = game_info["game"].play_word(message)
            await update.message.reply_text(response)
            
            if is_finished:
                if game_info["game"].score > 0:
                    save_score(user.id, username, "noitu", game_info["game"].score)
                del active_games[chat_id]
                
        return
    
    # Chat AI - giảm context để tiết kiệm memory
    if chat_id not in chat_history:
        chat_history[chat_id] = []
        
    chat_history[chat_id].append({"role": "user", "content": message})
    
    # Giữ ít tin nhắn hơn
    if len(chat_history[chat_id]) > 6:
        chat_history[chat_id] = chat_history[chat_id][-6:]
    
    messages = [
        {"role": "system", "content": "Bạn là Linh - cô gái vui tính. Trả lời ngắn gọn, dùng emoji."}
    ]
    messages.extend(chat_history[chat_id])
    
    response = await call_vercel_api(messages, 400)  # Giảm token
    
    chat_history[chat_id].append({"role": "assistant", "content": response})
    
    await update.message.reply_text(response)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("guessnumber", start_guess_number))
    application.add_handler(CommandHandler("noitu", start_noitu))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("stopquiz", stop_quiz))
    application.add_handler(CommandHandler("hint", hint_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Callbacks & Messages
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot started! 🎮")
    application.run_polling()

if __name__ == "__main__":
    main()
