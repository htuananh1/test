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
import psutil
import gc

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_TOKEN = os.getenv('BOT_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO', 'htuananh1/Data-manager')
GITHUB_FILE_PATH = "bot_data.json"
LOCAL_BACKUP_FILE = "local_backup.json"

# Hiệu ứng đặc biệt cho cá
FISH_EFFECTS = {
    "bronze": {
        "name": "🥉 Đồng",
        "multiplier": 3,
        "chance": 5,
        "color": "bronze"
    },
    "silver": {
        "name": "🥈 Bạc",
        "multiplier": 7,
        "chance": 2,
        "color": "silver"
    },
    "gold": {
        "name": "🥇 Vàng",
        "multiplier": 15,
        "chance": 0.8,
        "color": "gold"
    },
    "rainbow": {
        "name": "🌈 Cầu vồng",
        "multiplier": 30,
        "chance": 0.3,
        "color": "rainbow"
    },
    "zombie": {
        "name": "🧟 Zombie",
        "multiplier": 50,
        "chance": 0.1,
        "color": "zombie"
    },
    "legendary": {
        "name": "⚡ Huyền thoại",
        "multiplier": 100,
        "chance": 0.05,
        "color": "legendary"
    },
    "mythic": {
        "name": "🔮 Thần thoại",
        "multiplier": 200,
        "chance": 0.01,
        "color": "mythic"
    }
}

FISH_TYPES = {
    # Common (15-25%)
    "🍤 Tép": {
        "value": 2,
        "chance": 25,
        "exp": 1,
        "effect_chance": 5,
        "rarity": "common"
    },
    "🦐 Tôm": {
        "value": 5, 
        "chance": 22, 
        "exp": 1,
        "effect_chance": 6,
        "rarity": "common"
    },
    "🐟 Cá nhỏ": {
        "value": 10, 
        "chance": 20, 
        "exp": 2,
        "effect_chance": 7,
        "rarity": "common"
    },
    "🐠 Cá vàng": {
        "value": 30, 
        "chance": 18, 
        "exp": 5,
        "effect_chance": 8,
        "rarity": "common"
    },
    "🦀 Cua nhỏ": {
        "value": 25,
        "chance": 16,
        "exp": 4,
        "effect_chance": 8,
        "rarity": "common"
    },
    
    # Uncommon (8-15%)
    "🐡 Cá nóc": {
        "value": 50, 
        "chance": 12, 
        "exp": 8,
        "effect_chance": 10,
        "rarity": "uncommon"
    },
    "🦀 Cua lớn": {
        "value": 60,
        "chance": 10,
        "exp": 10,
        "effect_chance": 12,
        "rarity": "uncommon"
    },
    "🦑 Mực": {
        "value": 80, 
        "chance": 8, 
        "exp": 12,
        "effect_chance": 14,
        "rarity": "uncommon"
    },
    "🐚 Sò điệp": {
        "value": 70,
        "chance": 9,
        "exp": 11,
        "effect_chance": 13,
        "rarity": "uncommon"
    },
    "🦐 Tôm hùm nhỏ": {
        "value": 90,
        "chance": 7,
        "exp": 13,
        "effect_chance": 15,
        "rarity": "uncommon"
    },
    
    # Rare (2-6%)
    "🦈 Cá mập nhỏ": {
        "value": 150,
        "chance": 5,
        "exp": 20,
        "effect_chance": 18,
        "rarity": "rare"
    },
    "🐙 Bạch tuộc": {
        "value": 200, 
        "chance": 4, 
        "exp": 25,
        "effect_chance": 20,
        "rarity": "rare"
    },
    "🦈 Cá mập lớn": {
        "value": 300,
        "chance": 3,
        "exp": 30,
        "effect_chance": 22,
        "rarity": "rare"
    },
    "🐢 Rùa biển": {
        "value": 400,
        "chance": 2.5,
        "exp": 35,
        "effect_chance": 24,
        "rarity": "rare"
    },
    "🦞 Tôm hùm": {
        "value": 500, 
        "chance": 2, 
        "exp": 40,
        "effect_chance": 26,
        "rarity": "rare"
    },
    
    # Epic (0.5-2%)
    "🐊 Cá sấu": {
        "value": 800,
        "chance": 1.5,
        "exp": 50,
        "effect_chance": 30,
        "rarity": "epic"
    },
    "🐋 Cá voi": {
        "value": 1000, 
        "chance": 1, 
        "exp": 60,
        "effect_chance": 32,
        "rarity": "epic"
    },
    "🦭 Hải cẩu": {
        "value": 900,
        "chance": 0.8,
        "exp": 55,
        "effect_chance": 34,
        "rarity": "epic"
    },
    "⚡ Cá điện": {
        "value": 1200,
        "chance": 0.6,
        "exp": 70,
        "effect_chance": 36,
        "rarity": "epic"
    },
    "🌟 Cá thần": {
        "value": 1500,
        "chance": 0.5,
        "exp": 80,
        "effect_chance": 38,
        "rarity": "epic"
    },
    
    # Legendary (0.1-0.5%)
    "🐉 Rồng biển": {
        "value": 2500,
        "chance": 0.4,
        "exp": 100,
        "effect_chance": 40,
        "rarity": "legendary"
    },
    "💎 Kho báu": {
        "value": 3000, 
        "chance": 0.3, 
        "exp": 120,
        "effect_chance": 42,
        "rarity": "legendary"
    },
    "👑 Vua đại dương": {
        "value": 5000,
        "chance": 0.2,
        "exp": 150,
        "effect_chance": 45,
        "rarity": "legendary"
    },
    "🔱 Thủy thần": {
        "value": 6000,
        "chance": 0.15,
        "exp": 180,
        "effect_chance": 48,
        "rarity": "legendary"
    },
    "🌊 Hải vương": {
        "value": 7000,
        "chance": 0.1,
        "exp": 200,
        "effect_chance": 50,
        "rarity": "legendary"
    },
    
    # Mythic (0.01-0.1%)
    "🦄 Kỳ lân biển": {
        "value": 10000,
        "chance": 0.08,
        "exp": 300,
        "effect_chance": 55,
        "rarity": "mythic"
    },
    "🐲 Long vương": {
        "value": 15000,
        "chance": 0.05,
        "exp": 400,
        "effect_chance": 60,
        "rarity": "mythic"
    },
    "☄️ Thiên thạch": {
        "value": 20000,
        "chance": 0.03,
        "exp": 500,
        "effect_chance": 65,
        "rarity": "mythic"
    },
    "🌌 Vũ trụ": {
        "value": 25000,
        "chance": 0.02,
        "exp": 600,
        "effect_chance": 70,
        "rarity": "mythic"
    },
    "✨ Thần thánh": {
        "value": 30000,
        "chance": 0.01,
        "exp": 700,
        "effect_chance": 75,
        "rarity": "mythic"
    },
    
    # Secret (0.001-0.01%)
    "🎭 Bí ẩn": {
        "value": 50000,
        "chance": 0.008,
        "exp": 1000,
        "effect_chance": 80,
        "rarity": "secret"
    },
    "🗿 Cổ đại": {
        "value": 75000,
        "chance": 0.005,
        "exp": 1500,
        "effect_chance": 85,
        "rarity": "secret"
    },
    "🛸 Ngoài hành tinh": {
        "value": 100000,
        "chance": 0.003,
        "exp": 2000,
        "effect_chance": 90,
        "rarity": "secret"
    },
    "🔮 Hư không": {
        "value": 150000,
        "chance": 0.002,
        "exp": 3000,
        "effect_chance": 95,
        "rarity": "secret"
    },
    "⭐ Vĩnh hằng": {
        "value": 500000,
        "chance": 0.001,
        "exp": 5000,
        "effect_chance": 99,
        "rarity": "secret"
    }
}

