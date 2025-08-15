import os
import random
import asyncio
import logging
import requests
import json
import sqlite3
import gc
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "alibaba/qwen-3-32b")
QUIZ_MODEL = "openai/gpt-4o-mini"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "3"))

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
    c.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT,
            title TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
quiz_sessions: Dict[int, dict] = {}
quiz_mode: Dict[int, bool] = {}
quiz_count: Dict[int, int] = {}
quiz_history: Dict[int, List[str]] = {}
word_game_sessions: Dict[int, dict] = {}
goodnight_task = None

def save_chat_info(chat_id: int, chat_type: str, title: str = None):
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO chats (chat_id, chat_type, title) VALUES (?, ?, ?)',
              (chat_id, chat_type, title))
    conn.commit()
    conn.close()

def get_all_chats():
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('SELECT chat_id, chat_type FROM chats')
    results = c.fetchall()
    conn.close()
    return results

def cleanup_memory():
    global chat_history, quiz_history
    for chat_id in list(chat_history.keys()):
        if len(chat_history[chat_id]) > 4:
            chat_history[chat_id] = chat_history[chat_id][-4:]
    
    for chat_id in list(quiz_history.keys()):
        if len(quiz_history[chat_id]) > 20:
            quiz_history[chat_id] = quiz_history[chat_id][-20:]
    
    gc.collect()

def save_score(user_id: int, username: str, game_type: str, score: int):
    try:
        conn = sqlite3.connect('bot_scores.db')
        c = conn.cursor()
        c.execute('INSERT INTO scores (user_id, username, game_type, score) VALUES (?, ?, ?, ?)',
                  (user_id, username, game_type, score))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Save score error: {e}")

def get_leaderboard_24h(limit: int = 10) -> List[tuple]:
    try:
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
    except Exception as e:
        logger.error(f"Get leaderboard error: {e}")
        return []

def get_user_stats_24h(user_id: int) -> dict:
    try:
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
        
        stats = {'total': 0, 'games': {}}
        
        for game_type, games_played, total_score, best_score in results:
            stats['games'][game_type] = {
                'played': games_played,
                'total': total_score,
                'best': best_score
            }
            stats['total'] += total_score
            
        conn.close()
        return stats
    except Exception as e:
        logger.error(f"Get stats error: {e}")
        return {'total': 0, 'games': {}}

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

class VuaTiengVietGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.current_word = ""
        self.scrambled = ""
        self.attempts = 0
        self.max_attempts = 3
        self.score = 0
        self.start_time = datetime.now()
        self.round_count = 0
        
    async def start_new_round(self) -> str:
        self.round_count += 1
        self.attempts = 0
        
        await asyncio.sleep(5)
        
        self.current_word, self.scrambled = await self.generate_word_puzzle()
        
        return f"""🎮 **VUA TIẾNG VIỆT - CÂU {self.round_count}**

Sắp xếp các chữ cái sau thành từ có nghĩa:

🔤 **{self.scrambled}**

💡 Gợi ý: {len(self.current_word.replace(' ', ''))} chữ cái
📝 Bạn có {self.max_attempts} lần thử

Gõ đáp án của bạn!"""

    async def generate_word_puzzle(self) -> Tuple[str, str]:
        random_number = random.randint(1, 1000)
        category = random.choice(["động vật", "thực vật", "đồ vật", "cảm xúc", "hành động", "màu sắc", "thời tiết", "gia đình"])
        
        prompt = f"""Create a Vietnamese word puzzle. Category: {category}, variation: {random_number}.

Requirements:
- Generate ONE common Vietnamese word (2-8 letters)
- Must be different each time
- Output MUST be in Vietnamese

Return EXACTLY in this format (in Vietnamese):
Từ gốc: [vietnamese word]
Xáo trộn: [scrambled letters separated by /]

Example output:
Từ gốc: hạnh phúc
Xáo trộn: h / ạ / p / h / n / ú / c"""

        messages = [
            {"role": "system", "content": "You create Vietnamese word puzzles. Always respond in Vietnamese language only."},
            {"role": "user", "content": prompt}
        ]
        
        response = await call_api(messages, model=QUIZ_MODEL, max_tokens=100)
        
        if response:
            lines = response.strip().split('\n')
            word = ""
            scrambled = ""
            
            for line in lines:
                if line.startswith("Từ gốc:"):
                    word = line.replace("Từ gốc:", "").strip()
                elif line.startswith("Xáo trộn:"):
                    scrambled = line.replace("Xáo trộn:", "").strip()
            
            if word and scrambled:
                return word, scrambled
        
        fallback_words = [
            ("yêu", "ê / y / u"),
            ("mưa", "ư / m / a"),
            ("nắng", "ắ / n / g / n"),
            ("hoa", "o / h / a"),
            ("cây", "â / c / y"),
            ("biển", "ể / b / i / n"),
            ("sông", "ô / s / n / g"),
            ("núi", "ú / n / i"),
            ("trời", "ờ / t / r / i"),
            ("đất", "ấ / đ / t"),
            ("mây", "â / m / y"),
            ("gió", "ó / g / i"),
            ("sao", "a / s / o"),
            ("trăng", "ă / t / r / n / g"),
            ("vàng", "à / v / n / g")
        ]
        return random.choice(fallback_words)
        
    def check_answer(self, answer: str) -> Tuple[bool, str]:
        answer = answer.lower().strip()
        self.attempts += 1
        
        if answer == self.current_word:
            points = (self.max_attempts - self.attempts + 1) * 100
            self.score += points
            time_taken = (datetime.now() - self.start_time).seconds
            
            return True, f"""✅ **CHÍNH XÁC!**

Đáp án: **{self.current_word}**
Điểm: +{points} (Tổng: {self.score})
Thời gian: {time_taken}s

Gõ 'tiếp' để chơi tiếp hoặc 'dừng' để kết thúc"""
            
        if self.attempts >= self.max_attempts:
            return False, f"""❌ Hết lượt!

Đáp án là: **{self.current_word}**

Gõ 'tiếp' để chơi câu mới hoặc 'dừng' để kết thúc"""
            
        remaining = self.max_attempts - self.attempts
        return False, f"❌ Sai rồi! Còn {remaining} lần thử\n\n🔤 {self.scrambled}"

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
            "temperature": 0.8,
            "top_p": 0.95
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

