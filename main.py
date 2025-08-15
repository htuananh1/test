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
quiz_count: Dict[int, int] = {}  # Đếm số câu đã trả lời
used_words_global: set = set()

SIMPLE_WORDS = [
    "trong", "sạch", "đẹp", "tươi", "vui", "mạnh", "nhanh", "xinh", 
    "sáng", "tối", "cao", "thấp", "to", "nhỏ", "dài", "ngắn",
    "nóng", "lạnh", "cứng", "mềm", "đen", "trắng", "xanh", "đỏ",
    "già", "trẻ", "mới", "cũ", "tốt", "xấu", "khó", "dễ",
    "nặng", "nhẹ", "rộng", "hẹp", "dày", "mỏng", "xa", "gần",
    "sâu", "cạn", "đông", "tây", "nam", "bắc", "trong", "ngoài"
]

# Các chủ đề quiz
QUIZ_TOPICS = ["lịch sử", "địa lý", "ẩm thực", "văn hóa", "du lịch"]

def cleanup_memory():
    global chat_history
    for chat_id in list(chat_history.keys()):
        if len(chat_history[chat_id]) > 4:
            chat_history[chat_id] = chat_history[chat_id][-4:]
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
        
        available_starts = []
        for w1 in SIMPLE_WORDS:
            for w2 in SIMPLE_WORDS:
                if w1 != w2:
                    compound = f"{w1} {w2}"
                    if compound not in used_words_global:
                        available_starts.append(compound)
        
        if not available_starts:
            used_words_global.clear()
            available_starts = [f"{w1} {w2}" for w1 in SIMPLE_WORDS for w2 in SIMPLE_WORDS if w1 != w2]
        
        self.current_word = random.choice(available_starts)
        self.history = [self.current_word]
        used_words_global.add(self.current_word)
        
        return f"""🎮 **Nối Từ với Linh!**

Luật: Nối từ ghép 2 từ tiếng Việt
VD: trong sạch → sạch sẽ

🎯 **{self.current_word}**
Nối với '{self.current_word.split()[1]}' | Gõ 'thua' kết thúc"""
        
    def play_word(self, word: str) -> Tuple[bool, str]:
        global used_words_global
        word = word.lower().strip()
        
        if word == "thua":
            return True, f"📊 Điểm: {self.score} | {len(self.history)} từ"
        
        parts = word.split()
        if len(parts) != 2:
            return False, "❌ Phải 2 từ ghép!"
        
        last_word = self.current_word.split()[1]
        if parts[0] != last_word:
            return False, f"❌ Phải bắt đầu '{last_word}'"
            
        if word in self.history or word in used_words_global:
            return False, "❌ Từ đã dùng rồi!"
            
        self.history.append(word)
        used_words_global.add(word)
        self.current_word = word
        self.player_words += 1
        self.score += 100
        
        possible = []
        for w in SIMPLE_WORDS:
            if w != parts[1]:
                compound = f"{parts[1]} {w}"
                if compound not in self.history and compound not in used_words_global:
                    possible.append(compound)
        
        if possible:
            bot_word = random.choice(possible[:10])
            self.history.append(bot_word)
            used_words_global.add(bot_word)
            self.current_word = bot_word
            self.bot_words += 1
            return False, f"✅ +100đ\n🤖 Linh: **{bot_word}**\n📊 {self.score}đ | Nối '{bot_word.split()[1]}'"
        else:
            self.score += 500
            return True, f"🎉 **THẮNG!** +500đ\n📊 Tổng: {self.score} điểm"