FISHING_RODS = {
    "1": {
        "id": "basic",
        "name": "🎣 Cần câu cơ bản",
        "price": 0,
        "speed": 3.0,
        "auto_speed": 4.0,
        "common_bonus": 1.0,
        "rare_bonus": 0.5,
        "epic_bonus": 0.1,
        "legendary_bonus": 0.01,
        "mythic_bonus": 0.001,
        "secret_bonus": 0.0001,
        "description": "Cần mặc định - Cá hiếm rất khó"
    },
    "2": {
        "id": "bamboo",
        "name": "🎋 Cần tre",
        "price": 100,
        "speed": 2.8,
        "auto_speed": 3.8,
        "common_bonus": 1.1,
        "rare_bonus": 0.6,
        "epic_bonus": 0.15,
        "legendary_bonus": 0.02,
        "mythic_bonus": 0.002,
        "secret_bonus": 0.0002,
        "description": "Nhẹ hơn - Tăng nhẹ tỷ lệ"
    },
    "3": {
        "id": "wooden",
        "name": "🪵 Cần gỗ",
        "price": 500,
        "speed": 2.5,
        "auto_speed": 3.5,
        "common_bonus": 1.2,
        "rare_bonus": 0.8,
        "epic_bonus": 0.2,
        "legendary_bonus": 0.05,
        "mythic_bonus": 0.005,
        "secret_bonus": 0.0005,
        "description": "Cần gỗ chắc - Cá thường tốt"
    },
    "4": {
        "id": "bronze",
        "name": "🥉 Cần đồng",
        "price": 1500,
        "speed": 2.3,
        "auto_speed": 3.3,
        "common_bonus": 1.3,
        "rare_bonus": 1.0,
        "epic_bonus": 0.3,
        "legendary_bonus": 0.08,
        "mythic_bonus": 0.008,
        "secret_bonus": 0.0008,
        "description": "Kim loại đầu - Cân bằng"
    },
    "5": {
        "id": "iron",
        "name": "⚙️ Cần sắt",
        "price": 5000,
        "speed": 2.0,
        "auto_speed": 3.0,
        "common_bonus": 1.4,
        "rare_bonus": 1.5,
        "epic_bonus": 0.5,
        "legendary_bonus": 0.15,
        "mythic_bonus": 0.015,
        "secret_bonus": 0.001,
        "description": "Cứng cáp - Cá uncommon tốt"
    },
    "6": {
        "id": "silver",
        "name": "🥈 Cần bạc",
        "price": 15000,
        "speed": 1.8,
        "auto_speed": 2.8,
        "common_bonus": 1.5,
        "rare_bonus": 2.0,
        "epic_bonus": 0.8,
        "legendary_bonus": 0.25,
        "mythic_bonus": 0.025,
        "secret_bonus": 0.0015,
        "description": "Quý kim - Cá rare xuất hiện"
    },
    "7": {
        "id": "gold",
        "name": "🥇 Cần vàng",
        "price": 50000,
        "speed": 1.5,
        "auto_speed": 2.5,
        "common_bonus": 1.6,
        "rare_bonus": 3.0,
        "epic_bonus": 1.5,
        "legendary_bonus": 0.5,
        "mythic_bonus": 0.05,
        "secret_bonus": 0.002,
        "description": "Cao cấp - Cá rare thường xuyên"
    },
    "8": {
        "id": "platinum",
        "name": "💍 Cần bạch kim",
        "price": 150000,
        "speed": 1.3,
        "auto_speed": 2.3,
        "common_bonus": 1.7,
        "rare_bonus": 4.0,
        "epic_bonus": 2.5,
        "legendary_bonus": 1.0,
        "mythic_bonus": 0.1,
        "secret_bonus": 0.003,
        "description": "Siêu quý - Epic có thể câu"
    },
    "9": {
        "id": "crystal",
        "name": "💎 Cần pha lê",
        "price": 500000,
        "speed": 1.0,
        "auto_speed": 2.0,
        "common_bonus": 1.8,
        "rare_bonus": 5.0,
        "epic_bonus": 4.0,
        "legendary_bonus": 2.0,
        "mythic_bonus": 0.2,
        "secret_bonus": 0.005,
        "description": "Tinh thể - Epic dễ dàng"
    },
    "10": {
        "id": "diamond",
        "name": "💠 Cần kim cương",
        "price": 1500000,
        "speed": 0.8,
        "auto_speed": 1.8,
        "common_bonus": 2.0,
        "rare_bonus": 6.0,
        "epic_bonus": 6.0,
        "legendary_bonus": 3.5,
        "mythic_bonus": 0.5,
        "secret_bonus": 0.008,
        "description": "Cứng nhất - Legendary xuất hiện"
    },
    "11": {
        "id": "obsidian",
        "name": "🗿 Cần hắc diệu thạch",
        "price": 5000000,
        "speed": 0.6,
        "auto_speed": 1.5,
        "common_bonus": 2.2,
        "rare_bonus": 8.0,
        "epic_bonus": 10.0,
        "legendary_bonus": 6.0,
        "mythic_bonus": 1.0,
        "secret_bonus": 0.01,
        "description": "Cổ đại - Legendary thường"
    },
    "12": {
        "id": "mythril",
        "name": "⚔️ Cần mythril",
        "price": 15000000,
        "speed": 0.5,
        "auto_speed": 1.3,
        "common_bonus": 2.5,
        "rare_bonus": 10.0,
        "epic_bonus": 15.0,
        "legendary_bonus": 10.0,
        "mythic_bonus": 2.0,
        "secret_bonus": 0.02,
        "description": "Huyền thoại - Mythic có thể"
    },
    "13": {
        "id": "celestial",
        "name": "✨ Cần thiên thần",
        "price": 50000000,
        "speed": 0.4,
        "auto_speed": 1.0,
        "common_bonus": 3.0,
        "rare_bonus": 15.0,
        "epic_bonus": 25.0,
        "legendary_bonus": 20.0,
        "mythic_bonus": 5.0,
        "secret_bonus": 0.05,
        "description": "Thiên giới - Mythic dễ dàng"
    },
    "14": {
        "id": "cosmic",
        "name": "🌌 Cần vũ trụ",
        "price": 150000000,
        "speed": 0.3,
        "auto_speed": 0.8,
        "common_bonus": 3.5,
        "rare_bonus": 20.0,
        "epic_bonus": 40.0,
        "legendary_bonus": 35.0,
        "mythic_bonus": 10.0,
        "secret_bonus": 0.1,
        "description": "Vũ trụ - Secret xuất hiện"
    },
    "15": {
        "id": "eternal",
        "name": "♾️ Cần vĩnh hằng",
        "price": 500000000,
        "speed": 0.2,
        "auto_speed": 0.5,
        "common_bonus": 5.0,
        "rare_bonus": 30.0,
        "epic_bonus": 60.0,
        "legendary_bonus": 50.0,
        "mythic_bonus": 20.0,
        "secret_bonus": 0.5,
        "description": "Bất tử - Secret thường xuyên"
    },
    "16": {
        "id": "omnipotent",
        "name": "🔮 Cần toàn năng",
        "price": 1000000000,
        "speed": 0.1,
        "auto_speed": 0.3,
        "common_bonus": 10.0,
        "rare_bonus": 50.0,
        "epic_bonus": 100.0,
        "legendary_bonus": 100.0,
        "mythic_bonus": 50.0,
        "secret_bonus": 1.0,
        "description": "Tối thượng - Mọi cá đều dễ"
    }
}