async def generate_quiz(chat_id: int) -> dict:
    global quiz_history
    
    if chat_id not in quiz_history:
        quiz_history[chat_id] = []
    
    topics = ["lịch sử", "địa lý", "ẩm thực", "văn hóa", "du lịch", "nghệ thuật", "thể thao", "kinh tế", "khoa học", "văn học"]
    topic = random.choice(topics)
    
    random_seed = random.randint(1, 10000)
    difficulty = random.choice(["dễ", "trung bình", "khó"])
    
    prompt = f"""Create a quiz about Vietnamese {topic}. Seed: {random_seed}, difficulty: {difficulty}.

Requirements:
1. Question must be unique and specific about Vietnam
2. 4 answer options, only 1 correct
3. All content MUST be in Vietnamese language
4. Include interesting explanation

Format EXACTLY (all in Vietnamese):
Câu hỏi: [question in Vietnamese about {topic}]
A. [option A in Vietnamese]
B. [option B in Vietnamese]
C. [option C in Vietnamese]
D. [option D in Vietnamese]
Đáp án: [A/B/C/D]
Giải thích: [explanation in Vietnamese]

Remember: EVERYTHING must be in Vietnamese!"""

    messages = [
        {
            "role": "system", 
            "content": f"You are a Vietnamese culture expert. Create quiz questions about {topic} in Vietnamese language only. Never use English in the output."
        },
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = await call_api(messages, model=QUIZ_MODEL, max_tokens=400)
        
        if not response:
            return None
            
        lines = response.strip().split('\n')
        
        quiz = {"question": "", "options": [], "correct": "", "explanation": "", "topic": topic}
        
        for line in lines:
            line = line.strip()
            if line.startswith("Câu hỏi:"):
                quiz["question"] = line.replace("Câu hỏi:", "").strip()
            elif line.startswith("A."):
                quiz["options"].append(line)
            elif line.startswith("B."):
                quiz["options"].append(line)
            elif line.startswith("C."):
                quiz["options"].append(line)
            elif line.startswith("D."):
                quiz["options"].append(line)
            elif line.startswith("Đáp án:"):
                answer = line.replace("Đáp án:", "").strip()
                if answer and answer[0] in "ABCD":
                    quiz["correct"] = answer[0]
            elif line.startswith("Giải thích:"):
                quiz["explanation"] = line.replace("Giải thích:", "").strip()
        
        if quiz["question"] and len(quiz["options"]) == 4 and quiz["correct"]:
            quiz_history[chat_id].append(quiz["question"][:60])
            return quiz
        
        return None
            
    except Exception as e:
        logger.error(f"Generate quiz error: {e}")
        return None

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
    
    for chat_id, chat_type in chats:
        try:
            await app.bot.send_message(chat_id=chat_id, text=message)
            logger.info(f"Sent goodnight to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send to {chat_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    save_chat_info(chat.id, chat.type, chat.title)
    
    await update.message.reply_text("""
👋 **Xin chào! Mình là Linh!**

🎮 **Game:**
/guessnumber - Đoán số
/vuatiengviet - Sắp xếp chữ cái
/quiz - Câu đố về Việt Nam
/stopquiz - Dừng câu đố

🏆 /leaderboard - BXH 24h
📊 /stats - Điểm của bạn

💕 Mỗi 23h Linh sẽ chúc ngủ ngon!
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

async def start_vua_tieng_viet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
    
    game = VuaTiengVietGame(chat_id)
    active_games[chat_id] = {"type": "vuatiengviet", "game": game}
    
    loading_msg = await update.message.reply_text("⏳ GPT-4o mini đang tạo câu đố...")
    
    message = await game.start_new_round()
    await loading_msg.edit_text(message)

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    quiz_mode[chat_id] = True
    quiz_count[chat_id] = 1
    
    loading_msg = await update.message.reply_text("⏳ Đang tạo câu hỏi với GPT-4o mini...")
    
    quiz = await generate_quiz(chat_id)
    
    if not quiz:
        await loading_msg.edit_text("❌ Lỗi tạo câu hỏi! Thử lại /quiz")
        if chat_id in quiz_mode:
            del quiz_mode[chat_id]
        return
    
    quiz_sessions[chat_id] = quiz
    
    keyboard = []
    for option in quiz["options"]:
        keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
    keyboard.append([InlineKeyboardButton("❌ Dừng", callback_data="quiz_stop")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    topic_emojis = {
        "lịch sử": "📜",
        "địa lý": "🗺️",
        "ẩm thực": "🍜",
        "văn hóa": "🎭",
        "du lịch": "✈️",
        "nghệ thuật": "🎨",
        "thể thao": "⚽",
        "kinh tế": "💰",
        "khoa học": "🔬",
        "văn học": "📚"
    }
    
    emoji = topic_emojis.get(quiz.get("topic", ""), "❓")
    message = f"{emoji} **CÂU {quiz_count[chat_id]} - {quiz.get('topic', '').upper()}**\n\n{quiz['question']}"
    
    await loading_msg.edit_text(message, reply_markup=reply_markup)

async def stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    total_questions = quiz_count.get(chat_id, 0) - 1
    
    if chat_id in quiz_mode:
        del quiz_mode[chat_id]
    if chat_id in quiz_sessions:
        del quiz_sessions[chat_id]
    if chat_id in quiz_count:
        del quiz_count[chat_id]
    if chat_id in quiz_history:
        quiz_history[chat_id] = []
        
    await update.message.reply_text(f"✅ Đã dừng câu đố!\n📊 Bạn đã trả lời {total_questions} câu")

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
            game_name = {
                "guessnumber": "Đoán số",
                "vuatiengviet": "Vua Tiếng Việt",
                "quiz": "Câu đố"
            }.get(game_type, game_type)
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
            total_questions = quiz_count.get(chat_id, 1) - 1
            
            if chat_id in quiz_mode:
                del quiz_mode[chat_id]
            if chat_id in quiz_sessions:
                del quiz_sessions[chat_id]
            if chat_id in quiz_count:
                del quiz_count[chat_id]
            if chat_id in quiz_history:
                quiz_history[chat_id] = []
                
            await query.message.edit_text(f"✅ Đã dừng câu đố!\n📊 Bạn đã trả lời {total_questions} câu")
            return
            
        if chat_id not in quiz_sessions:
            await query.message.edit_text("❌ Hết giờ!")
            return
            
        quiz = quiz_sessions[chat_id]
        answer = data.split("_")[1]
        
        if answer == quiz["correct"]:
            save_score(user.id, username, "quiz", 200)
            result = f"✅ Chính xác! (+200đ)\n\n{quiz['explanation']}"
        else:
            result = f"❌ Sai rồi! Đáp án: {quiz['correct']}\n\n{quiz['explanation']}"
        
        del quiz_sessions[chat_id]
        
        await query.message.edit_text(result)
        
        if chat_id in quiz_mode:
            wait_msg = await context.bot.send_message(
                chat_id, 
                "⏳ **Đợi 5 giây cho câu tiếp theo...**"
            )
            
            await asyncio.sleep(5)
            await wait_msg.delete()
            
            quiz_count[chat_id] = quiz_count.get(chat_id, 1) + 1
            
            loading_msg = await context.bot.send_message(chat_id, "⏳ GPT-4o mini đang tạo câu hỏi mới...")
            
            quiz = await generate_quiz(chat_id)
            
            if not quiz:
                await loading_msg.edit_text("❌ Lỗi tạo câu hỏi! Dùng /quiz để thử lại")
                if chat_id in quiz_mode:
                    del quiz_mode[chat_id]
                return
            
            quiz_sessions[chat_id] = quiz
            
            keyboard = []
            for option in quiz["options"]:
                keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
            keyboard.append([InlineKeyboardButton("❌ Dừng", callback_data="quiz_stop")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            topic_emojis = {
                "lịch sử": "📜",
                "địa lý": "🗺️",
                "ẩm thực": "🍜",
                "văn hóa": "🎭",
                "du lịch": "✈️",
                "nghệ thuật": "🎨",
                "thể thao": "⚽",
                "kinh tế": "💰",
                "khoa học": "🔬",
                "văn học": "📚"
            }
            
            emoji = topic_emojis.get(quiz.get("topic", ""), "❓")
            message = f"{emoji} **CÂU {quiz_count[chat_id]} - {quiz.get('topic', '').upper()}**\n\n{quiz['question']}"
            
            await loading_msg.edit_text(message, reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    chat = update.effective_chat
    save_chat_info(chat.id, chat.type, chat.title)
    
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
                
        elif game_info["type"] == "vuatiengviet":
            game = game_info["game"]
            
            if message.lower() in ["tiếp", "tiep"]:
                loading_msg = await update.message.reply_text("⏳ GPT-4o mini đang tạo câu mới...")
                msg = await game.start_new_round()
                await loading_msg.edit_text(msg)
            elif message.lower() in ["dừng", "dung", "stop"]:
                if game.score > 0:
                    save_score(user.id, username, "vuatiengviet", game.score)
                await update.message.reply_text(f"📊 Kết thúc!\nTổng điểm: {game.score}")
                del active_games[chat_id]
            else:
                is_correct, response = game.check_answer(message)
                await update.message.reply_text(response)
                
                if is_correct and "dừng" not in response.lower():
                    loading_msg = await context.bot.send_message(chat_id, "⏳ GPT-4o mini đang tạo câu mới...")
                    await asyncio.sleep(2)
                    msg = await game.start_new_round()
                    await loading_msg.edit_text(msg)
        return
    
    if chat_id not in chat_history:
        chat_history[chat_id] = []
        
    chat_history[chat_id].append({"role": "user", "content": message})
    
    if len(chat_history[chat_id]) > 4:
        chat_history[chat_id] = chat_history[chat_id][-4:]
    
    messages = [
        {"role": "system", "content": "Bạn là Linh - cô gái Việt Nam vui vẻ, thân thiện. Trả lời ngắn gọn."}
    ]
    messages.extend(chat_history[chat_id])
    
    response = await call_api(messages, max_tokens=300)
    
    if response:
        chat_history[chat_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("😅 Xin lỗi, mình đang gặp lỗi!")

async def post_init(application: Application) -> None:
    global goodnight_task
    goodnight_task = asyncio.create_task(goodnight_scheduler(application))
    logger.info("Goodnight scheduler started!")

async def post_shutdown(application: Application) -> None:
    global goodnight_task
    if goodnight_task:
        goodnight_task.cancel()
        try:
            await goodnight_task
        except asyncio.CancelledError:
            pass

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("guessnumber", start_guess_number))
    application.add_handler(CommandHandler("vuatiengviet", start_vua_tieng_viet))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("stopquiz", stop_quiz))
    application.add_handler(CommandHandler("hint", hint_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot started! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
