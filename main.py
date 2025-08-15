import os
import random
import asyncio
import logging
import requests
import json
import sqlite3
import gc
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "alibaba/qwen-3-32b")
QUIZ_MODEL = "anthropic/claude-3-haiku"  # Claude cho quiz
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
    conn.commit()
    conn.close()

init_db()

active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
quiz_sessions: Dict[int, dict] = {}
quiz_mode: Dict[int, bool] = {}
quiz_count: Dict[int, int] = {}
quiz_history: Dict[int, List[str]] = {}
used_words_global: set = set()

# Từ có nghĩa cho game nối từ
VIETNAMESE_WORDS = [
    # Danh từ
    "con", "người", "nhà", "cửa", "bàn", "ghế", "sách", "vở", "bút", "mực",
    "trường", "học", "lớp", "thầy", "cô", "trò", "bạn", "bè", "anh", "em",
    "cha", "mẹ", "ông", "bà", "cháu", "con", "gái", "trai", "chồng", "vợ",
    "đường", "phố", "làng", "xóm", "thành", "thị", "nông", "thôn", "miền", "quê",
    "sông", "nước", "biển", "hồ", "núi", "đồi", "cây", "lá", "hoa", "quả",
    "mặt", "trời", "trăng", "sao", "mây", "gió", "mưa", "nắng", "sương", "khói",
    "tay", "chân", "đầu", "mắt", "mũi", "miệng", "tai", "tóc", "da", "thịt",
    "áo", "quần", "giày", "dép", "mũ", "nón", "khăn", "túi", "ví", "balo",
    "cơm", "nước", "bánh", "kẹo", "trái", "rau", "thịt", "cá", "tôm", "cua",
    "xe", "máy", "ô", "tô", "tàu", "thuyền", "máy", "bay", "đạp", "buýt",
    
    # Tính từ
    "đẹp", "xấu", "tốt", "xấu", "cao", "thấp", "dài", "ngắn", "to", "nhỏ",
    "nhanh", "chậm", "mới", "cũ", "trẻ", "già", "khỏe", "yếu", "giàu", "nghèo",
    "vui", "buồn", "sướng", "khổ", "thương", "ghét", "yêu", "quý", "mến", "thích",
    "sạch", "bẩn", "trong", "đục", "sáng", "tối", "trắng", "đen", "xanh", "đỏ",
    "ngọt", "đắng", "chua", "cay", "mặn", "nhạt", "thơm", "thối", "tanh", "hôi",
    "cứng", "mềm", "ướt", "khô", "nóng", "lạnh", "ấm", "mát", "dày", "mỏng",
    
    # Động từ
    "đi", "đến", "về", "lên", "xuống", "vào", "ra", "qua", "lại", "sang",
    "ăn", "uống", "ngủ", "thức", "nằm", "ngồi", "đứng", "chạy", "nhảy", "múa",
    "nói", "nghe", "nhìn", "thấy", "hiểu", "biết", "học", "hỏi", "trả", "lời",
    "làm", "việc", "chơi", "nghỉ", "ngơi", "giúp", "đỡ", "cứu", "vớt", "giữ",
    "mua", "bán", "đổi", "trao", "nhận", "cho", "tặng", "gửi", "gởi", "nhờ",
    "yêu", "thương", "ghét", "giận", "hờn", "cười", "khóc", "la", "hét", "gọi",
    "viết", "vẽ", "đọc", "xem", "ngắm", "sờ", "chạm", "cầm", "nắm", "bắt",
    "mở", "đóng", "khóa", "cài", "gài", "buộc", "cột", "trói", "tháo", "gỡ",
    
    # Từ ghép phổ biến
    "sinh", "viên", "giáo", "dục", "văn", "hóa", "nghệ", "thuật", "khoa", "học",
    "công", "nghệ", "kinh", "tế", "chính", "trị", "xã", "hội", "môi", "trường",
    "thể", "thao", "âm", "nhạc", "điện", "ảnh", "báo", "chí", "truyền", "thông"
]