class LocalStorage:
    """Local storage for backup"""
    @staticmethod
    def save_local(data):
        try:
            with open(LOCAL_BACKUP_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logging.info("Saved to local backup")
        except Exception as e:
            logging.error(f"Error saving local backup: {e}")
    
    @staticmethod
    def load_local():
        try:
            with open(LOCAL_BACKUP_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

class ResourceMonitor:
    @staticmethod
    def get_system_stats():
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        return {
            "cpu": cpu_percent,
            "ram": memory.percent,
            "ram_used": memory.used / (1024**3),
            "ram_total": memory.total / (1024**3)
        }
    
    @staticmethod
    def check_resources():
        stats = ResourceMonitor.get_system_stats()
        if stats["cpu"] > 80:
            gc.collect()
            return False
        if stats["ram"] > 85:
            gc.collect()
            return False
        return True

class DataManager:
    def __init__(self):
        self.github = Github(GITHUB_TOKEN)
        self.repo = self.github.get_repo(GITHUB_REPO)
        self.auto_fishing_tasks = {}
        self.save_queue = []
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.start_auto_save()
    
    def load_user_from_github(self, user_id):
        """Load user data directly from GitHub"""
        try:
            file_content = self.repo.get_contents(GITHUB_FILE_PATH)
            content_str = base64.b64decode(file_content.content).decode()
            lines = content_str.strip().split('\n')
            
            for line in lines:
                if line.strip():
                    try:
                        user_data = json.loads(line)
                        if user_data.get('user_id') == str(user_id):
                            return user_data
                    except:
                        pass
        except Exception as e:
            logging.error(f"Error loading user from GitHub: {e}")
            # Try local backup
            local_data = LocalStorage.load_local()
            if str(user_id) in local_data:
                return local_data[str(user_id)]
        
        return self.create_new_user(str(user_id))
    
    def create_new_user(self, user_id):
        """Create new user data"""
        return {
            "user_id": str(user_id),
            "username": "",
            "coins": 100,
            "exp": 0,
            "level": 1,
            "fishing_count": 0,
            "win_count": 0,
            "lose_count": 0,
            "treasures_found": 0,
            "total_effects": {},
            "best_multiplier": 0,
            "owned_rods": ["1"],  # Start with basic rod
            "inventory": {
                "rod": "1",
                "fish": {}
            },
            "daily_claimed": None,
            "created_at": datetime.now().isoformat()
        }
    
    def save_user_to_github(self, user_data):
        """Save single user to GitHub"""
        with self.lock:
            self.save_queue.append(user_data)
    
    def batch_save_to_github(self):
        """Batch save all queued users"""
        if not self.save_queue or not ResourceMonitor.check_resources():
            return
        
        with self.lock:
            if not self.save_queue:
                return
            
            users_to_save = self.save_queue.copy()
            self.save_queue.clear()
        
        try:
            all_users = {}
            try:
                file_content = self.repo.get_contents(GITHUB_FILE_PATH)
                content_str = base64.b64decode(file_content.content).decode()
                lines = content_str.strip().split('\n')
                
                for line in lines:
                    if line.strip():
                        try:
                            user_data = json.loads(line)
                            if 'user_id' in user_data:
                                all_users[user_data['user_id']] = user_data
                        except:
                            pass
            except:
                pass
            
            for user_data in users_to_save:
                all_users[user_data['user_id']] = user_data
            
            # Save to local backup
            LocalStorage.save_local(all_users)
            
            lines = []
            for user_id, data in all_users.items():
                data['user_id'] = user_id
                lines.append(json.dumps(data, ensure_ascii=False))
            
            content = '\n'.join(lines)
            
            try:
                file = self.repo.get_contents(GITHUB_FILE_PATH)
                self.repo.update_file(
                    GITHUB_FILE_PATH,
                    f"Update bot data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content,
                    file.sha
                )
            except:
                self.repo.create_file(
                    GITHUB_FILE_PATH,
                    f"Create bot data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content
                )
            
            logging.info(f"Saved {len(users_to_save)} users to GitHub")
        except Exception as e:
            logging.error(f"Error batch saving to GitHub: {e}")
    
    def auto_save(self):
        """Auto save every 30 seconds"""
        while True:
            time.sleep(30)
            if self.save_queue:
                self.executor.submit(self.batch_save_to_github)
    
    def start_auto_save(self):
        save_thread = threading.Thread(target=self.auto_save, daemon=True)
        save_thread.start()
    
    def get_user(self, user_id):
        """Get user data from GitHub"""
        return self.load_user_from_github(user_id)
    
    def update_user(self, user_id, data):
        """Update user data"""
        data['user_id'] = str(user_id)
        self.save_user_to_github(data)

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
        200: "⚡ Huyền thoại",
        300: "🌌 Vũ trụ",
        500: "♾️ Vĩnh hằng"
    }
    
    for min_level in sorted(titles.keys(), reverse=True):
        if level >= min_level:
            return titles[min_level]
    return titles[1]

def calculate_fish_effects(fish_data):
    """Calculate special effects for fish"""
    effects = []
    total_multiplier = 1
    
    base_effect_chance = fish_data.get("effect_chance", 10)
    
    for effect_id, effect_data in FISH_EFFECTS.items():
        roll = random.uniform(0, 100)
        if roll <= effect_data["chance"] * (base_effect_chance / 100):
            effects.append(effect_data)
            total_multiplier *= effect_data["multiplier"]
    
    if len(effects) > 3:
        effects = sorted(effects, key=lambda x: x["multiplier"], reverse=True)[:3]
        total_multiplier = 1
        for effect in effects:
            total_multiplier *= effect["multiplier"]
    
    return effects, total_multiplier

def get_rarity_color(rarity):
    """Get color emoji for rarity"""
    colors = {
        "common": "⚪",
        "uncommon": "🟢",
        "rare": "🔵",
        "epic": "🟣",
        "legendary": "🟡",
        "mythic": "🔴",
        "secret": "⚫"
    }
    return colors.get(rarity, "⚪")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    user = data_manager.get_user(user_id)
    user["username"] = user_name
    data_manager.update_user(user_id, user)
    
    stats = ResourceMonitor.get_system_stats()
    
    welcome_text = f"""
🎮 **Chào mừng {user_name} đến với Fishing Game Bot!** 🎮

🎣 **Thông tin của bạn:**
├ 💰 Xu: {format_number(user['coins'])}
├ ⭐ Level: {user['level']} - {get_level_title(user['level'])}
├ 🎯 Kinh nghiệm: {user['exp']}
└ 🎣 Cần câu: {FISHING_RODS[user['inventory']['rod']]['name']}

📜 **Lệnh cơ bản:**
/menu - 📱 Menu chính
/fish - 🎣 Câu cá (có Auto)
/rods - 🎣 Cửa hàng cần câu
/stats - 📊 Thống kê

💡 **Độ hiếm cá:**
⚪Common 🟢Uncommon 🔵Rare 🟣Epic 🟡Legendary 🔴Mythic ⚫Secret

⚠️ **Lưu ý:** Cần xịn mới câu được cá hiếm!

💻 Hệ thống: CPU {stats['cpu']:.1f}% | RAM {stats['ram']:.1f}%
    """
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🎣 Câu Cá", callback_data='game_fishing'),
            InlineKeyboardButton("🤖 Auto Câu", callback_data='auto_fishing')
        ],
        [
            InlineKeyboardButton("🎣 Cần Câu", callback_data='shop_rods'),
            InlineKeyboardButton("🗺️ Tìm Kho Báu", callback_data='game_treasure')
        ],
        [
            InlineKeyboardButton("🎒 Kho Đồ", callback_data='view_inventory'),
            InlineKeyboardButton("🎲 Chẵn Lẻ", callback_data='game_chanle')
        ],
        [
            InlineKeyboardButton("📊 Thống Kê", callback_data='view_stats'),
            InlineKeyboardButton("🏆 BXH", callback_data='leaderboard')
        ],
        [
            InlineKeyboardButton("🎁 Quà Hàng Ngày", callback_data='daily_reward'),
            InlineKeyboardButton("💻 Hệ Thống", callback_data='system_info')
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

async def rods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show rods shop command"""
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    
    # Initialize owned_rods if not exists
    if 'owned_rods' not in user:
        user['owned_rods'] = ["1"]
        data_manager.update_user(user_id, user)
    
    keyboard = []
    row = []
    count = 0
    
    for rod_id, rod_data in FISHING_RODS.items():
        if rod_id not in user['owned_rods']:
            button_text = f"{rod_id}"
            if user['coins'] >= rod_data['price']:
                button_text = f"✅ {rod_id}"
            else:
                button_text = f"❌ {rod_id}"
            
            row.append(InlineKeyboardButton(button_text, callback_data=f'buy_rod_{rod_id}'))
            count += 1
            
            if count % 4 == 0:
                keyboard.append(row)
                row = []
    
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("◀️ Quay lại", callback_data='back_menu')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
🎣 **CỬA HÀNG CẦN CÂU** 🎣

💰 Xu của bạn: {format_number(user['coins'])}
🎣 Cần hiện tại: {FISHING_RODS[user['inventory']['rod']]['name']}

📝 **Chọn số để xem chi tiết và mua:**
✅ = Đủ xu | ❌ = Chưa đủ xu

**Cần đã sở hữu:** {', '.join(user['owned_rods'])}
    """
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def fish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fish command with auto option"""
    keyboard = [
        [
            InlineKeyboardButton("🎣 Câu 1 lần", callback_data='fish_single'),
            InlineKeyboardButton("🤖 Auto câu", callback_data='auto_fishing')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎣 **CHỌN CHẾ ĐỘ CÂU CÁ**\n⚠️ Auto câu chậm hơn và khó ra cá hiếm!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def process_fishing(user_id, is_auto=False):
    """Process fishing logic"""
    user = data_manager.get_user(user_id)
    
    if user["coins"] < 10:
        return None, "❌ Không đủ xu! Cần 10 xu để câu cá."
    
    user["coins"] -= 10
    rod_data = FISHING_RODS[user['inventory']['rod']]
    
    rand = random.uniform(0, 100)
    cumulative = 0
    caught_fish = None
    reward = 0
    exp = 0
    
    for fish_name, fish_data in FISH_TYPES.items():
        rarity = fish_data['rarity']
        if rarity == 'common':
            chance = fish_data["chance"] * rod_data['common_bonus']
        elif rarity == 'uncommon':
            chance = fish_data["chance"] * rod_data['common_bonus']
        elif rarity == 'rare':
            chance = fish_data["chance"] * rod_data['rare_bonus']
        elif rarity == 'epic':
            chance = fish_data["chance"] * rod_data['epic_bonus']
        elif rarity == 'legendary':
            chance = fish_data["chance"] * rod_data['legendary_bonus']
        elif rarity == 'mythic':
            chance = fish_data["chance"] * rod_data['mythic_bonus']
        elif rarity == 'secret':
            chance = fish_data["chance"] * rod_data['secret_bonus']
        else:
            chance = fish_data["chance"]
        
        if is_auto and rarity in ['epic', 'legendary', 'mythic', 'secret']:
            chance *= 0.5
        
        cumulative += chance
        if rand <= cumulative:
            caught_fish = fish_name
            base_reward = fish_data["value"]
            exp = fish_data["exp"]
            
            effects, effect_multiplier = calculate_fish_effects(fish_data)
            
            reward = base_reward * effect_multiplier
            break
    
    if caught_fish:
        if caught_fish not in user['inventory']['fish']:
            user['inventory']['fish'][caught_fish] = 0
        user['inventory']['fish'][caught_fish] += 1
        
        user["coins"] += reward
        user["exp"] += exp
        new_level = (user["exp"] // 100) + 1
        leveled_up = new_level > user["level"]
        if leveled_up:
            user["level"] = new_level
        
        user["fishing_count"] += 1
        user["win_count"] += 1
        
        if user.get('best_multiplier', 0) < effect_multiplier:
            user['best_multiplier'] = effect_multiplier
        
        if 'total_effects' not in user:
            user['total_effects'] = {}
        for effect in effects:
            effect_name = effect["name"]
            if effect_name not in user['total_effects']:
                user['total_effects'][effect_name] = 0
            user['total_effects'][effect_name] += 1
        
        data_manager.update_user(user_id, user)
        
        fish_rarity = ""
        for fname, fdata in FISH_TYPES.items():
            if fname == caught_fish:
                fish_rarity = fdata['rarity']
                break
        
        result = {
            "success": True,
            "fish": caught_fish,
            "rarity": fish_rarity,
            "reward": reward,
            "exp": exp,
            "effects": effects,
            "effect_multiplier": effect_multiplier,
            "leveled_up": leveled_up,
            "new_level": user["level"],
            "coins": user["coins"]
        }
        
        return result, None
    else:
        user["fishing_count"] += 1
        data_manager.update_user(user_id, user)
        return {"success": False, "coins": user["coins"]}, None

async def auto_fishing_task(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, message_id: int, chat_id: int):
    """Auto fishing task"""
    count = 0
    total_coins = 0
    total_exp = 0
    fish_caught = {}
    effects_count = {}
    rarity_count = {
        "common": 0,
        "uncommon": 0,
        "rare": 0,
        "epic": 0,
        "legendary": 0,
        "mythic": 0,
        "secret": 0
    }
    
    while user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks[user_id]:
        if count % 10 == 0 and not ResourceMonitor.check_resources():
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⛔ **AUTO TẠM DỪNG**\nHệ thống đang quá tải!\nĐã câu {count} lần",
                parse_mode='Markdown'
            )
            await asyncio.sleep(5)
            continue
        
        count += 1
        
        result, error = await process_fishing(user_id, is_auto=True)
        
        if error:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⛔ **AUTO ĐÃ DỪNG**\n{error}\nĐã câu {count-1} lần\n💰 Tổng thu: {format_number(total_coins)} xu",
                parse_mode='Markdown'
            )
            data_manager.auto_fishing_tasks[user_id] = False
            break
        
        if result["success"]:
            fish_name = result["fish"]
            if fish_name not in fish_caught:
                fish_caught[fish_name] = 0
            fish_caught[fish_name] += 1
            
            rarity_count[result["rarity"]] += 1
            
            total_coins += result["reward"] - 10
            total_exp += result["exp"]
            
            for effect in result["effects"]:
                effect_name = effect["name"]
                if effect_name not in effects_count:
                    effects_count[effect_name] = 0
                effects_count[effect_name] += 1
        else:
            total_coins -= 10
        
        user = data_manager.get_user(user_id)
        rod_data = FISHING_RODS[user['inventory']['rod']]
        
        status_text = f"""
🤖 **AUTO FISHING ĐANG CHẠY** 🤖

📊 **Thống kê Auto:**
├ 🔄 Số lần: {count}
├ 💰 Tổng thu: {format_number(total_coins)} xu
├ ⭐ Tổng EXP: {total_exp}
└ 💰 Xu hiện tại: {format_number(result['coins'] if result else user['coins'])} xu

📈 **Độ hiếm đã câu:**
"""
        for rarity, cnt in rarity_count.items():
            if cnt > 0:
                status_text += f"  {get_rarity_color(rarity)} {rarity}: {cnt}\n"
        
        status_text += "\n🐟 **Top 5 cá:**\n"
        for fish, qty in sorted(fish_caught.items(), key=lambda x: x[1], reverse=True)[:5]:
            status_text += f"  {fish}: {qty}\n"
        
        if effects_count:
            status_text += "\n✨ **Hiệu ứng:**\n"
            for effect, qty in sorted(effects_count.items(), key=lambda x: x[1], reverse=True):
                status_text += f"  {effect}: {qty}\n"
        
        status_text += f"\n🎣 Cần: {rod_data['name']}"
        
        keyboard = [[InlineKeyboardButton("🛑 DỪNG AUTO", callback_data='stop_auto')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=status_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except:
            pass
        
        await asyncio.sleep(rod_data['auto_speed'])
    
    if user_id in data_manager.auto_fishing_tasks:
        del data_manager.auto_fishing_tasks[user_id]

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == 'shop_rods':
        user = data_manager.get_user(user_id)
        
        if 'owned_rods' not in user:
            user['owned_rods'] = ["1"]
            data_manager.update_user(user_id, user)
        
        keyboard = []
        row = []
        count = 0
        
        for rod_id, rod_data in FISHING_RODS.items():
            if rod_id not in user['owned_rods']:
                button_text = f"{rod_id}"
                if user['coins'] >= rod_data['price']:
                    button_text = f"✅ {rod_id}"
                else:
                    button_text = f"❌ {rod_id}"
                
                row.append(InlineKeyboardButton(button_text, callback_data=f'buy_rod_{rod_id}'))
                count += 1
                
                if count % 4 == 0:
                    keyboard.append(row)
                    row = []
        
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔄 Đổi cần", callback_data='change_rod')])
        keyboard.append([InlineKeyboardButton("◀️ Quay lại", callback_data='back_menu')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"""
🎣 **CỬA HÀNG CẦN CÂU** 🎣

💰 Xu: {format_number(user['coins'])}
🎣 Đang dùng: {FISHING_RODS[user['inventory']['rod']]['name']}

📝 Chọn số để xem chi tiết:
✅ = Đủ xu | ❌ = Chưa đủ xu

**Đã sở hữu:** {', '.join(user['owned_rods'])}
        """
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == 'change_rod':
        user = data_manager.get_user(user_id)
        
        keyboard = []
        row = []
        count = 0
        
        for rod_id in user.get('owned_rods', ["1"]):
            if rod_id != user['inventory']['rod']:
                rod_data = FISHING_RODS[rod_id]
                row.append(InlineKeyboardButton(f"{rod_id}. {rod_data['name'][:8]}", callback_data=f'equip_rod_{rod_id}'))
                count += 1
                
                if count % 2 == 0:
                    keyboard.append(row)
                    row = []
        
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("◀️ Quay lại", callback_data='shop_rods')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔄 **CHỌN CẦN ĐỂ TRANG BỊ:**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data.startswith('equip_rod_'):
        rod_id = data.replace('equip_rod_', '')
        user = data_manager.get_user(user_id)
        
        if rod_id in user.get('owned_rods', []):
            user['inventory']['rod'] = rod_id
            data_manager.update_user(user_id, user)
            
            await query.edit_message_text(
                f"✅ Đã trang bị: {FISHING_RODS[rod_id]['name']}",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ Bạn chưa sở hữu cần này!")
    
    elif data.startswith('buy_rod_'):
        rod_id = data.replace('buy_rod_', '')
        user = data_manager.get_user(user_id)
        rod_data = FISHING_RODS[rod_id]
        
        text = f"""
🎣 **{rod_data['name']}**

💰 Giá: {format_number(rod_data['price'])} xu
⚡ Tốc độ: {rod_data['speed']}s
📝 {rod_data['description']}

💰 Xu của bạn: {format_number(user['coins'])}
        """
        
        keyboard = []
        if user['coins'] >= rod_data['price']:
            keyboard.append([InlineKeyboardButton("💰 MUA", callback_data=f'confirm_buy_{rod_id}')])
        keyboard.append([InlineKeyboardButton("◀️ Quay lại", callback_data='shop_rods')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data.startswith('confirm_buy_'):
        rod_id = data.replace('confirm_buy_', '')
        user = data_manager.get_user(user_id)
        rod_data = FISHING_RODS[rod_id]
        
        if user['coins'] < rod_data['price']:
            await query.edit_message_text("❌ Không đủ xu!")
            return
        
        if 'owned_rods' not in user:
            user['owned_rods'] = ["1"]
        
        if rod_id in user['owned_rods']:
            await query.edit_message_text("❌ Bạn đã sở hữu cần này!")
            return
        
        user['coins'] -= rod_data['price']
        user['owned_rods'].append(rod_id)
        user['inventory']['rod'] = rod_id
        data_manager.update_user(user_id, user)
        
        await query.edit_message_text(
            f"✅ **MUA THÀNH CÔNG!**\n{rod_data['name']}\n💰 Còn lại: {format_number(user['coins'])} xu",
            parse_mode='Markdown'
        )
    
    elif data == 'system_info':
        stats = ResourceMonitor.get_system_stats()
        text = f"""
💻 **THÔNG TIN HỆ THỐNG** 💻

📊 **Tài nguyên:**
├ 🖥️ CPU: {stats['cpu']:.1f}%
├ 💾 RAM: {stats['ram']:.1f}%
├ 📈 RAM đã dùng: {stats['ram_used']:.2f} GB
└ 📉 RAM tổng: {stats['ram_total']:.2f} GB

👥 **Bot:**
├ 🤖 Auto đang chạy: {len(data_manager.auto_fishing_tasks)}
└ ✅ Trạng thái: {'Tốt' if ResourceMonitor.check_resources() else '⚠️ Cao'}
        """
        await query.edit_message_text(text, parse_mode='Markdown')
    
    elif data == 'fish_single' or data == 'game_fishing':
        user = data_manager.get_user(user_id)
        rod_data = FISHING_RODS[user['inventory']['rod']]
        
        await query.edit_message_text(f"🎣 Đang thả câu... (chờ {rod_data['speed']}s)")
        await asyncio.sleep(rod_data['speed'])
        
        result, error = await process_fishing(user_id, is_auto=False)
        
        if error:
            await query.edit_message_text(error)
            return
        
        if result["success"]:
            result_text = f"""
🎉 **BẮT ĐƯỢC!**
{result['fish']} {get_rarity_color(result['rarity'])}
💰 +{format_number(result['reward'])} xu"""
            
            if result['effects']:
                result_text += f"\n✨ Hiệu ứng: "
                for effect in result['effects']:
                    result_text += f"{effect['name']} "
                result_text += f"\n🔥 Tổng nhân: x{result['effect_multiplier']}"
            
            result_text += f"""
⭐ +{result['exp']} EXP
📦 Đã lưu vào kho

💰 Số dư: {format_number(result['coins'])} xu"""
            
            if result['leveled_up']:
                result_text += f"\n\n🎊 **LEVEL UP! Bạn đã đạt level {result['new_level']}!**"
        else:
            result_text = f"😢 Không câu được gì!\n💰 Số dư: {format_number(result['coins'])} xu"
        
        await query.edit_message_text(result_text, parse_mode='Markdown')
    
    elif data == 'auto_fishing':
        if user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks[user_id]:
            await query.edit_message_text("⚠️ Bạn đang auto rồi! Dùng nút DỪNG để tắt.")
            return
        
        if not ResourceMonitor.check_resources():
            await query.edit_message_text("⚠️ Hệ thống đang quá tải! Thử lại sau.")
            return
        
        data_manager.auto_fishing_tasks[user_id] = True
        
        await query.edit_message_text("🤖 **BẮT ĐẦU AUTO FISHING...**")
        
        asyncio.create_task(auto_fishing_task(
            update,
            context,
            user_id,
            query.message.message_id,
            query.message.chat_id
        ))
    
    elif data == 'stop_auto':
        if user_id in data_manager.auto_fishing_tasks:
            data_manager.auto_fishing_tasks[user_id] = False
            await query.edit_message_text("🛑 **AUTO ĐÃ DỪNG**")
    
    elif data == 'game_chanle':
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
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎲 **TRÒ CHƠI CHẴN LẺ** 🎲\nChọn chẵn hoặc lẻ:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    # ... (Continue with other callbacks like before)
    
    elif data == 'back_menu':
        user = data_manager.get_user(user_id)
        keyboard = [
            [
                InlineKeyboardButton("🎣 Câu Cá", callback_data='game_fishing'),
                InlineKeyboardButton("🤖 Auto Câu", callback_data='auto_fishing')
            ],
            [
                InlineKeyboardButton("🎣 Cần Câu", callback_data='shop_rods'),
                InlineKeyboardButton("🗺️ Tìm Kho Báu", callback_data='game_treasure')
            ],
            [
                InlineKeyboardButton("🎒 Kho Đồ", callback_data='view_inventory'),
                InlineKeyboardButton("🎲 Chẵn Lẻ", callback_data='game_chanle')
            ],
            [
                InlineKeyboardButton("📊 Thống Kê", callback_data='view_stats'),
                InlineKeyboardButton("🏆 BXH", callback_data='leaderboard')
            ],
            [
                InlineKeyboardButton("🎁 Quà Hàng Ngày", callback_data='daily_reward'),
                InlineKeyboardButton("💻 Hệ Thống", callback_data='system_info')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        menu_text = f"""
🎮 **MENU CHÍNH** 🎮

👤 {user['username']} | Level {user['level']}
💰 {format_number(user['coins'])} xu | ⭐ {user['exp']} EXP
🎣 Cần: {FISHING_RODS[user['inventory']['rod']]['name']}

Chọn hoạt động:
        """
        
        await query.edit_message_text(menu_text, reply_markup=reply_markup, parse_mode='Markdown')

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("fish", fish))
    application.add_handler(CommandHandler("rods", rods))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("🤖 Bot đang chạy...")
    print("📊 Data từ GitHub + Local backup")
    print("🎣 16 loại cần câu với hệ thống sở hữu")
    print("✨ Menu có Cần Câu, ẩn cần đã mua")
    
    stats = ResourceMonitor.get_system_stats()
    print(f"💻 CPU: {stats['cpu']:.1f}% | RAM: {stats['ram']:.1f}%")
    
    application.run_polling()

if __name__ == '__main__':
    main()
