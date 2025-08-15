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
PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "15"))
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")

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

active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
vietnamese_words: set = set()
quiz_sessions: Dict[int, dict] = {}

def load_vietnamese_dictionary():
    global vietnamese_words
    try:
        response = requests.get("https://raw.githubusercontent.com/undertheseanlp/dictionary/refs/heads/hongocduc/data/Viet74K.txt")
        if response.status_code == 200:
            words = response.text.strip().split('\n')
            vietnamese_words = {word.lower().strip() for word in words if word.strip() and len(word.strip()) > 1}
            logger.info(f"Loaded {len(vietnamese_words)} Vietnamese words")
        else:
            logger.error("Failed to load Vietnamese dictionary")
    except Exception as e:
        logger.error(f"Error loading dictionary: {e}")

load_vietnamese_dictionary()

def save_score(user_id: int, username: str, game_type: str, score: int):
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('INSERT INTO scores (user_id, username, game_type, score) VALUES (?, ?, ?, ?)',
              (user_id, username, game_type, score))
    conn.commit()
    conn.close()

def get_total_scores(limit: int = 10) -> List[tuple]:
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('''
        SELECT username, SUM(score) as total_score
        FROM scores
        GROUP BY user_id
        ORDER BY total_score DESC
        LIMIT ?
    ''', (limit,))
    results = c.fetchall()
    conn.close()
    return results