QUIZ_TOPICS = ["lịch sử", "địa lý", "ẩm thực", "văn hóa", "du lịch"]

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
        global used_words_global
        
        # Chọn từ ghép có nghĩa để bắt đầu
        start_compounds = [
            "học sinh", "sinh viên", "viên chức", "chức năng", "năng lực",
            "công việc", "việc làm", "làm việc", "giáo viên", "viên mãn",
            "thành phố", "phố phường", "phường xá", "xã hội", "hội họp",
            "đất nước", "nước mắt", "mắt kính", "kính trọng", "trọng yếu",
            "con người", "người yêu", "yêu thương", "thương mại", "mại dâm",
            "bạn bè", "bè phái", "phái đoàn", "đoàn kết", "kết thúc"
        ]
        
        available_starts = [s for s in start_compounds if s not in used_words_global]
        
        if not available_starts:
            used_words_global.clear()
            available_starts = start_compounds
        
        self.current_word = random.choice(available_starts)
        self.history = [self.current_word]
        used_words_global.add(self.current_word)
        
        last_word = self.current_word.split()[-1]
        
        return f"""🎮 **Nối Từ với Linh!**

📖 Luật: Nối từ/cụm từ có nghĩa tiếng Việt
VD: học sinh → sinh viên → viên chức

🎯 **{self.current_word}**
Nối với từ '{last_word}' | Gõ 'thua' kết thúc"""
        
    def play_word(self, word: str) -> Tuple[bool, str]:
        global used_words_global
        word = word.lower().strip()
        
        if word == "thua":
            return True, f"📊 Điểm: {self.score} | {len(self.history)} từ"
        
        parts = word.split()
        if len(parts) < 1 or len(parts) > 3:
            return False, "❌ Nhập từ đơn hoặc cụm từ 2-3 từ!"
        
        # Lấy từ cuối của từ hiện tại
        last_word = self.current_word.split()[-1]
        first_word = parts[0]
        
        if first_word != last_word:
            return False, f"❌ Phải bắt đầu bằng '{last_word}'"
            
        if word in self.history or word in used_words_global:
            return False, "❌ Từ đã dùng rồi!"
        
        # Kiểm tra từ có nghĩa
        valid = False
        if len(parts) == 1:
            # Từ đơn phải trong danh sách
            valid = word in VIETNAMESE_WORDS
        else:
            # Cụm từ phải có các phần trong danh sách
            valid = all(p in VIETNAMESE_WORDS for p in parts)
        
        if not valid:
            return False, "❌ Từ không có nghĩa hoặc không phổ biến!"
            
        self.history.append(word)
        used_words_global.add(word)
        self.current_word = word
        self.player_words += 1
        points = len(word.replace(" ", "")) * 10
        self.score += points
        
        # Bot tìm từ để nối
        bot_word = self.find_bot_word(parts[-1])
        
        if bot_word:
            self.history.append(bot_word)
            used_words_global.add(bot_word)
            self.current_word = bot_word
            self.bot_words += 1
            bot_last_word = bot_word.split()[-1]
            return False, f"✅ Tốt! (+{points}đ)\n\n🤖 Linh: **{bot_word}**\n\n📊 Điểm: {self.score} | Nối với '{bot_last_word}'"
        else:
            self.score += 500
            return True, f"🎉 **THẮNG!** Bot không nối được!\n\n📊 Tổng điểm: {self.score} (+500 bonus)"
            
    def find_bot_word(self, start_word: str) -> Optional[str]:
        possible = []
        
        # Tìm từ đơn
        if start_word in VIETNAMESE_WORDS:
            possible.append(start_word)
        
        # Tìm từ ghép 2 từ
        for word in VIETNAMESE_WORDS:
            if word != start_word:
                compound = f"{start_word} {word}"
                if compound not in self.history and compound not in used_words_global:
                    possible.append(compound)
        
        # Tìm từ ghép 3 từ phổ biến
        common_compounds = [
            f"{start_word} sinh viên", f"{start_word} giáo viên",
            f"{start_word} công nhân", f"{start_word} nông dân",
            f"{start_word} học sinh", f"{start_word} bác sĩ"
        ]
        
        for compound in common_compounds:
            parts = compound.split()
            if len(parts) <= 3 and all(p in VIETNAMESE_WORDS for p in parts):
                if compound not in self.history and compound not in used_words_global:
                    possible.append(compound)
        
        if possible:
            return random.choice(possible[:15])
        return None