async def call_qwen_api(messages: List[dict], max_tokens: int = 400) -> str:
    try:
        headers = {
            "Authorization": f"Bearer {VERCEL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": CHAT_MODEL,
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
            return "Lỗi API!"
            
    except Exception as e:
        logger.error(f"API error: {e}")
        return "Lỗi kết nối!"

async def generate_quiz() -> dict:
    """Tạo quiz đa dạng về Việt Nam"""
    topic = random.choice(QUIZ_TOPICS)
    
    topic_prompts = {
        "lịch sử": "Tạo câu hỏi về lịch sử Việt Nam (vua chúa, triều đại, chiến tranh, sự kiện)",
        "địa lý": "Tạo câu hỏi về địa lý Việt Nam (tỉnh thành, sông núi, biển đảo, địa danh)",
        "ẩm thực": "Tạo câu hỏi về ẩm thực Việt Nam (món ăn, đặc sản, nguyên liệu, vùng miền)",
        "văn hóa": "Tạo câu hỏi về văn hóa Việt Nam (lễ hội, phong tục, trang phục, nghệ thuật)",
        "du lịch": "Tạo câu hỏi về du lịch Việt Nam (điểm đến, di tích, danh lam thắng cảnh)"
    }
    
    prompt = f"""{topic_prompts[topic]}

Format CHÍNH XÁC:
Câu hỏi: [câu hỏi]
A. [đáp án]
B. [đáp án]  
C. [đáp án]
D. [đáp án]
Đáp án: [A/B/C/D]
Giải thích: [ngắn gọn]"""

    messages = [
        {"role": "system", "content": f"Tạo câu hỏi về {topic} Việt Nam. Trả lời đúng format."},
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = await call_qwen_api(messages, 250)
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
            return quiz
        else:
            # Fallback quiz theo chủ đề
            fallback_quizzes = {
                "lịch sử": {
                    "question": "Thủ đô của Việt Nam được dời về Thăng Long năm nào?",
                    "options": ["A. 1009", "B. 1010", "C. 1011", "D. 1012"],
                    "correct": "B",
                    "explanation": "Năm 1010, Lý Thái Tổ dời đô về Thăng Long",
                    "topic": "lịch sử"
                },
                "địa lý": {
                    "question": "Đỉnh núi cao nhất Việt Nam là gì?",
                    "options": ["A. Phan Xi Păng", "B. Bà Đen", "C. Bà Nà", "D. Langbiang"],
                    "correct": "A",
                    "explanation": "Phan Xi Păng cao 3.143m, ở Lào Cai",
                    "topic": "địa lý"
                },
                "ẩm thực": {
                    "question": "Phở có nguồn gốc từ vùng nào?",
                    "options": ["A. Hà Nội", "B. Nam Định", "C. Hải Phòng", "D. Ninh Bình"],
                    "correct": "B",
                    "explanation": "Phở có nguồn gốc từ Nam Định đầu thế kỷ 20",
                    "topic": "ẩm thực"
                }
            }
            return fallback_quizzes.get(topic, fallback_quizzes["lịch sử"])
            
    except Exception as e:
        logger.error(f"Generate quiz error: {e}")
        return {
            "question": "Việt Nam có bao nhiêu tỉnh thành?",
            "options": ["A. 61", "B. 62", "C. 63", "D. 64"],
            "correct": "C",
            "explanation": "Việt Nam có 63 tỉnh thành",
            "topic": "địa lý"
        }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
👋 **Xin chào! Mình là Linh!**

🎮 **Game:**
/guessnumber - Đoán số
/noitu - Nối từ (không lặp)
/quiz - Câu đố về Việt Nam
/stopquiz - Dừng câu đố

🏆 /leaderboard - BXH 24h
📊 /stats - Điểm của bạn

📚 Quiz đa dạng: Lịch sử, Địa lý, Ẩm thực, Văn hóa, Du lịch!
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
    
    quiz = await generate_quiz()
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
    
    await update.message.reply_text(message, reply_markup=reply_markup)

async def stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    total_questions = quiz_count.get(chat_id, 0) - 1
    
    if chat_id in quiz_mode:
        del quiz_mode[chat_id]
    if chat_id in quiz_sessions:
        del quiz_sessions[chat_id]
    if chat_id in quiz_count:
        del quiz_count[chat_id]
        
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
                
            await query.message.edit_text(f"✅ Đã dừng câu đố!\n📊 Bạn đã trả lời {total_questions} câu")
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
        
        # Hiển thị kết quả
        await query.message.edit_text(result)
        
        # Tạo câu mới nếu còn quiz mode
        if chat_id in quiz_mode:
            await asyncio.sleep(1.5)
            
            # Tăng số câu
            quiz_count[chat_id] = quiz_count.get(chat_id, 1) + 1
            
            quiz = await generate_quiz()
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
            
            await context.bot.send_message(chat_id, message, reply_markup=reply_markup)

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
    
    # Chat AI với Qwen
    if chat_id not in chat_history:
        chat_history[chat_id] = []
        
    chat_history[chat_id].append({"role": "user", "content": message})
    
    if len(chat_history[chat_id]) > 4:
        chat_history[chat_id] = chat_history[chat_id][-4:]
    
    messages = [
        {"role": "system", "content": "Bạn là Linh - trợ lý AI vui vẻ. Trả lời ngắn gọn, thân thiện."}
    ]
    messages.extend(chat_history[chat_id])
    
    response = await call_qwen_api(messages, 300)
    chat_history[chat_id].append({"role": "assistant", "content": response})
    
    await update.message.reply_text(response)

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
    
    logger.info("Bot started with diverse Vietnam quiz! 🇻🇳")
    application.run_polling()

if __name__ == "__main__":
    main()
