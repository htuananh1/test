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
            return "❌ Hết gợi ý rồi! Cố lên nào!"
            
        self.hints_used += 1
        self.score -= 100
        
        hints = []
        
        if self.hints_used == 1:
            tens = self.secret_number // 10
            if tens == 0:
                hints.append("💡 Gợi ý 1: Số có 1 chữ số thôi")
            else:
                hints.append(f"💡 Gợi ý 1: Chữ số hàng chục là {tens}")
                
        elif self.hints_used == 2:
            digit_sum = sum(int(d) for d in str(self.secret_number))
            hints.append(f"💡 Gợi ý 2: Tổng các chữ số là {digit_sum}")
            
        elif self.hints_used == 3:
            lower = (self.secret_number // 10) * 10
            upper = lower + 9
            if lower == 0:
                hints.append(f"💡 Gợi ý 3: Số nằm từ 1 đến 9")
            else:
                hints.append(f"💡 Gợi ý 3: Số nằm từ {lower} đến {upper}")
                
        return f"{hints[0]}\n\n🎯 Còn {self.max_hints - self.hints_used} gợi ý"
        
    def make_guess(self, guess: int) -> Tuple[bool, str]:
        self.attempts += 1
        self.score -= 50
        
        if guess == self.secret_number:
            time_taken = (datetime.now() - self.start_time).seconds
            final_score = max(self.score, 100)
            return True, f"🎉 Giỏi lắm! Đoán đúng số {self.secret_number} sau {self.attempts} lần trong {time_taken} giây!\n\n🏆 Điểm: {final_score}"
            
        if self.attempts >= self.max_attempts:
            return True, f"😤 Hết lượt rồi! Số là {self.secret_number} đó!\n\n💡 Gợi ý: {self.riddle}\n\nChơi lại đi! /guessnumber"
            
        hint = "📈 cao hơn" if guess < self.secret_number else "📉 thấp hơn"
        remaining = self.max_attempts - self.attempts
        return False, f"Số {guess} {hint}!\n\n📊 Còn {remaining} lượt\n💰 Điểm: {self.score}\n\n💡 Gõ /hint xem gợi ý (-100 điểm)"

class NoiTuGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.history = []
        self.score = 0
        self.current_word = ""
        self.start_time = datetime.now()
        self.player_words = 0
        self.bot_words = 0
        self.two_word_compounds = self.get_two_word_compounds()
        
    def get_two_word_compounds(self) -> set:
        compounds = set()
        words_list = list(vietnamese_words)
        
        for i in range(len(words_list)):
            for j in range(len(words_list)):
                if i != j:
                    compound = f"{words_list[i]} {words_list[j]}"
                    if len(compound.split()) == 2:
                        compounds.add(compound)
        
        return compounds
        
    def start(self) -> str:
        start_compounds = ["trong sạch", "sạch sẽ", "đẹp đẽ", "tươi tốt", "vui vẻ", "mạnh mẽ", "nhanh nhẹn", "xinh xắn"]
        valid_starts = []
        
        for compound in start_compounds:
            parts = compound.split()
            if len(parts) == 2 and all(part in vietnamese_words for part in parts):
                valid_starts.append(compound)
                
        if valid_starts:
            self.current_word = random.choice(valid_starts)
        else:
            self.current_word = "trong sáng"
            
        self.history = [self.current_word]
        last_word = self.current_word.split()[1]
        
        return f"""🎮 **Linh thách đấu Nối Từ!**

📖 Luật: Nối từ 2 từ ghép tiếng Việt
VD: trong sạch → sạch sẽ → sẽ sàng...

🎯 Từ đầu: **{self.current_word}**

Nối tiếp với từ bắt đầu bằng '{last_word}'
Gõ 'thua' để kết thúc"""
        
    def check_valid_compound(self, word: str) -> bool:
        parts = word.split()
        if len(parts) != 2:
            return False
        return all(part in vietnamese_words for part in parts)
        
    def play_word(self, word: str) -> Tuple[bool, str]:
        word = word.lower().strip()
        
        if word == "thua":
            time_taken = (datetime.now() - self.start_time).seconds
            return True, f"""😏 Chịu thua rồi à!

📊 Kết quả:
- Điểm: {self.score}
- Thời gian: {time_taken} giây
- Tổng từ: {len(self.history)}
- Của bạn: {self.player_words}
- Của Linh: {self.bot_words}

Chơi lại không? /noitu"""
        
        if not word:
            return False, "❌ Gõ gì đó đi chứ!"
        
        parts = word.split()
        if len(parts) != 2:
            return False, "❌ Phải là từ ghép 2 từ! VD: sạch sẽ"
        
        last_word = self.current_word.split()[1]
        first_word = parts[0]
        
        if first_word != last_word:
            return False, f"❌ Phải bắt đầu bằng '{last_word}' chứ!"
            
        if word in self.history:
            return False, "❌ Từ này dùng rồi! Nghĩ từ khác đi!"
        
        if not self.check_valid_compound(word):
            return False, "❌ Từ không hợp lệ! Phải có trong từ điển!"
            
        self.history.append(word)
        self.current_word = word
        self.player_words += 1
        points = 100
        self.score += points
        
        bot_word = self.find_bot_word(parts[1])
        if bot_word:
            self.history.append(bot_word)
            self.current_word = bot_word
            self.bot_words += 1
            bot_last_word = bot_word.split()[1]
            return False, f"""✅ Được đó! (+{points} điểm)

🤖 Linh nối: **{bot_word}**

📊 Điểm: {self.score} | Số từ: {len(self.history)}

Đến lượt bạn, nối với '{bot_last_word}'"""
        else:
            time_taken = (datetime.now() - self.start_time).seconds
            self.score += 500
            return True, f"""😱 Trời ơi! Linh không nối được!

🏆 **BẠN THẮNG RỒI!**

📊 Kết quả:
- Điểm: {self.score} (bonus +500)
- Thời gian: {time_taken} giây
- Tổng từ: {len(self.history)}
- Của bạn: {self.player_words}
- Của Linh: {self.bot_words}

Giỏi ghê! 🔥"""
            
    def find_bot_word(self, start_word: str) -> Optional[str]:
        possible_words = []
        
        for word in vietnamese_words:
            if word != start_word:
                compound = f"{start_word} {word}"
                if compound not in self.history and self.check_valid_compound(compound):
                    possible_words.append(compound)
                    
        if possible_words:
            return random.choice(possible_words[:20])
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
            logger.error(f"API error: {response.status_code} - {response.text}")
            return "Ủa lỗi gì vậy? Thử lại đi!"
            
    except Exception as e:
        logger.error(f"API call error: {e}")
        return "Lỗi rồi! Thử lại sau nhé!"

async def get_weather(city: str) -> str:
    if not WEATHER_API_KEY:
        messages = [
            {"role": "system", "content": "Bạn là Linh, cô gái Việt Nam nóng nảy. Khi được hỏi về thời tiết mà không có dữ liệu, hãy trả lời theo phong cách hài hước."},
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

🌡️ Nhiệt độ: {data['main']['temp']}°C (cảm giác {data['main']['feels_like']}°C)
💨 Gió: {data['wind']['speed']} m/s
💧 Độ ẩm: {data['main']['humidity']}%
☁️ Mây: {data['clouds']['all']}%

📝 {data['weather'][0]['description'].capitalize()}

💬 Linh mách: {"Nóng vậy nhớ uống nước!" if data['main']['temp'] > 30 else "Lạnh vậy mặc ấm vào!" if data['main']['temp'] < 20 else "Thời tiết dễ chịu, đi chơi không?"}
"""
            return weather_info
        else:
            return f"😤 Không tìm thấy {city}! Gõ đúng tên thành phố đi!"
            
    except Exception as e:
        logger.error(f"Weather API error: {e}")
        return "😩 Lỗi rồi! Check thời tiết trên mạng đi!"

async def generate_quiz() -> dict:
    prompt = """Tạo câu đố vui tiếng Việt theo format CHÍNH XÁC sau (mỗi đáp án chỉ xuất hiện 1 lần):

Câu hỏi: [câu hỏi]
A. [đáp án A]
B. [đáp án B]
C. [đáp án C]
D. [đáp án D]
Đáp án: [chỉ chữ A hoặc B hoặc C hoặc D]
Giải thích: [giải thích]"""

    messages = [
        {"role": "system", "content": "Bạn là Linh. Tạo 1 câu đố về Việt Nam (văn hóa, lịch sử, ẩm thực, địa lý). Mỗi đáp án A,B,C,D chỉ viết 1 lần, không lặp lại."},
        {"role": "user", "content": prompt}
    ]
    
    response = await call_vercel_api(messages, max_tokens=400)
    
    lines = response.strip().split('\n')
    quiz = {
        "question": "",
        "options": [],
        "correct": "",
        "explanation": ""
    }
    
    options_found = {"A": False, "B": False, "C": False, "D": False}
    
    for line in lines:
        line = line.strip()
        if line.startswith("Câu hỏi:"):
            quiz["question"] = line.replace("Câu hỏi:", "").strip()
        elif line.startswith("A.") and not options_found["A"]:
            quiz["options"].append(line)
            options_found["A"] = True
        elif line.startswith("B.") and not options_found["B"]:
            quiz["options"].append(line)
            options_found["B"] = True
        elif line.startswith("C.") and not options_found["C"]:
            quiz["options"].append(line)
            options_found["C"] = True
        elif line.startswith("D.") and not options_found["D"]:
            quiz["options"].append(line)
            options_found["D"] = True
        elif line.startswith("Đáp án:"):
            answer = line.replace("Đáp án:", "").strip()
            if answer and answer[0] in ["A", "B", "C", "D"]:
                quiz["correct"] = answer[0]
        elif line.startswith("Giải thích:"):
            quiz["explanation"] = line.replace("Giải thích:", "").strip()
    
    if len(quiz["options"]) != 4:
        quiz["options"] = quiz["options"][:4]
            
    return quiz

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = """
👋 **Chào! Mình là Linh nè!**

🎮 **Chơi game với Linh:**
/guessnumber - Đoán số (Linh nghĩ số)
/noitu - Nối từ (thách đấu Linh)
/quiz - Câu đố vui

🏆 /leaderboard - BXH 24h gần nhất
📊 /stats - Điểm của bạn

💬 Chat với Linh về game hoặc bất cứ gì!
⚡ Linh hơi nóng tính nhưng vui lắm! 😄
"""
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 **HƯỚNG DẪN CHƠI**

**🎮 Game của Linh:**
• /guessnumber - Đoán số 1-100
  → 10 lần đoán, 3 gợi ý
• /noitu - Nối từ ghép 2 từ
  → VD: trong sạch → sạch sẽ
• /quiz - Trả lời câu đố
• /hint - Gợi ý (trong đoán số)

**📊 Điểm & BXH:**
• /leaderboard - BXH 24h
• /stats - Điểm của bạn

**💬 Chat & Khác:**
• Chat trực tiếp với Linh
• /weather <city> - Thời tiết

💡 Càng chơi nhiều càng lên top!
"""
    await update.message.reply_text(help_text)

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = """
🤖 **VỀ LINH**

Xin chào! Mình là Linh - AI assistant vui tính!

**Tính cách:**
• Nóng nảy nhưng thân thiện
• Thích thách đấu game
• Biết nhiều về Việt Nam

**Game & Điểm:**
• BXH reset sau 24h
• Điểm = Tổng các game
• Chơi nhiều = Điểm cao

**Tech:** Claude 3 Haiku x Vercel
"""
    await update.message.reply_text(about_text)

async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in chat_history:
        chat_history[chat_id] = []
    await update.message.reply_text("✅ Đã xóa lịch sử chat! Nói chuyện lại từ đầu nhé!")

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Gõ tên thành phố đi!\n\nVD: /weather hanoi")
        return
        
    city = " ".join(context.args)
    weather_info = await get_weather(city)
    await update.message.reply_text(weather_info)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_leaderboard_24h()
    
    message = "🏆 **BẢNG XẾP HẠNG 24H**\n\n"
    
    if scores:
        for i, (username, total_score, games_played) in enumerate(scores, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            message += f"{medal} {username}: {total_score:,}đ ({games_played} game)\n"
    else:
        message += "Chưa ai chơi! Làm người đầu tiên đi!"
        
    message += f"\n⏰ BXH reset sau 24h\n💡 Chơi nhiều game để lên top!"
    await update.message.reply_text(message)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats = get_user_stats_24h(user.id)
    
    message = f"📊 **ĐIỂM CỦA {user.first_name.upper()} (24H)**\n\n"
    message += f"💰 Tổng: {stats['total']:,} điểm\n\n"
    
    if stats['games']:
        for game_type, data in stats['games'].items():
            game_name = "Đoán Số" if game_type == "guessnumber" else "Nối Từ" if game_type == "noitu" else "Câu Đố"
            message += f"**{game_name}:**\n"
            message += f"• Số lần: {data['played']}\n"
            message += f"• Tổng điểm: {data['total']:,}\n"
            message += f"• Cao nhất: {data['best']:,}\n\n"
    else:
        message += "Chưa chơi game nào!\nThử /guessnumber hoặc /noitu đi!"
        
    await update.message.reply_text(message)

async def start_guess_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
        
    use_ai = random.choice([True, False])
    game = GuessNumberGame(chat_id, use_ai)
    active_games[chat_id] = {"type": "guessnumber", "game": game}
    
    message = f"""🎮 **LINH THÁCH ĐOÁN SỐ!**

🎯 Linh nghĩ 1 số từ 1-100
📝 Bạn có 10 lần đoán
💡 3 gợi ý (/hint)

🔍 **Mách nước:** {game.riddle}

Đoán thử xem!"""
    
    await update.message.reply_text(message)

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
        await update.message.reply_text("❌ Đang không chơi đoán số!\n\n/guessnumber để chơi")
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
    
    if quiz["question"] and len(quiz["options"]) == 4:
        quiz_sessions[chat_id] = quiz
        
        keyboard = []
        for option in quiz["options"]:
            letter = option[0]
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{letter}")])
        keyboard.append([InlineKeyboardButton("❌ Bỏ qua", callback_data="quiz_skip")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"❓ **LINH HỎI NÈ!**\n\n{quiz['question']}"
        
        await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text("😤 Lỗi rồi! Thử lại đi!")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    if data.startswith("quiz_"):
        if chat_id not in quiz_sessions:
            await query.message.edit_text("❌ Hết giờ rồi!")
            return
            
        quiz = quiz_sessions[chat_id]
        
        if data == "quiz_skip":
            await query.message.edit_text(f"😏 Bỏ cuộc à?\n\nĐáp án: **{quiz['correct']}**\n\n{quiz['explanation']}")
        else:
            answer = data.split("_")[1]
            if answer == quiz["correct"]:
                save_score(user.id, username, "quiz", 200)
                await query.message.edit_text(f"✅ Giỏi! (+200 điểm)\n\n{quiz['explanation']}")
            else:
                await query.message.edit_text(f"❌ Sai rồi!\n\nĐáp án: **{quiz['correct']}**\n\n{quiz['explanation']}")
        
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
                    
                    if is_finished and "Giỏi lắm" in response:
                        final_score = max(game_info["game"].score, 100)
                        save_score(user.id, username, "guessnumber", final_score)
                        
                    if is_finished:
                        del active_games[chat_id]
                else:
                    await update.message.reply_text("❌ Từ 1 đến 100 thôi!")
            except ValueError:
                await update.message.reply_text("❌ Gõ số đi!\n\n💡 /hint để xem gợi ý")
                
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
        {"role": "system", "content": f"""Bạn là Linh - cô gái Việt Nam 20 tuổi, nóng nảy, vui tính, thích chơi game. 
        Tính cách: hơi nóng, hay cười 😄, dùng emoji, nói chuyện tự nhiên như gen Z Việt Nam.
        Khi được hỏi về bot/game: giới thiệu /guessnumber, /noitu, /quiz và hệ thống BXH 24h.
        Hay thách thức người chơi thử game, khoe mình giỏi nối từ."""}
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
    
    logger.info("Linh Bot started! 🎮")
    application.run_polling()

if __name__ == "__main__":
    main()