async def call_api(messages: List[dict], model: str = None, max_tokens: int = 400) -> str:
    """Gọi API với model được chỉ định"""
    try:
        headers = {
            "Authorization": f"Bearer {VERCEL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model or CHAT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "top_p": 0.9
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
    """Tạo quiz với Claude 3 Haiku - độ chính xác cao"""
    global quiz_history
    
    if chat_id not in quiz_history:
        quiz_history[chat_id] = []
    
    topic = random.choice(QUIZ_TOPICS)
    
    # Prompt tối ưu cho Claude
    topic_prompts = {
        "lịch sử": """Tạo câu hỏi về lịch sử Việt Nam với thông tin CHÍNH XÁC TUYỆT ĐỐI.
Chỉ hỏi về các sự kiện, năm, nhân vật đã được xác nhận trong sách giáo khoa.""",
        
        "địa lý": """Tạo câu hỏi về địa lý Việt Nam với thông tin CHÍNH XÁC.
Hỏi về: tỉnh thành, sông núi, diện tích, dân số, vị trí địa lý.""",
        
        "ẩm thực": """Tạo câu hỏi về ẩm thực Việt Nam.
Hỏi về món ăn truyền thống, đặc sản vùng miền, nguyên liệu.""",
        
        "văn hóa": """Tạo câu hỏi về văn hóa Việt Nam.
Hỏi về lễ hội, phong tục, di sản văn hóa, nghệ thuật truyền thống.""",
        
        "du lịch": """Tạo câu hỏi về du lịch Việt Nam.
Hỏi về điểm du lịch nổi tiếng, di tích lịch sử, danh lam thắng cảnh."""
    }
    
    # Thêm câu đã hỏi để tránh lặp
    avoid_text = ""
    if quiz_history[chat_id]:
        recent = quiz_history[chat_id][-10:]
        avoid_text = f"\n\nKHÔNG lặp lại các câu đã hỏi:\n" + "\n".join(f"- {q}" for q in recent)
    
    prompt = f"""{topic_prompts[topic]}

QUAN TRỌNG: Thông tin phải CHÍNH XÁC 100%, có thể kiểm chứng.{avoid_text}

Format bắt buộc:
Câu hỏi: [câu hỏi rõ ràng]
A. [đáp án]
B. [đáp án]
C. [đáp án]
D. [đáp án]
Đáp án: [chỉ A hoặc B hoặc C hoặc D]
Giải thích: [thông tin chính xác với nguồn đáng tin cậy]"""

    messages = [
        {
            "role": "system", 
            "content": f"Bạn là chuyên gia về Việt Nam. Tạo câu hỏi {topic} với độ chính xác tuyệt đối. KHÔNG bịa đặt thông tin."
        },
        {"role": "user", "content": prompt}
    ]
    
    try:
        # Dùng Claude 3 Haiku cho quiz
        response = await call_api(messages, model=QUIZ_MODEL, max_tokens=350)
        
        if not response:
            return None
            
        lines = response.strip().split('\n')
        
        quiz = {"question": "", "options": [], "correct": "", "explanation": "", "topic": topic}
        
        for line in lines:
            line = line.strip()
            if line.startswith("Câu hỏi:"):
                quiz["question"] = line.replace("Câu hỏi:", "").strip()
            elif line.startswith(("A.", "B.", "C.", "D.")):
                if len(quiz["options"]) < 4:
                    quiz["options"].append(line)
            elif line.startswith("Đáp án:"):
                answer = line.replace("Đáp án:", "").strip()
                if answer and answer[0] in "ABCD":
                    quiz["correct"] = answer[0]
            elif line.startswith("Giải thích:"):
                quiz["explanation"] = line.replace("Giải thích:", "").strip()
        
        if quiz["question"] and len(quiz["options"]) == 4 and quiz["correct"]:
            # Lưu câu hỏi vào history
            quiz_history[chat_id].append(quiz["question"][:60])
            return quiz
        
        return None
            
    except Exception as e:
        logger.error(f"Generate quiz error: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
👋 **Xin chào! Mình là Linh!**

🎮 **Game:**
/guessnumber - Đoán số
/noitu - Nối từ có nghĩa
/quiz - Câu đố về Việt Nam
/stopquiz - Dừng câu đố

🏆 /leaderboard - BXH 24h
📊 /stats - Điểm của bạn

💡 Nối từ dùng từ có nghĩa thực tế!
🎯 Quiz dùng Claude AI - độ chính xác cao!
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
    quiz_mode[chat_id] = True
    quiz_count[chat_id] = 1
    
    loading_msg = await update.message.reply_text("⏳ Đang tạo câu hỏi với Claude AI...")
    
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
        "du lịch": "✈️"
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
            
            loading_msg = await context.bot.send_message(chat_id, "⏳ Claude AI đang tạo câu hỏi mới...")
            
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
                "du lịch": "✈️"
            }
            
            emoji = topic_emojis.get(quiz.get("topic", ""), "❓")
            message = f"{emoji} **CÂU {quiz_count[chat_id]} - {quiz.get('topic', '').upper()}**\n\n{quiz['question']}"
            
            await loading_msg.edit_text(message, reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
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
            
            if is_finished and game_info["game"].score > 0:
                save_score(user.id, username, "noitu", game_info["game"].score)
                del active_games[chat_id]
        return
    
    if chat_id not in chat_history:
        chat_history[chat_id] = []
        
    chat_history[chat_id].append({"role": "user", "content": message})
    
    if len(chat_history[chat_id]) > 4:
        chat_history[chat_id] = chat_history[chat_id][-4:]
    
    messages = [
        {"role": "system", "content": "Bạn là Linh - trợ lý AI vui vẻ. Trả lời ngắn gọn, thân thiện."}
    ]
    messages.extend(chat_history[chat_id])
    
    response = await call_api(messages, max_tokens=300)
    
    if response:
        chat_history[chat_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("😅 Xin lỗi, mình đang gặp lỗi!")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("guessnumber", start_guess_number))
    application.add_handler(CommandHandler("noitu", start_noitu))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("stopquiz", stop_quiz))
    application.add_handler(CommandHandler("hint", hint_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot started with meaningful words & Claude quiz! 🎯")
    application.run_polling()

if __name__ == "__main__":
    main()
