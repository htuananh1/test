import logging
import random
import json
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import threading
import time
from github import Github
import base64
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_TOKEN = os.getenv('BOT_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO', 'htuananh1/Data-manager')
GITHUB_FILE_PATH = "bot_data.json"

FISH_TYPES = {
    "🦐 Tôm": {
        "value": 5, 
        "chance": 25, 
        "exp": 1,
        "multiplier_chance": 5,
        "multiplier_range": (2, 5)
    },
    "🐟 Cá nhỏ": {
        "value": 10, 
        "chance": 20, 
        "exp": 2,
        "multiplier_chance": 8,
        "multiplier_range": (2, 6)
    },
    "🐠 Cá vàng": {
        "value": 30, 
        "chance": 15, 
        "exp": 5,
        "multiplier_chance": 10,
        "multiplier_range": (2, 8)
    },
    "🐡 Cá nóc": {
        "value": 50, 
        "chance": 12, 
        "exp": 8,
        "multiplier_chance": 12,
        "multiplier_range": (3, 10)
    },
    "🦑 Mực": {
        "value": 80, 
        "chance": 10, 
        "exp": 12,
        "multiplier_chance": 15,
        "multiplier_range": (3, 12)
    },
    "🦈 Cá mập": {
        "value": 150, 
        "chance": 8, 
        "exp": 20,
        "multiplier_chance": 18,
        "multiplier_range": (4, 15)
    },
    "🐙 Bạch tuộc": {
        "value": 200, 
        "chance": 5, 
        "exp": 25,
        "multiplier_chance": 20,
        "multiplier_range": (5, 16)
    },
    "🐋 Cá voi": {
        "value": 500, 
        "chance": 3, 
        "exp": 50,
        "multiplier_chance": 25,
        "multiplier_range": (5, 18)
    },
    "🦞 Tôm hùm": {
        "value": 300, 
        "chance": 1.5, 
        "exp": 35,
        "multiplier_chance": 22,
        "multiplier_range": (4, 17)
    },
    "💎 Kho báu": {
        "value": 1000, 
        "chance": 0.5, 
        "exp": 100,
        "multiplier_chance": 30,
        "multiplier_range": (10, 20)
    }
}

FISHING_RODS = {
    "basic": {
        "name": "🎣 Cần câu cơ bản",
        "price": 0,
        "bonus": 0,
        "speed": 3.0,
        "rare_bonus": 1.0,
        "description": "Cần câu mặc định"
    },
    "bronze": {
        "name": "🥉 Cần câu đồng",
        "price": 500,
        "bonus": 10,
        "speed": 2.5,
        "rare_bonus": 1.2,
        "description": "+10% cơ hội | Nhanh hơn 0.5s | Cá hiếm x1.2"
    },
    "silver": {
        "name": "🥈 Cần câu bạc",
        "price": 1500,
        "bonus": 25,
        "speed": 2.0,
        "rare_bonus": 1.5,
        "description": "+25% cơ hội | Nhanh hơn 1s | Cá hiếm x1.5"
    },
    "gold": {
        "name": "🥇 Cần câu vàng",
        "price": 5000,
        "bonus": 50,
        "speed": 1.5,
        "rare_bonus": 2.0,
        "description": "+50% cơ hội | Nhanh hơn 1.5s | Cá hiếm x2"
    },
    "diamond": {
        "name": "💎 Cần câu kim cương",
        "price": 15000,
        "bonus": 100,
        "speed": 1.0,
        "rare_bonus": 3.0,
        "description": "x2 cơ hội | Siêu nhanh | Cá hiếm x3"
    },
    "legendary": {
        "name": "⚡ Cần câu huyền thoại",
        "price": 50000,
        "bonus": 200,
        "speed": 0.5,
        "rare_bonus": 5.0,
        "description": "x3 cơ hội | Tức thì | Cá hiếm x5"
    }
}