def get_user_stats(user_id: int) -> dict:
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('''
        SELECT game_type, COUNT(*) as games_played, SUM(score) as total_score, MAX(score) as best_score
        FROM scores
        WHERE user_id = ?
        GROUP BY game_type
    ''', (user_id,))
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
    def __init__(self, chat_id: int, use_ai: bool = False):
        self.chat_id = chat_id
        self.attempts = 0
        self.max_attempts = 10
        self.hints_used = 0
        self.max_hints = 3
        self.start_time = datetime.now()
        self.use_ai = use_ai
        self.score = 1000
        
        if use_ai:
            self.secret_number, self.riddle = self.generate_ai_number()
        else:
            self.secret_number = random.randint(1, 100)
            self.riddle = self.generate_riddle()
            
    def generate_ai_number(self) -> Tuple[int, str]:
        number = random.randint(1, 100)
        riddle = self.generate_riddle_for_number(number)
        return number, riddle
        
    def generate_riddle(self) -> str:
        if self.secret_number % 2 == 0:
            riddle = "Số bí mật là số chẵn"
        else:
            riddle = "Số bí mật là số lẻ"
            
        if self.secret_number < 50:
            riddle += " và nhỏ hơn 50"
        else:
            riddle += " và lớn hơn hoặc bằng 50"
            
        return riddle
        
    def generate_riddle_for_number(self, number: int) -> str:
        riddles = []
        
        if number % 2 == 0:
            riddles.append("là số chẵn")
        else:
            riddles.append("là số lẻ")
            
        if number <= 25:
            riddles.append("nằm trong khoảng 1-25")
        elif number <= 50:
            riddles.append("nằm trong khoảng 26-50")
        elif number <= 75:
            riddles.append("nằm trong khoảng 51-75")
        else:
            riddles.append("nằm trong khoảng 76-100")
            
        if number % 5 == 0:
            riddles.append("chia hết cho 5")
        if number % 10 == 0:
            riddles.append("chia hết cho 10")
        if self.is_prime(number):
            riddles.append("là số nguyên tố")
            
        return f"Số bí mật {' và '.join(riddles[:2])}"
        
    def is_prime(self, n: int) -> bool:
        if n < 2:
            return False
        for i in range(2, int(n**0.5) + 1):
            if n % i == 0:
                return False
        return True
        
    def get_hint(self) -> str:
        if self.hints_used >= self.max_hints:
            return "❌ Bạn đã dùng hết số lần gợi ý!"
            
        self.hints_used += 1
        self.score -= 100
        
        hints = []
        
        if self.hints_used == 1:
            tens = self.secret_number // 10
            if tens == 0:
                hints.append("💡 Gợi ý 1: Số bí mật có 1 chữ số")
            else:
                hints.append(f"💡 Gợi ý 1: Chữ số hàng chục là {tens}")
                
        elif self.hints_used == 2:
            digit_sum = sum(int(d) for d in str(self.secret_number))
            hints.append(f"💡 Gợi ý 2: Tổng các chữ số là {digit_sum}")
            
        elif self.hints_used == 3:
            lower = (self.secret_number // 10) * 10
            upper = lower + 9
            if lower == 0:
                hints.append(f"💡 Gợi ý 3: Số nằm trong khoảng 1-9")
            else:
                hints.append(f"💡 Gợi ý 3: Số nằm trong khoảng {lower}-{upper}")
                
        return f"{hints[0]}\n\n🎯 Còn {self.max_hints - self.hints_used} gợi ý"
        
    def make_guess(self, guess: int) -> Tuple[bool, str]:
        self.attempts += 1
        self.score -= 50
        
        if guess == self.secret_number:
            time_taken = (datetime.now() - self.start_time).seconds
            final_score = max(self.score, 100)
            return True, f"🎉 Chúc mừng! Bạn đã đoán đúng số {self.secret_number} sau {self.attempts} lần thử trong {time_taken} giây!\n\n🏆 Điểm: {final_score}"
            
        if self.attempts >= self.max_attempts:
            return True, f"😢 Hết lượt! Số bí mật là {self.secret_number}.\n\n💡 Câu đố: {self.riddle}\n\nChơi lại với /guessnumber"
            
        hint = "📈 cao hơn" if guess < self.secret_number else "📉 thấp hơn"
        remaining = self.max_attempts - self.attempts
        return False, f"Số {guess} {hint}!\n\n📊 Còn {remaining} lượt\n💰 Điểm hiện tại: {self.score}\n\n💡 Gửi /hint để xem gợi ý (trừ 100 điểm)"

class NoiTuGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.history = []
        self.score = 0
        self.current_word = ""
        self.start_time = datetime.now()
        self.player_words = 0
        self.bot_words = 0
        common_starts = ["con người", "bầu trời", "mặt đất", "nước mắt", "tình yêu", "cuộc sống", "gia đình", "nhà cửa", "bạn bè"]
        self.start_words = [w for w in common_starts if all(part in vietnamese_words for part in w.split())]
        if not self.start_words:
            self.start_words = ["con", "người", "bầu", "trời", "mặt", "đất", "nước", "tình", "yêu"]
        
    def start(self) -> str:
        self.current_word = random.choice(self.start_words)
        self.history = [self.current_word]
        last_word = self.current_word.split()[-1]
        
        return f"""🎮 **Trò chơi Nối Từ**

📖 Luật chơi:
- Nối từ/cụm từ tiếng Việt có trong từ điển
- Từ mới phải bắt đầu bằng TỪ CUỐI của cụm từ trước
- Không được lặp lại từ đã dùng
- Gõ 'thua' để kết thúc

🎯 Cụm từ đầu: **{self.current_word}**

Hãy nối từ/cụm từ bắt đầu bằng từ '{last_word}'"""
        
    def play_word(self, word: str) -> Tuple[bool, str]:
        word = word.lower().strip()
        
        if word == "thua":
            time_taken = (datetime.now() - self.start_time).seconds
            return True, f"""🏁 Kết thúc trò chơi!

📊 Thống kê:
- Điểm: {self.score}
- Thời gian: {time_taken} giây
- Tổng số từ: {len(self.history)}
- Từ của bạn: {self.player_words}
- Từ của bot: {self.bot_words}

Chơi lại với /noitu"""
        
        if not word:
            return False, "❌ Vui lòng nhập một từ!"
        
        last_word = self.current_word.split()[-1]
        first_word = word.split()[0]
        
        if first_word != last_word:
            return False, f"❌ Từ/cụm từ phải bắt đầu bằng từ '{last_word}'"
            
        if word in self.history:
            return False, "❌ Từ/cụm từ này đã được sử dụng!"
        
        word_parts = word.split()
        if not all(part in vietnamese_words for part in word_parts):
            return False, "❌ Từ/cụm từ không hợp lệ hoặc không có trong từ điển!"
            
        self.history.append(word)
        self.current_word = word
        self.player_words += 1
        points = len(word.replace(" ", "")) * 10
        self.score += points
        
        bot_word = self.find_bot_word(word.split()[-1])
        if bot_word:
            self.history.append(bot_word)
            self.current_word = bot_word
            self.bot_words += 1
            bot_last_word = bot_word.split()[-1]
            return False, f"""✅ Tốt! (+{points} điểm)

🤖 Tôi nối: **{bot_word}**

📊 Điểm: {self.score} | Số từ: {len(self.history)}

Lượt của bạn, nối từ bắt đầu bằng '{bot_last_word}'"""
        else:
            time_taken = (datetime.now() - self.start_time).seconds
            self.score += 500
            return True, f"""🎉 Xuất sắc! Bot không nối được!

🏆 **BẠN THẮNG!**

📊 Thống kê:
- Điểm: {self.score} (bonus +500)
- Thời gian: {time_taken} giây
- Tổng số từ: {len(self.history)}
- Từ của bạn: {self.player_words}
- Từ của bot: {self.bot_words}"""
            
    def find_bot_word(self, start_word: str) -> Optional[str]:
        single_words = [
            word for word in vietnamese_words 
            if word == start_word and word not in self.history
        ]
        
        compound_words = []
        for word in vietnamese_words:
            if word != start_word and len(word) > len(start_word):
                potential_compound = f"{start_word} {word}"
                if potential_compound not in self.history:
                    compound_words.append(potential_compound)
        
        all_options = single_words[:5] + compound_words[:15]
        
        if all_options:
            return random.choice(all_options)
        return None

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
            "temperature": 0.7
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
            logger.error(f"API error: {response.status_code} - {response.text}")
            return "Xin lỗi, tôi gặp lỗi khi xử lý. Vui lòng thử lại sau."
            
    except Exception as e:
        logger.error(f"API call error: {e}")
        return "Xin lỗi, có lỗi xảy ra. Vui lòng thử lại sau."

async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        messages = [
            {"role": "system", "content": "Bạn là trợ lý AI thân thiện. Khi được hỏi về thời tiết mà không có dữ liệu thực, hãy trả lời một cách hữu ích và gợi ý người dùng kiểm tra các nguồn thời tiết đáng tin cậy."},
            {"role": "user", "content": f"Thời tiết ở {city} như thế nào?"}
        ]
        return await call_vercel_api(messages)
        
    try:
        city_map = {
            "hà nội": "Hanoi",
            "hồ chí minh": "Ho Chi Minh City", 
            "sài gòn": "Ho Chi Minh City",
            "đà nẵng": "Da Nang",
            "cần thơ": "Can Tho",
            "hải phòng": "Hai Phong",
            "nha trang": "Nha Trang",
            "đà lạt": "Da Lat",
            "huế": "Hue",
            "vũng tàu": "Vung Tau",
            "phú quốc": "Phu Quoc",
            "quy nhơn": "Quy Nhon"
        }
        
        city_query = city_map.get(city.lower(), city)
        
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city_query},VN&appid={WEATHER_API_KEY}&units=metric&lang=vi"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            weather_info = f"""
🌤️ **Thời tiết {data['name']}**