BAITS = {
    "worm": {
        "name": "🪱 Giun",
        "price": 5,
        "bonus": 5,
        "description": "+5% cơ hội câu được cá"
    },
    "shrimp": {
        "name": "🦐 Tôm nhỏ",
        "price": 15,
        "bonus": 15,
        "description": "+15% cơ hội câu được cá tốt"
    },
    "special": {
        "name": "✨ Mồi đặc biệt",
        "price": 50,
        "bonus": 30,
        "description": "+30% cơ hội câu được cá hiếm"
    },
    "golden": {
        "name": "🌟 Mồi vàng",
        "price": 100,
        "bonus": 50,
        "description": "+50% cơ hội & x2 nhân tiền"
    }
}

class DataManager:
    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.github = Github(GITHUB_TOKEN)
        self.repo = self.github.get_repo(GITHUB_REPO)
        self.load_from_github()
        self.start_auto_save()
        self.pending_saves = {}
    
    def load_from_github(self):
        try:
            file_content = self.repo.get_contents(GITHUB_FILE_PATH)
            self.data = json.loads(base64.b64decode(file_content.content).decode())
            logging.info("Loaded data from GitHub successfully")
        except Exception as e:
            logging.info(f"No existing data file or error: {e}")
            self.data = {}
    
    def save_to_github(self):
        with self.lock:
            try:
                json_data = json.dumps(self.data, indent=2, ensure_ascii=False)
                
                try:
                    file = self.repo.get_contents(GITHUB_FILE_PATH)
                    self.repo.update_file(
                        GITHUB_FILE_PATH,
                        f"Update bot data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        json_data,
                        file.sha
                    )
                except:
                    self.repo.create_file(
                        GITHUB_FILE_PATH,
                        f"Create bot data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        json_data
                    )
                
                logging.info("Saved data to GitHub successfully")
                return True
            except Exception as e:
                logging.error(f"Error saving to GitHub: {e}")
                return False
    
    def auto_save(self):
        while True:
            time.sleep(60)
            self.executor.submit(self.save_to_github)
    
    def start_auto_save(self):
        save_thread = threading.Thread(target=self.auto_save, daemon=True)
        save_thread.start()
    
    def get_user(self, user_id):
        user_id = str(user_id)
        with self.lock:
            if user_id not in self.data:
                self.data[user_id] = {
                    "username": "",
                    "coins": 100,
                    "exp": 0,
                    "level": 1,
                    "fishing_count": 0,
                    "win_count": 0,
                    "lose_count": 0,
                    "treasures_found": 0,
                    "total_multiplier": 0,
                    "best_multiplier": 0,
                    "inventory": {
                        "rod": "basic",
                        "baits": {"worm": 10, "shrimp": 0, "special": 0, "golden": 0},
                        "fish": {}
                    },
                    "daily_claimed": None,
                    "created_at": datetime.now().isoformat()
                }
            return self.data[user_id].copy()
    
    def update_user(self, user_id, data):
        user_id = str(user_id)
        with self.lock:
            self.data[user_id] = data
    
    def add_coins(self, user_id, amount):
        user_id = str(user_id)
        with self.lock:
            user = self.get_user(user_id)
            user["coins"] += amount
            self.data[user_id] = user
            return user["coins"]
    
    def add_exp(self, user_id, amount):
        user_id = str(user_id)
        with self.lock:
            user = self.get_user(user_id)
            user["exp"] += amount
            new_level = (user["exp"] // 100) + 1
            leveled_up = new_level > user["level"]
            if leveled_up:
                user["level"] = new_level
            self.data[user_id] = user
            return leveled_up

data_manager = DataManager()

def format_number(num):
    return "{:,}".format(num)

def get_level_title(level):
    titles = {
        1: "🐣 Người mới",
        5: "🎣 Thợ câu",
        10: "🐠 Ngư dân",
        20: "🦈 Thủy thủ",
        30: "⚓ Thuyền trưởng",
        50: "🏴‍☠️ Hải tặc",
        75: "🧜‍♂️ Vua biển cả",
        100: "🔱 Poseidon",
        150: "🌊 Thần đại dương",
        200: "⚡ Huyền thoại"
    }
    
    for min_level in sorted(titles.keys(), reverse=True):
        if level >= min_level:
            return titles[min_level]
    return titles[1]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    user = data_manager.get_user(user_id)
    user["username"] = user_name
    data_manager.update_user(user_id, user)
    
    welcome_text = f"""
🎮 **Chào mừng {user_name} đến với Fishing Game Bot!** 🎮

🎣 **Thông tin của bạn:**
├ 💰 Xu: {format_number(user['coins'])}
├ ⭐ Level: {user['level']} - {get_level_title(user['level'])}
├ 🎯 Kinh nghiệm: {user['exp']}
└ 🎣 Cần câu: {FISHING_RODS[user['inventory']['rod']]['name']}

📜 **Lệnh cơ bản:**
/menu - 📱 Menu chính
/fishing - 🎣 Câu cá
/inventory - 🎒 Kho đồ
/shop - 🛍️ Cửa hàng
/stats - 📊 Thống kê
/leaderboard - 🏆 BXH

💡 Cá có cơ hội nhân tiền x2-x20!
    """
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🎣 Câu Cá", callback_data='game_fishing'),
            InlineKeyboardButton("🎲 Chẵn Lẻ", callback_data='game_chanle')
        ],
        [
            InlineKeyboardButton("🗺️ Tìm Kho Báu", callback_data='game_treasure'),
            InlineKeyboardButton("🎒 Kho Đồ", callback_data='view_inventory')
        ],
        [
            InlineKeyboardButton("🛍️ Cửa Hàng", callback_data='open_shop'),
            InlineKeyboardButton("📊 Thống Kê", callback_data='view_stats')
        ],
        [
            InlineKeyboardButton("🏆 BXH", callback_data='leaderboard'),
            InlineKeyboardButton("🎁 Quà Hàng Ngày", callback_data='daily_reward')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    
    menu_text = f"""
🎮 **MENU CHÍNH** 🎮

👤 {user['username']} | Level {user['level']}
💰 {format_number(user['coins'])} xu | ⭐ {user['exp']} EXP
🎣 Cần: {FISHING_RODS[user['inventory']['rod']]['name']}

Chọn hoạt động:
    """
    
    await update.message.reply_text(menu_text, reply_markup=reply_markup, parse_mode='Markdown')

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    inv = user['inventory']
    
    total_fish = sum(inv['fish'].values()) if inv['fish'] else 0
    
    fish_list = ""
    if inv['fish']:
        for fish_name, count in sorted(inv['fish'].items(), key=lambda x: x[1], reverse=True)[:10]:
            fish_list += f"  {fish_name}: {count}\n"
    else:
        fish_list = "  Chưa có cá nào\n"
    
    inventory_text = f"""
🎒 **KHO ĐỒ CỦA BẠN** 🎒

**🎣 Cần câu:**
{FISHING_RODS[inv['rod']]['name']}
{FISHING_RODS[inv['rod']]['description']}

**🪱 Mồi câu:**
├ 🪱 Giun: {inv['baits']['worm']}
├ 🦐 Tôm: {inv['baits']['shrimp']}
├ ✨ Đặc biệt: {inv['baits']['special']}
└ 🌟 Vàng: {inv['baits'].get('golden', 0)}

**🐟 Cá đã câu:** (Tổng: {total_fish})
{fish_list}

**📈 Thống kê nhân tiền:**
├ Tổng nhân: x{user.get('total_multiplier', 0)}
└ Cao nhất: x{user.get('best_multiplier', 0)}
    """
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Cửa hàng", callback_data='open_shop')],
        [InlineKeyboardButton("💰 Bán cá", callback_data='sell_fish')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(inventory_text, reply_markup=reply_markup, parse_mode='Markdown')

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎣 Cần câu", callback_data='shop_rods')],
        [InlineKeyboardButton("🪱 Mồi câu", callback_data='shop_baits')],
        [InlineKeyboardButton("💎 Vật phẩm đặc biệt", callback_data='shop_special')],
        [InlineKeyboardButton("◀️ Quay lại", callback_data='back_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    shop_text = """
🛍️ **CỬA HÀNG** 🛍️

Chào mừng đến cửa hàng!
Chọn danh mục bạn muốn xem:
    """
    
    await update.message.reply_text(shop_text, reply_markup=reply_markup, parse_mode='Markdown')

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_users = sorted(data_manager.data.items(), 
                         key=lambda x: x[1]['coins'], 
                         reverse=True)[:10]
    
    text = "🏆 **BẢNG XẾP HẠNG TOP 10** 🏆\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, user_data) in enumerate(sorted_users, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} {user_data.get('username', 'User')} - {format_number(user_data['coins'])} xu (Lv.{user_data['level']})\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def fishing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    
    cost = 10
    if user["coins"] < cost:
        await update.message.reply_text(f"❌ Bạn không đủ xu! Cần {cost} xu để câu cá.")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"🪱 Giun ({user['inventory']['baits']['worm']})", 
                            callback_data='fish_bait_worm')],
        [InlineKeyboardButton(f"🦐 Tôm ({user['inventory']['baits']['shrimp']})", 
                            callback_data='fish_bait_shrimp')],
        [InlineKeyboardButton(f"✨ Đặc biệt ({user['inventory']['baits']['special']})", 
                            callback_data='fish_bait_special')],
        [InlineKeyboardButton(f"🌟 Vàng ({user['inventory']['baits'].get('golden', 0)})", 
                            callback_data='fish_bait_golden')],
        [InlineKeyboardButton("🎣 Không dùng mồi", callback_data='fish_bait_none')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    rod_info = FISHING_RODS[user['inventory']['rod']]
    await update.message.reply_text(
        f"🎣 **CHỌN MỒI CÂU**\nCần: {rod_info['name']}\nTốc độ: {rod_info['speed']}s\nChọn mồi:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def process_fishing(query, bait_type):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    
    data_manager.add_coins(user_id, -10)
    
    bonus = 0
    golden_multiplier = 1
    if bait_type != 'none':
        if bait_type in user['inventory']['baits'] and user['inventory']['baits'][bait_type] > 0:
            user['inventory']['baits'][bait_type] -= 1
            if bait_type == 'golden':
                bonus = 50
                golden_multiplier = 2
            else:
                bait_info = BAITS.get(bait_type)
                bonus = bait_info['bonus'] if bait_info else 0
    
    rod_info = FISHING_RODS[user['inventory']['rod']]
    rod_bonus = rod_info['bonus']
    total_bonus = bonus + rod_bonus
    rare_multiplier = rod_info['rare_bonus']
    
    await query.edit_message_text(f"🎣 Đang thả câu... (chờ {rod_info['speed']}s)")
    await asyncio.sleep(rod_info['speed'])
    
    rand = random.uniform(0, 100)
    cumulative = 0
    caught_fish = None
    
    for fish_name, fish_data in FISH_TYPES.items():
        if fish_name in ["🐋 Cá voi", "💎 Kho báu", "🦞 Tôm hùm"]:
            chance = fish_data["chance"] * (1 + total_bonus/100) * rare_multiplier
        else:
            chance = fish_data["chance"] * (1 + total_bonus/100)
        
        cumulative += chance
        if rand <= cumulative:
            caught_fish = fish_name
            base_reward = fish_data["value"]
            exp = fish_data["exp"]
            
            multiplier = 1
            if random.randint(1, 100) <= fish_data["multiplier_chance"]:
                min_mult, max_mult = fish_data["multiplier_range"]
                multiplier = random.randint(min_mult, max_mult)
                if golden_multiplier > 1:
                    multiplier *= golden_multiplier
            
            reward = base_reward * multiplier
            
            if user.get('best_multiplier', 0) < multiplier:
                user['best_multiplier'] = multiplier
            user['total_multiplier'] = user.get('total_multiplier', 0) + multiplier
            
            break
    
    if caught_fish:
        if caught_fish not in user['inventory']['fish']:
            user['inventory']['fish'][caught_fish] = 0
        user['inventory']['fish'][caught_fish] += 1
        
        data_manager.add_coins(user_id, reward)
        leveled_up = data_manager.add_exp(user_id, exp)
        
        user["fishing_count"] += 1
        user["win_count"] += 1
        
        result_text = f"""
🎉 **BẮT ĐƯỢC!**
{caught_fish}
💰 +{format_number(reward)} xu"""
        
        if multiplier > 1:
            result_text += f" (x{multiplier} 🔥)"
        
        result_text += f"""
⭐ +{exp} EXP
📦 Đã lưu vào kho

💰 Số dư: {format_number(user['coins'] + reward)} xu"""
        
        if leveled_up:
            result_text += f"\n\n🎊 **LEVEL UP! Bạn đã đạt level {user['level'] + 1}!**"
    else:
        user["fishing_count"] += 1
        result_text = f"😢 Không câu được gì!\n💰 Số dư: {format_number(user['coins'] - 10)} xu"
    
    data_manager.update_user(user_id, user)
    await query.edit_message_text(result_text, parse_mode='Markdown')

async def chanle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Chẵn (10 xu)", callback_data='chanle_chan_10'),
            InlineKeyboardButton("Lẻ (10 xu)", callback_data='chanle_le_10')
        ],
        [
            InlineKeyboardButton("Chẵn (50 xu)", callback_data='chanle_chan_50'),
            InlineKeyboardButton("Lẻ (50 xu)", callback_data='chanle_le_50')
        ],
        [
            InlineKeyboardButton("Chẵn (100 xu)", callback_data='chanle_chan_100'),
            InlineKeyboardButton("Lẻ (100 xu)", callback_data='chanle_le_100')
        ],
        [
            InlineKeyboardButton("Chẵn (500 xu)", callback_data='chanle_chan_500'),
            InlineKeyboardButton("Lẻ (500 xu)", callback_data='chanle_le_500')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎲 **TRÒ CHƠI CHẴN LẺ** 🎲\nChọn chẵn hoặc lẻ:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def treasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    
    cost = 20
    if user["coins"] < cost:
        await update.message.reply_text(f"❌ Bạn không đủ xu! Cần {cost} xu để tìm kho báu.")
        return
    
    keyboard = []
    for i in range(4):
        row = []
        for j in range(4):
            row.append(InlineKeyboardButton("📦", callback_data=f"treasure_{i}_{j}"))
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    treasure_pos = random.randint(0, 15)
    gold_positions = random.sample([i for i in range(16) if i != treasure_pos], 3)
    
    context.user_data['treasure_pos'] = treasure_pos
    context.user_data['gold_positions'] = gold_positions
    
    await update.message.reply_text(
        f"""🗺️ **TÌM KHO BÁU** 🗺️
Phí chơi: {cost} xu
Chọn 1 hộp để tìm kho báu!

💎 Kho báu = 200 xu
💰 Vàng = 50 xu
💩 Trống = 0 xu""",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    data_manager.add_coins(user_id, -cost)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    data = query.data
    
    if data == 'game_fishing':
        await fishing(query, context)
    
    elif data == 'game_chanle':
        await chanle(query, context)
    
    elif data == 'game_treasure':
        await treasure(query, context)
    
    elif data == 'view_inventory':
        await show_inventory(query)
    
    elif data == 'view_stats':
        await show_stats(query)
    
    elif data == 'open_shop':
        await show_shop(query)
    
    elif data == 'leaderboard':
        await show_leaderboard(query)
    
    elif data == 'daily_reward':
        await claim_daily(query)
    
    elif data.startswith('fish_bait_'):
        bait = data.replace('fish_bait_', '')
        await process_fishing(query, bait)
    
    elif data.startswith('chanle_'):
        parts = data.split('_')
        choice = parts[1]
        bet = int(parts[2])
        
        if user["coins"] < bet:
            await query.edit_message_text(f"❌ Bạn không đủ {bet} xu để cược!")
            return
        
        dice = random.randint(1, 6)
        is_even = dice % 2 == 0
        
        if (choice == 'chan' and is_even) or (choice == 'le' and not is_even):
            data_manager.add_coins(user_id, bet)
            data_manager.add_exp(user_id, 5)
            user["win_count"] += 1
            result = f"""🎉 **THẮNG!**
🎲 Xúc xắc: {dice}
💰 +{bet} xu
⭐ +5 EXP
💰 Số dư: {format_number(user['coins'] + bet)} xu"""
        else:
            data_manager.add_coins(user_id, -bet)
            user["lose_count"] += 1
            result = f"""😢 **THUA!**
🎲 Xúc xắc: {dice}
💰 -{bet} xu
💰 Số dư: {format_number(user['coins'] - bet)} xu"""
        
        data_manager.update_user(user_id, user)
        await query.edit_message_text(result, parse_mode='Markdown')
    
    elif data.startswith('treasure_'):
        parts = data.split('_')
        row = int(parts[1])
        col = int(parts[2])
        position = row * 4 + col
        
        treasure_pos = context.user_data.get('treasure_pos', -1)
        gold_positions = context.user_data.get('gold_positions', [])
        
        if position == treasure_pos:
            reward = 200
            data_manager.add_coins(user_id, reward)
            data_manager.add_exp(user_id, 20)
            user["treasures_found"] += 1
            user["win_count"] += 1
            result = f"""💎 **KHO BÁU!**
+{reward} xu
⭐ +20 EXP
💰 Số dư: {format_number(user['coins'] + reward - 20)} xu"""
        elif position in gold_positions:
            reward = 50
            data_manager.add_coins(user_id, reward)
            data_manager.add_exp(user_id, 10)
            result = f"""💰 **VÀNG!**
+{reward} xu
⭐ +10 EXP
💰 Số dư: {format_number(user['coins'] + reward - 20)} xu"""
        else:
            user["lose_count"] += 1
            result = f"""💩 **TRỐNG!**
Không có gì ở đây!
💰 Số dư: {format_number(user['coins'] - 20)} xu"""
        
        data_manager.update_user(user_id, user)
        await query.edit_message_text(result, parse_mode='Markdown')
    
    elif data == 'shop_rods':
        await show_rods_shop(query)
    
    elif data == 'shop_baits':
        await show_baits_shop(query)
    
    elif data.startswith('buy_rod_'):
        rod_id = data.replace('buy_rod_', '')
        await buy_rod(query, rod_id)
    
    elif data.startswith('buy_bait_'):
        parts = data.split('_')
        bait_type = parts[2]
        amount = int(parts[3])
        await buy_bait(query, bait_type, amount)
    
    elif data == 'sell_fish':
        await sell_all_fish(query)

async def show_shop(query):
    keyboard = [
        [InlineKeyboardButton("🎣 Cần câu", callback_data='shop_rods')],
        [InlineKeyboardButton("🪱 Mồi câu", callback_data='shop_baits')],
        [InlineKeyboardButton("◀️ Quay lại", callback_data='back_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🛍️ **CỬA HÀNG**\nChọn danh mục:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_rods_shop(query):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    current_rod = user['inventory']['rod']
    
    text = "🎣 **CỬA HÀNG CẦN CÂU**\n\n"
    keyboard = []
    
    for rod_id, rod_info in FISHING_RODS.items():
        if rod_id == current_rod:
            text += f"✅ {rod_info['name']} (Đang dùng)\n\n"
        else:
            text += f"{rod_info['name']}\n"
            text += f"💰 {format_number(rod_info['price'])} xu\n"
            text += f"📝 {rod_info['description']}\n\n"
            
            if rod_info['price'] <= user['coins'] and rod_id != current_rod:
                keyboard.append([InlineKeyboardButton(
                    f"Mua {rod_info['name']} ({format_number(rod_info['price'])} xu)",
                    callback_data=f'buy_rod_{rod_id}'
                )])
    
    keyboard.append([InlineKeyboardButton("◀️ Quay lại", callback_data='open_shop')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_baits_shop(query):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    
    text = "🪱 **CỬA HÀNG MỒI CÂU**\n\n"
    keyboard = []
    
    for bait_id, bait_info in BAITS.items():
        current_amount = user['inventory']['baits'].get(bait_id, 0)
        text += f"{bait_info['name']}\n"
        text += f"💰 {bait_info['price']} xu/cái\n"
        text += f"📝 {bait_info['description']}\n"
        text += f"📦 Đang có: {current_amount}\n\n"
        
        row = []
        for amount in [10, 50, 100]:
            total_price = bait_info['price'] * amount
            if total_price <= user['coins']:
                row.append(InlineKeyboardButton(
                    f"x{amount} ({format_number(total_price)} xu)",
                    callback_data=f'buy_bait_{bait_id}_{amount}'
                ))
        if row:
            keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("◀️ Quay lại", callback_data='open_shop')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def buy_rod(query, rod_id):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    rod_info = FISHING_RODS[rod_id]
    
    if user['coins'] < rod_info['price']:
        await query.edit_message_text("❌ Bạn không đủ xu!")
        return
    
    data_manager.add_coins(user_id, -rod_info['price'])
    user['inventory']['rod'] = rod_id
    data_manager.update_user(user_id, user)
    
    await query.edit_message_text(
        f"✅ **MUA THÀNH CÔNG!**\n"
        f"Bạn đã mua {rod_info['name']}\n"
        f"💰 Số dư: {format_number(user['coins'] - rod_info['price'])} xu",
        parse_mode='Markdown'
    )

async def buy_bait(query, bait_type, amount):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    bait_info = BAITS[bait_type]
    total_price = bait_info['price'] * amount
    
    if user['coins'] < total_price:
        await query.edit_message_text("❌ Bạn không đủ xu!")
        return
    
    data_manager.add_coins(user_id, -total_price)
    if bait_type not in user['inventory']['baits']:
        user['inventory']['baits'][bait_type] = 0
    user['inventory']['baits'][bait_type] += amount
    data_manager.update_user(user_id, user)
    
    await query.edit_message_text(
        f"✅ **MUA THÀNH CÔNG!**\n"
        f"Bạn đã mua {amount} {bait_info['name']}\n"
        f"💰 Số dư: {format_number(user['coins'] - total_price)} xu",
        parse_mode='Markdown'
    )

async def sell_all_fish(query):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    
    total_value = 0
    total_count = 0
    
    if user['inventory']['fish']:
        for fish_name, count in user['inventory']['fish'].items():
            for fish_type, fish_data in FISH_TYPES.items():
                if fish_type == fish_name:
                    total_value += fish_data['value'] * count * 0.7
                    total_count += count
                    break
        
        user['inventory']['fish'] = {}
        data_manager.add_coins(user_id, int(total_value))
        data_manager.update_user(user_id, user)
        
        await query.edit_message_text(
            f"💰 **BÁN THÀNH CÔNG!**\n"
            f"Đã bán {total_count} con cá\n"
            f"Thu được: {format_number(int(total_value))} xu\n"
            f"💰 Số dư: {format_number(user['coins'] + int(total_value))} xu",
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text("❌ Bạn không có cá để bán!")

async def show_inventory(query):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    inv = user['inventory']
    
    total_fish = sum(inv['fish'].values()) if inv['fish'] else 0
    
    fish_list = ""
    if inv['fish']:
        for fish_name, count in sorted(inv['fish'].items(), key=lambda x: x[1], reverse=True)[:5]:
            fish_list += f"  {fish_name}: {count}\n"
    else:
        fish_list = "  Chưa có cá nào\n"
    
    text = f"""
🎒 **KHO ĐỒ**

🎣 Cần: {FISHING_RODS[inv['rod']]['name']}
🪱 Mồi: Giun x{inv['baits']['worm']} | Tôm x{inv['baits']['shrimp']} | ĐB x{inv['baits']['special']} | Vàng x{inv['baits'].get('golden', 0)}

🐟 Cá ({total_fish} con):
{fish_list}

📈 Nhân cao nhất: x{user.get('best_multiplier', 0)}
    """
    
    keyboard = [
        [InlineKeyboardButton("💰 Bán tất cả cá", callback_data='sell_fish')],
        [InlineKeyboardButton("◀️ Quay lại", callback_data='back_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_stats(query):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    
    win_rate = (user['win_count'] / (user['win_count'] + user['lose_count']) * 100) if (user['win_count'] + user['lose_count']) > 0 else 0
    
    text = f"""
📊 **THỐNG KÊ**

👤 {user['username']}
🏆 Level {user['level']} - {get_level_title(user['level'])}
⭐ {user['exp']} EXP
💰 {format_number(user['coins'])} xu

📈 **Thành tích:**
🎣 Câu cá: {user['fishing_count']} lần
✅ Thắng: {user['win_count']} lần
❌ Thua: {user['lose_count']} lần
📊 Tỷ lệ thắng: {win_rate:.1f}%
💎 Kho báu: {user['treasures_found']} lần
🔥 Tổng nhân: x{user.get('total_multiplier', 0)}
⚡ Nhân cao nhất: x{user.get('best_multiplier', 0)}
    """
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def show_leaderboard(query):
    sorted_users = sorted(data_manager.data.items(), 
                         key=lambda x: x[1]['coins'], 
                         reverse=True)[:10]
    
    text = "🏆 **BẢNG XẾP HẠNG TOP 10** 🏆\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, user_data) in enumerate(sorted_users, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} {user_data.get('username', 'User')} - {format_number(user_data['coins'])} xu (Lv.{user_data['level']})\n"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def claim_daily(query):
    user_id = query.from_user.id
    user = data_manager.get_user(user_id)
    
    last_claim = user.get('daily_claimed')
    if last_claim:
        last_date = datetime.fromisoformat(last_claim)
        if (datetime.now() - last_date).days < 1:
            hours_left = 24 - (datetime.now() - last_date).total_seconds() / 3600
            await query.edit_message_text(
                f"⏰ Bạn đã nhận quà hôm nay!\nQuay lại sau {hours_left:.1f} giờ"
            )
            return
    
    reward = random.randint(50, 200)
    bonus_baits = random.randint(5, 15)
    
    data_manager.add_coins(user_id, reward)
    user['inventory']['baits']['worm'] += bonus_baits
    user['daily_claimed'] = datetime.now().isoformat()
    data_manager.update_user(user_id, user)
    
    await query.edit_message_text(
        f"🎁 **PHẦN THƯỞNG HÀNG NGÀY!**\n"
        f"💰 +{reward} xu\n"
        f"🪱 +{bonus_baits} mồi giun\n"
        f"💰 Số dư: {format_number(user['coins'] + reward)} xu",
        parse_mode='Markdown'
    )

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("fishing", fishing))
    application.add_handler(CommandHandler("chanle", chanle))
    application.add_handler(CommandHandler("treasure", treasure))
    application.add_handler(CommandHandler("inventory", inventory))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("🤖 Bot đang chạy...")
    print("📊 Dữ liệu tự động lưu GitHub mỗi 60 giây")
    print("👥 Hỗ trợ nhiều người chơi cùng lúc")
    application.run_polling()

if __name__ == '__main__':
    main()