🌡️ Nhiệt độ: {data['main']['temp']}°C (cảm giác như {data['main']['feels_like']}°C)
💨 Gió: {data['wind']['speed']} m/s
💧 Độ ẩm: {data['main']['humidity']}%
☁️ Mây: {data['clouds']['all']}%
🌅 Bình minh: {datetime.fromtimestamp(data['sys']['sunrise']).strftime('%H:%M')}
🌇 Hoàng hôn: {datetime.fromtimestamp(data['sys']['sunset']).strftime('%H:%M')}

📝 {data['weather'][0]['description'].capitalize()}
"""
            return weather_info
        else:
            messages = [
                {"role": "system", "content": "Bạn là trợ lý AI. Trả lời về thời tiết một cách hữu ích."},
                {"role": "user", "content": f"Thời tiết ở {city} như thế nào?"}
            ]
            return await call_vercel_api(messages)
            
    except Exception as e:
        logger.error(f"Weather API error: {e}")
        messages = [
            {"role": "system", "content": "Bạn là trợ lý AI. Trả lời về thời tiết một cách hữu ích."},
            {"role": "user", "content": f"Thời tiết ở {city} như thế nào?"}
        ]
        return await call_vercel_api(messages)

async def generate_quiz() -> dict:
    prompt = """Hãy tạo một câu đố vui bằng tiếng Việt với format sau:

Câu hỏi: [câu hỏi thú vị về kiến thức tổng quát, ưu tiên về Việt Nam]
A. [đáp án A]
B. [đáp án B]
C. [đáp án C]
D. [đáp án D]
Đáp án: [A/B/C/D]
Giải thích: [giải thích ngắn gọn và thú vị]"""

    messages = [
        {"role": "system", "content": "Bạn là người tạo câu đố thông minh. Tạo câu đố về các chủ đề đa dạng: lịch sử, địa lý, khoa học, văn hóa, đặc biệt là về Việt Nam."},
        {"role": "user", "content": prompt}
    ]
    
    response = await call_vercel_api(messages, max_tokens=500)
    
    lines = response.strip().split('\n')
    quiz = {
        "question": "",
        "options": [],
        "correct": "",
        "explanation": ""
    }
    
    for line in lines:
        line = line.strip()
        if line.startswith("Câu hỏi:"):
            quiz["question"] = line.replace("Câu hỏi:", "").strip()
        elif line.startswith(("A.", "B.", "C.", "D.")):
            quiz["options"].append(line)
        elif line.startswith("Đáp án:"):
            quiz["correct"] = line.replace("Đáp án:", "").strip()[0]
        elif line.startswith("Giải thích:"):
            quiz["explanation"] = line.replace("Giải thích:", "").strip()
            
    return quiz

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = """
👋 **Xin chào! Tôi là Bot AI thông minh**

🤖 **Tính năng chính:**
• Chat AI thông minh với Claude 3 Haiku
• Thông tin thời tiết Việt Nam
• Nhiều trò chơi thú vị

📝 **Lệnh game (chơi ngay):**
/guessnumber - Đoán số bí mật
/noitu - Nối từ tiếng Việt
/quiz - Câu đố vui

🏆 /leaderboard - Bảng xếp hạng tổng
📊 /stats - Xem thống kê cá nhân

💬 Hoặc chat trực tiếp với tôi!
"""
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 **HƯỚNG DẪN SỬ DỤNG**

**🎮 Lệnh Game (chơi ngay):**
• /guessnumber - Đoán số 1-100
• /noitu - Nối từ/cụm từ tiếng Việt
• /quiz - Trả lời câu đố
• /hint - Gợi ý (trong đoán số)

**📊 Thống kê:**
• /leaderboard - BXH tổng điểm
• /stats - Thống kê cá nhân

**💬 Chat & Tiện ích:**
• Chat trực tiếp không cần lệnh
• /weather <city> - Thời tiết
• /clear - Xóa lịch sử chat

💡 Điểm tổng = Tổng điểm tất cả game!
"""
    await update.message.reply_text(help_text)

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = """
🤖 **VỀ BOT AI**

**Công nghệ:**
• AI: Claude 3 Haiku (Anthropic)
• Platform: Vercel AI Gateway
• Từ điển: 74K+ từ tiếng Việt

**Game & Điểm:**
• Điểm tổng = Tất cả game cộng lại
• Mỗi game có cách tính điểm riêng
• BXH cập nhật real-time

**Phiên bản:** 3.1
"""
    await update.message.reply_text(about_text)

async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in chat_history:
        chat_history[chat_id] = []
    await update.message.reply_text("✅ Đã xóa lịch sử chat!")

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Vui lòng nhập tên thành phố!\n\nVí dụ: /weather hanoi")
        return
        
    city = " ".join(context.args)
    weather_info = await get_weather(city)
    await update.message.reply_text(weather_info)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_total_scores()
    
    message = "🏆 **BẢNG XẾP HẠNG TỔNG ĐIỂM**\n\n"
    
    if scores:
        for i, (username, total_score) in enumerate(scores, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            message += f"{medal} {username}: {total_score:,} điểm\n"
    else:
        message += "Chưa có dữ liệu. Hãy chơi game để lên bảng!"
        
    message += "\n💡 Điểm tổng = Tổng điểm tất cả game"
    await update.message.reply_text(message)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats = get_user_stats(user.id)
    
    message = f"📊 **THỐNG KÊ CỦA {user.first_name}**\n\n"
    message += f"💰 Tổng điểm: {stats['total']:,}\n\n"
    
    if stats['games']:
        for game_type, data in stats['games'].items():
            game_name = "Đoán Số" if game_type == "guessnumber" else "Nối Từ" if game_type == "noitu" else "Câu Đố"
            message += f"**{game_name}:**\n"
            message += f"• Số lần chơi: {data['played']}\n"
            message += f"• Tổng điểm: {data['total']:,}\n"
            message += f"• Điểm cao nhất: {data['best']:,}\n\n"
    else:
        message += "Bạn chưa chơi game nào!"
        
    await update.message.reply_text(message)

async def start_guess_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
        
    use_ai = random.choice([True, False])
    game = GuessNumberGame(chat_id, use_ai)
    active_games[chat_id] = {"type": "guessnumber", "game": game}
    
    message = f"""🎮 **ĐOÁN SỐ BÍ MẬT**

🎯 Số từ 1 đến 100
📝 Bạn có 10 lần đoán
💡 Có 3 lần gợi ý (/hint)

🔍 **Câu đố:** {game.riddle}

Gửi số đoán của bạn!"""
    
    await update.message.reply_text(message)

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
        await update.message.reply_text("❌ Bạn không đang chơi đoán số!\n\n/guessnumber để bắt đầu")
        return
        
    game = active_games[chat_id]["game"]
    hint = game.get_hint()
    await update.message.reply_text(hint)

async def start_noitu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
        
    game = NoiTuGame(chat_id)
    active_games[chat_id] = {"type": "noitu", "game": game}
    
    message = game.start()
    await update.message.reply_text(message)

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    quiz = await generate_quiz()
    
    if quiz["question"] and quiz["options"]:
        quiz_sessions[chat_id] = quiz
        
        keyboard = []
        for option in quiz["options"]:
            letter = option[0]
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{letter}")])
        keyboard.append([InlineKeyboardButton("❌ Bỏ qua", callback_data="quiz_skip")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"❓ **CÂU ĐỐ VUI**\n\n{quiz['question']}"
        
        await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text("Xin lỗi, không thể tạo câu đố lúc này!")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    if data.startswith("quiz_"):
        if chat_id not in quiz_sessions:
            await query.message.edit_text("❌ Câu đố đã hết hạn!")
            return
            
        quiz = quiz_sessions[chat_id]
        
        if data == "quiz_skip":
            await query.message.edit_text(f"Đáp án đúng là: **{quiz['correct']}**\n\n{quiz['explanation']}")
        else:
            answer = data.split("_")[1]
            if answer == quiz["correct"]:
                save_score(user.id, username, "quiz", 200)
                await query.message.edit_text(f"✅ Chính xác! (+200 điểm)\n\n{quiz['explanation']}")
            else:
                await query.message.edit_text(f"❌ Sai rồi! Đáp án đúng là: **{quiz['correct']}**\n\n{quiz['explanation']}")
        
        del quiz_sessions[chat_id]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_name = user.first_name
    username = user.username or user_name
    
    if chat_id in active_games:
        game_info = active_games[chat_id]
        
        if game_info["type"] == "guessnumber":
            try:
                guess = int(message)
                if 1 <= guess <= 100:
                    is_finished, response = game_info["game"].make_guess(guess)
                    await update.message.reply_text(response)
                    
                    if is_finished and "Chúc mừng" in response:
                        final_score = game_info["game"].score
                        if final_score < 0:
                            final_score = 100
                        save_score(user.id, username, "guessnumber", final_score)
                        
                    if is_finished:
                        del active_games[chat_id]
                else:
                    await update.message.reply_text("❌ Vui lòng nhập số từ 1 đến 100!")
            except ValueError:
                await update.message.reply_text("❌ Vui lòng nhập một số!\n\n💡 /hint để xem gợi ý")
                
        elif game_info["type"] == "noitu":
            is_finished, response = game_info["game"].play_word(message)
            await update.message.reply_text(response)
            
            if is_finished:
                save_score(user.id, username, "noitu", game_info["game"].score)
                del active_games[chat_id]
                
        return
    
    if "thời tiết" in message.lower():
        words = message.lower().split()
        if "thời tiết" in words:
            idx = words.index("thời tiết")
            if idx + 1 < len(words):
                city = " ".join(words[idx + 1:])
                weather_info = await get_weather(city)
                await update.message.reply_text(weather_info)
                return
    
    if chat_id not in chat_history:
        chat_history[chat_id] = []
        
    chat_history[chat_id].append({"role": "user", "content": message})
    
    if len(chat_history[chat_id]) > CTX_TURNS * 2:
        chat_history[chat_id] = chat_history[chat_id][-(CTX_TURNS * 2):]
    
    messages = [
        {"role": "system", "content": f"Bạn là trợ lý AI thân thiện, hữu ích. Bạn đang chat với {user_name}. Hãy trả lời bằng tiếng Việt một cách tự nhiên, thân thiện. Khi được hỏi về bot, giới thiệu các game: /guessnumber, /noitu, /quiz và hệ thống điểm tổng."}
    ]
    messages.extend(chat_history[chat_id])
    
    response = await call_vercel_api(messages, MAX_TOKENS)
    
    chat_history[chat_id].append({"role": "assistant", "content": response})
    
    await update.message.reply_text(response)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("clear", clear_history))
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_handler(CommandHandler("guessnumber", start_guess_number))
    application.add_handler(CommandHandler("noitu", start_noitu))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("hint", hint_command))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot started!")
    application.run_polling()

if __name__ == "__main__":
    main()
