import logging
import random
import json
import asyncio
from datetime import datetime, timedelta, timezone
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
import pytz

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

VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

FISH_RANKS = {
    "1": {"name": "🎣 Ngư Tân Thủ", "exp_required": 0, "coin_bonus": 1.0, "fish_bonus": 1.0},
    "2": {"name": "⚔️ Ngư Tiểu Hiệp", "exp_required": 5000, "coin_bonus": 1.15, "fish_bonus": 1.1},
    "3": {"name": "🗡️ Ngư Hiệp Khách", "exp_required": 20000, "coin_bonus": 1.35, "fish_bonus": 1.2},
    "4": {"name": "🛡️ Ngư Tráng Sĩ", "exp_required": 80000, "coin_bonus": 1.6, "fish_bonus": 1.35},
    "5": {"name": "⚡ Ngư Đại Hiệp", "exp_required": 250000, "coin_bonus": 2.0, "fish_bonus": 1.5},
    "6": {"name": "🌟 Ngư Tông Sư", "exp_required": 800000, "coin_bonus": 2.5, "fish_bonus": 1.75},
    "7": {"name": "🔥 Ngư Chân Nhân", "exp_required": 2000000, "coin_bonus": 3.2, "fish_bonus": 2.0},
    "8": {"name": "💫 Ngư Thánh Giả", "exp_required": 5000000, "coin_bonus": 4.0, "fish_bonus": 2.5},
    "9": {"name": "⚔️ Ngư Võ Thần", "exp_required": 15000000, "coin_bonus": 5.5, "fish_bonus": 3.0},
    "10": {"name": "👑 Ngư Minh Chủ", "exp_required": 50000000, "coin_bonus": 8.0, "fish_bonus": 4.0}
}

FISH_TYPES = {
    "🍤 Tép": {"value": 2, "chance": 25, "exp": 1, "rarity": "common"},
    "🦐 Tôm": {"value": 5, "chance": 22, "exp": 2, "rarity": "common"},
    "🐟 Cá nhỏ": {"value": 10, "chance": 20, "exp": 3, "rarity": "common"},
    "🐠 Cá vàng": {"value": 30, "chance": 18, "exp": 5, "rarity": "common"},
    "🦀 Cua nhỏ": {"value": 25, "chance": 16, "exp": 4, "rarity": "common"},
    "🐡 Cá nóc": {"value": 50, "chance": 12, "exp": 8, "rarity": "uncommon"},
    "🦀 Cua lớn": {"value": 60, "chance": 10, "exp": 10, "rarity": "uncommon"},
    "🦑 Mực": {"value": 80, "chance": 8, "exp": 12, "rarity": "uncommon"},
    "🐚 Sò điệp": {"value": 70, "chance": 9, "exp": 11, "rarity": "uncommon"},
    "🦐 Tôm hùm nhỏ": {"value": 90, "chance": 7, "exp": 13, "rarity": "uncommon"},
    "🦈 Cá mập nhỏ": {"value": 150, "chance": 5, "exp": 20, "rarity": "rare"},
    "🐙 Bạch tuộc": {"value": 200, "chance": 4, "exp": 25, "rarity": "rare"},
    "🦈 Cá mập lớn": {"value": 300, "chance": 3, "exp": 30, "rarity": "rare"},
    "🐢 Rùa biển": {"value": 400, "chance": 2.5, "exp": 35, "rarity": "rare"},
    "🦞 Tôm hùm": {"value": 500, "chance": 2, "exp": 40, "rarity": "rare"},
    "🐊 Cá sấu": {"value": 800, "chance": 1.5, "exp": 50, "rarity": "epic"},
    "🐋 Cá voi": {"value": 1000, "chance": 1, "exp": 60, "rarity": "epic"},
    "🦭 Hải cẩu": {"value": 900, "chance": 0.8, "exp": 55, "rarity": "epic"},
    "⚡ Cá điện": {"value": 1200, "chance": 0.6, "exp": 70, "rarity": "epic"},
    "🌟 Cá thần": {"value": 1500, "chance": 0.5, "exp": 80, "rarity": "epic"},
    "🐉 Rồng biển": {"value": 2500, "chance": 0.4, "exp": 100, "rarity": "legendary"},
    "💎 Kho báu": {"value": 3000, "chance": 0.3, "exp": 120, "rarity": "legendary"},
    "👑 Vua đại dương": {"value": 5000, "chance": 0.2, "exp": 150, "rarity": "legendary"},
    "🔱 Thủy thần": {"value": 6000, "chance": 0.15, "exp": 180, "rarity": "legendary"},
    "🌊 Hải vương": {"value": 7000, "chance": 0.1, "exp": 200, "rarity": "legendary"},
    "🦄 Kỳ lân biển": {"value": 10000, "chance": 0.08, "exp": 300, "rarity": "mythic"},
    "🐲 Long vương": {"value": 15000, "chance": 0.05, "exp": 400, "rarity": "mythic"},
    "☄️ Thiên thạch": {"value": 20000, "chance": 0.03, "exp": 500, "rarity": "mythic"},
    "🌌 Vũ trụ": {"value": 25000, "chance": 0.02, "exp": 600, "rarity": "mythic"},
    "✨ Thần thánh": {"value": 30000, "chance": 0.01, "exp": 700, "rarity": "mythic"},
    "🎭 Bí ẩn": {"value": 50000, "chance": 0.008, "exp": 1000, "rarity": "secret"},
    "🗿 Cổ đại": {"value": 75000, "chance": 0.005, "exp": 1500, "rarity": "secret"},
    "🛸 Ngoài hành tinh": {"value": 100000, "chance": 0.003, "exp": 2000, "rarity": "secret"},
    "🔮 Hư không": {"value": 150000, "chance": 0.002, "exp": 3000, "rarity": "secret"},
    "⭐ Vĩnh hằng": {"value": 500000, "chance": 0.001, "exp": 5000, "rarity": "secret"}
}

FISHING_RODS = {
    "1": {
        "name": "🎣 Cần cơ bản",
        "price": 0,
        "speed": 3.0,
        "auto_speed": 4.0,
        "common_bonus": 1.0,
        "rare_bonus": 0.5,
        "epic_bonus": 0.1,
        "legendary_bonus": 0.01,
        "mythic_bonus": 0.001,
        "secret_bonus": 0.0001,
        "exp_bonus": 1.0,
        "description": "Cần mặc định"
    },
    "2": {
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
        "exp_bonus": 1.1,
        "description": "Nhẹ hơn +10% EXP"
    },
    "3": {
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
        "exp_bonus": 1.2,
        "description": "Chắc chắn +20% EXP"
    },
    "4": {
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
        "exp_bonus": 1.3,
        "description": "Kim loại +30% EXP"
    },
    "5": {
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
        "exp_bonus": 1.5,
        "description": "Cứng cáp +50% EXP"
    },
    "6": {
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
        "exp_bonus": 1.75,
        "description": "Quý kim +75% EXP"
    },
    "7": {
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
        "exp_bonus": 2.0,
        "description": "Cao cấp x2 EXP"
    },
    "8": {
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
        "exp_bonus": 2.5,
        "description": "Siêu quý x2.5 EXP"
    },
    "9": {
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
        "exp_bonus": 3.0,
        "description": "Tinh thể x3 EXP"
    },
    "10": {
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
        "exp_bonus": 4.0,
        "description": "Cứng nhất x4 EXP"
    },
    "11": {
        "name": "🗿 Cần hắc diệu",
        "price": 5000000,
        "speed": 0.6,
        "auto_speed": 1.5,
        "common_bonus": 2.2,
        "rare_bonus": 8.0,
        "epic_bonus": 10.0,
        "legendary_bonus": 6.0,
        "mythic_bonus": 1.0,
        "secret_bonus": 0.01,
        "exp_bonus": 5.0,
        "description": "Cổ đại x5 EXP"
    },
    "12": {
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
        "exp_bonus": 7.0,
        "description": "Huyền thoại x7 EXP"
    },
    "13": {
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
        "exp_bonus": 10.0,
        "description": "Thiên giới x10 EXP"
    },
    "14": {
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
        "exp_bonus": 15.0,
        "description": "Vũ trụ x15 EXP"
    },
    "15": {
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
        "exp_bonus": 20.0,
        "description": "Bất tử x20 EXP"
    },
    "16": {
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
        "exp_bonus": 30.0,
        "description": "Tối thượng x30 EXP"
    }
}

def get_next_sunday():
    now = datetime.now(VIETNAM_TZ)
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.hour >= 0:
        days_until_sunday = 7
    next_sunday = now + timedelta(days=days_until_sunday)
    next_sunday = next_sunday.replace(hour=0, minute=0, second=0, microsecond=0)
    return next_sunday

def should_reset_weekly():
    now = datetime.now(VIETNAM_TZ)
    return now.weekday() == 6 and now.hour == 0 and now.minute < 1

def get_user_rank(exp):
    current_rank = FISH_RANKS["1"]
    rank_level = 1
    
    for level, rank_data in FISH_RANKS.items():
        if exp >= rank_data["exp_required"]:
            current_rank = rank_data
            rank_level = int(level)
        else:
            break
    
    next_rank = None
    exp_to_next = 0
    if rank_level < 10:
        next_rank = FISH_RANKS[str(rank_level + 1)]
        exp_to_next = next_rank["exp_required"] - exp
    
    return current_rank, rank_level, next_rank, exp_to_next

class LocalStorage:
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
        if stats["cpu"] > 80 or stats["ram"] > 85:
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
        self.start_weekly_reset_check()
    
    def check_and_reset_weekly(self):
        while True:
            if should_reset_weekly():
                logging.info("Starting weekly reset...")
                self.reset_all_users_coins()
                time.sleep(60)
            time.sleep(30)
    
    def start_weekly_reset_check(self):
        reset_thread = threading.Thread(target=self.check_and_reset_weekly, daemon=True)
        reset_thread.start()
    
    def reset_all_users_coins(self):
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
                                user_data['coins'] = 100
                                user_data['last_reset'] = datetime.now(VIETNAM_TZ).isoformat()
                                all_users[user_data['user_id']] = user_data
                        except:
                            pass
            except:
                pass
            
            if all_users:
                lines = []
                for user_id, data in all_users.items():
                    data['user_id'] = user_id
                    lines.append(json.dumps(data, ensure_ascii=False))
                
                content = '\n'.join(lines)
                
                try:
                    file = self.repo.get_contents(GITHUB_FILE_PATH)
                    self.repo.update_file(
                        GITHUB_FILE_PATH,
                        f"Weekly reset - {datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')}",
                        content,
                        file.sha
                    )
                    logging.info("Weekly reset completed!")
                except:
                    self.repo.create_file(
                        GITHUB_FILE_PATH,
                        f"Weekly reset - {datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')}",
                        content
                    )
        except Exception as e:
            logging.error(f"Error in weekly reset: {e}")
    
    def load_user_from_github(self, user_id):
        try:
            file_content = self.repo.get_contents(GITHUB_FILE_PATH)
            content_str = base64.b64decode(file_content.content).decode()
            lines = content_str.strip().split('\n')
            
            for line in lines:
                if line.strip():
                    try:
                        user_data = json.loads(line)
                        if user_data.get('user_id') == str(user_id):
                            if 'owned_rods' not in user_data:
                                user_data['owned_rods'] = ["1"]
                            if 'inventory' not in user_data:
                                user_data['inventory'] = {"rod": "1", "fish": {}}
                            elif 'rod' not in user_data['inventory']:
                                user_data['inventory']['rod'] = "1"
                            if 'total_exp' not in user_data:
                                user_data['total_exp'] = user_data.get('exp', 0)
                            return user_data
                    except:
                        pass
        except Exception as e:
            logging.error(f"Error loading from GitHub: {e}")
            local_data = LocalStorage.load_local()
            if str(user_id) in local_data:
                user_data = local_data[str(user_id)]
                if 'owned_rods' not in user_data:
                    user_data['owned_rods'] = ["1"]
                if 'inventory' not in user_data:
                    user_data['inventory'] = {"rod": "1", "fish": {}}
                elif 'rod' not in user_data['inventory']:
                    user_data['inventory']['rod'] = "1"
                if 'total_exp' not in user_data:
                    user_data['total_exp'] = user_data.get('exp', 0)
                return user_data
        
        return self.create_new_user(str(user_id))
    
    def create_new_user(self, user_id):
        return {
            "user_id": str(user_id),
            "username": "",
            "coins": 100,
            "exp": 0,
            "total_exp": 0,
            "level": 1,
            "fishing_count": 0,
            "win_count": 0,
            "lose_count": 0,
            "treasures_found": 0,
            "best_multiplier": 0,
            "owned_rods": ["1"],
            "inventory": {
                "rod": "1",
                "fish": {}
            },
            "daily_claimed": None,
            "last_reset": None,
            "created_at": datetime.now().isoformat()
        }
    
    def save_user_to_github(self, user_data):
        with self.lock:
            self.save_queue.append(user_data)
    
    def batch_save_to_github(self):
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
                    f"Update - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content,
                    file.sha
                )
            except:
                self.repo.create_file(
                    GITHUB_FILE_PATH,
                    f"Create - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    content
                )
            
            logging.info(f"Saved {len(users_to_save)} users")
        except Exception as e:
            logging.error(f"Error saving: {e}")
    
    def auto_save(self):
        while True:
            time.sleep(30)
            if self.save_queue:
                self.executor.submit(self.batch_save_to_github)
    
    def start_auto_save(self):
        save_thread = threading.Thread(target=self.auto_save, daemon=True)
        save_thread.start()
    
    def get_user(self, user_id):
        user_data = self.load_user_from_github(user_id)
        if 'inventory' not in user_data or 'rod' not in user_data['inventory']:
            user_data['inventory'] = {"rod": "1", "fish": {}}
        if user_data['inventory']['rod'] not in FISHING_RODS:
            user_data['inventory']['rod'] = "1"
        if 'total_exp' not in user_data:
            user_data['total_exp'] = user_data.get('exp', 0)
        return user_data
    
    def update_user(self, user_id, data):
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

def get_rarity_color(rarity):
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

def get_current_rod_name(user):
    rod_id = user.get('inventory', {}).get('rod', '1')
    if rod_id in FISHING_RODS:
        return FISHING_RODS[rod_id]['name']
    return FISHING_RODS['1']['name']

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    user = data_manager.get_user(user_id)
    user["username"] = user_name
    data_manager.update_user(user_id, user)
    
    current_rank, rank_level, next_rank, exp_to_next = get_user_rank(user.get('total_exp', 0))
    stats = ResourceMonitor.get_system_stats()
    next_reset = get_next_sunday()
    
    welcome_text = f"""
🎮 **Chào mừng {user_name}!** 🎮

🎯 **Thông tin:**
├ 💰 Xu: {format_number(user['coins'])}
├ ⭐ Level: {user['level']} - {get_level_title(user['level'])}
├ 🎯 EXP: {format_number(user.get('total_exp', 0))}
├ 🏆 Rank: {current_rank['name']}
└ 🎣 Cần: {get_current_rod_name(user)}

⏰ Reset xu: Chủ nhật {next_reset.strftime('%d/%m %H:%M')} GMT+7

📜 /menu /fish /rank /rods /stats

💻 CPU {stats['cpu']:.1f}% | RAM {stats['ram']:.1f}%
    """
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def rank_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    
    current_rank, rank_level, next_rank, exp_to_next = get_user_rank(user.get('total_exp', 0))
    
    text = f"""
🏆 **HỆ THỐNG RANK NGƯ HIỆP** 🏆

👤 {user['username']}
🎯 Tổng EXP: {format_number(user.get('total_exp', 0))}
🏆 Rank hiện tại: {current_rank['name']}

📊 **Buff hiện tại:**
├ 💰 Xu câu cá: x{current_rank['coin_bonus']}
└ 🎣 Tỷ lệ cá: x{current_rank['fish_bonus']}
"""
    
    if next_rank:
        progress = user.get('total_exp', 0) - current_rank['exp_required']
        total_needed = next_rank['exp_required'] - current_rank['exp_required']
        percent = (progress / total_needed * 100) if total_needed > 0 else 0
        
        text += f"""
📈 **Tiến độ:**
├ Rank tiếp: {next_rank['name']}
├ Cần thêm: {format_number(exp_to_next)} EXP
└ Tiến độ: {percent:.1f}%
"""
    else:
        text += "\n👑 Đã đạt rank cao nhất!"
    
    text += "\n\n📋 **Danh sách Rank:**"
    for level, rank_data in FISH_RANKS.items():
        if int(level) <= rank_level:
            text += f"\n✅ {rank_data['name']} - {format_number(rank_data['exp_required'])} EXP"
        else:
            text += f"\n⬜ {rank_data['name']} - {format_number(rank_data['exp_required'])} EXP"
            if int(level) > rank_level + 2:
                break
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    
    keyboard = [
        [
            InlineKeyboardButton("🎣 Câu Cá", callback_data='game_fishing'),
            InlineKeyboardButton("🤖 Auto", callback_data='auto_fishing')
        ],
        [
            InlineKeyboardButton("🎣 Cần Câu", callback_data='shop_rods'),
            InlineKeyboardButton("🗺️ Kho Báu", callback_data='game_treasure')
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
            InlineKeyboardButton("🏆 Rank", callback_data='view_rank'),
            InlineKeyboardButton("🎁 Quà", callback_data='daily_reward')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    next_reset = get_next_sunday()
    
    menu_text = f"""
🎮 **MENU CHÍNH** 🎮

👤 {user['username']} | Lv.{user['level']}
💰 {format_number(user['coins'])} xu | ⭐ {format_number(user.get('total_exp', 0))} EXP
🏆 {current_rank['name']}
🎣 {get_current_rod_name(user)}

⏰ Reset: CN {next_reset.strftime('%d/%m')}
    """
    
    await update.message.reply_text(menu_text, reply_markup=reply_markup, parse_mode='Markdown')

async def process_fishing(user_id, is_auto=False):
    user = data_manager.get_user(user_id)
    
    if user["coins"] < 10:
        return None, "❌ Cần 10 xu!"
    
    user["coins"] -= 10
    rod_id = user.get('inventory', {}).get('rod', '1')
    if rod_id not in FISHING_RODS:
        rod_id = '1'
    rod_data = FISHING_RODS[rod_id]
    
    current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    
    rand = random.uniform(0, 100)
    cumulative = 0
    caught_fish = None
    reward = 0
    exp = 0
    
    for fish_name, fish_data in FISH_TYPES.items():
        rarity = fish_data['rarity']
        chance_map = {
            'common': rod_data['common_bonus'],
            'uncommon': rod_data['common_bonus'],
            'rare': rod_data['rare_bonus'],
            'epic': rod_data['epic_bonus'],
            'legendary': rod_data['legendary_bonus'],
            'mythic': rod_data['mythic_bonus'],
            'secret': rod_data['secret_bonus']
        }
        
        chance = fish_data["chance"] * chance_map.get(rarity, 1.0) * current_rank['fish_bonus']
        
        if is_auto and rarity in ['epic', 'legendary', 'mythic', 'secret']:
            chance *= 0.5
        
        cumulative += chance
        if rand <= cumulative:
            caught_fish = fish_name
            base_reward = int(fish_data["value"] * current_rank['coin_bonus'])
            exp = int(fish_data["exp"] * rod_data.get('exp_bonus', 1.0))
            reward = base_reward
            break
    
    if caught_fish:
        if 'fish' not in user['inventory']:
            user['inventory']['fish'] = {}
        if caught_fish not in user['inventory']['fish']:
            user['inventory']['fish'][caught_fish] = 0
        user['inventory']['fish'][caught_fish] += 1
        
        user["coins"] += reward
        user["exp"] += exp
        user["total_exp"] = user.get('total_exp', 0) + exp
        new_level = (user["exp"] // 100) + 1
        leveled_up = new_level > user["level"]
        if leveled_up:
            user["level"] = new_level
        
        user["fishing_count"] += 1
        user["win_count"] += 1
        
        data_manager.update_user(user_id, user)
        
        fish_rarity = ""
        for fname, fdata in FISH_TYPES.items():
            if fname == caught_fish:
                fish_rarity = fdata['rarity']
                break
        
        return {
            "success": True,
            "fish": caught_fish,
            "rarity": fish_rarity,
            "reward": reward,
            "exp": exp,
            "leveled_up": leveled_up,
            "new_level": user["level"],
            "coins": user["coins"]
        }, None
    else:
        user["fishing_count"] += 1
        data_manager.update_user(user_id, user)
        return {"success": False, "coins": user["coins"]}, None

async def auto_fishing_task(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, message_id: int, chat_id: int):
    count = 0
    total_coins = 0
    total_exp = 0
    fish_caught = {}
    rarity_count = {
        "common": 0, "uncommon": 0, "rare": 0,
        "epic": 0, "legendary": 0, "mythic": 0, "secret": 0
    }
    
    while user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks[user_id]:
        if count % 10 == 0 and not ResourceMonitor.check_resources():
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⛔ **TẠM DỪNG**\nQuá tải!\nĐã câu {count} lần",
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
                text=f"⛔ **DỪNG**\n{error}\nĐã câu {count-1} lần\n💰 Thu: {format_number(total_coins)} xu",
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
        else:
            total_coins -= 10
        
        user = data_manager.get_user(user_id)
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        rod_id = user.get('inventory', {}).get('rod', '1')
        if rod_id not in FISHING_RODS:
            rod_id = '1'
        rod_data = FISHING_RODS[rod_id]
        
        status_text = f"""
🤖 **AUTO FISHING** 🤖

📊 Thống kê:
├ 🔄 Lần: {count}
├ 💰 Thu: {format_number(total_coins)} xu
├ ⭐ EXP: {total_exp}
└ 💰 Xu: {format_number(result['coins'] if result else user['coins'])} xu

🏆 Rank: {current_rank['name']}
📈 Buff: 💰x{current_rank['coin_bonus']} 🎣x{current_rank['fish_bonus']}

📈 Độ hiếm:
"""
        for rarity, cnt in rarity_count.items():
            if cnt > 0:
                status_text += f"{get_rarity_color(rarity)} {cnt} "
        
        status_text += f"\n\n🎣 {rod_data['name']}"
        
        keyboard = [[InlineKeyboardButton("🛑 DỪNG", callback_data='stop_auto')]]
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
    
    if data == 'view_rank':
        user = data_manager.get_user(user_id)
        current_rank, rank_level, next_rank, exp_to_next = get_user_rank(user.get('total_exp', 0))
        
        text = f"""
🏆 **RANK NGƯ HIỆP** 🏆

🎯 EXP: {format_number(user.get('total_exp', 0))}
🏆 Rank: {current_rank['name']}

📊 **Buff:**
├ 💰 Xu: x{current_rank['coin_bonus']}
└ 🎣 Cá: x{current_rank['fish_bonus']}
"""
        
        if next_rank:
            progress = user.get('total_exp', 0) - current_rank['exp_required']
            total_needed = next_rank['exp_required'] - current_rank['exp_required']
            percent = (progress / total_needed * 100) if total_needed > 0 else 0
            
            text += f"""
📈 **Tiến độ:**
├ Tiếp: {next_rank['name']}
├ Cần: {format_number(exp_to_next)} EXP
└ {percent:.1f}%
"""
        else:
            text += "\n👑 Max rank!"
        
        await query.edit_message_text(text, parse_mode='Markdown')
    
    elif data == 'game_fishing' or data == 'fish_single':
        user = data_manager.get_user(user_id)
        rod_id = user.get('inventory', {}).get('rod', '1')
        if rod_id not in FISHING_RODS:
            rod_id = '1'
        rod_data = FISHING_RODS[rod_id]
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        
        await query.edit_message_text(f"🎣 Đang câu... ({rod_data['speed']}s)")
        await asyncio.sleep(rod_data['speed'])
        
        result, error = await process_fishing(user_id, is_auto=False)
        
        if error:
            await query.edit_message_text(error)
            return
        
        if result["success"]:
            result_text = f"""
🎉 **BẮT ĐƯỢC!**
{result['fish']} {get_rarity_color(result['rarity'])}
💰 +{format_number(result['reward'])} xu (Rank x{current_rank['coin_bonus']})
⭐ +{result['exp']} EXP
💰 Xu: {format_number(result['coins'])}"""
            
            if result['leveled_up']:
                result_text += f"\n\n🎊 **LEVEL {result['new_level']}!**"
        else:
            result_text = f"😢 Trượt!\n💰 Xu: {format_number(result['coins'])}"
        
        await query.edit_message_text(result_text, parse_mode='Markdown')
    
    elif data == 'sell_fish':
        user = data_manager.get_user(user_id)
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        total_value = 0
        total_count = 0
        
        fish_inv = user.get('inventory', {}).get('fish', {})
        if fish_inv:
            for fish_name, count in fish_inv.items():
                for fish_type, fish_data in FISH_TYPES.items():
                    if fish_type == fish_name:
                        total_value += fish_data['value'] * count * 0.7 * current_rank['coin_bonus']
                        total_count += count
                        break
            
            user['inventory']['fish'] = {}
            user["coins"] += int(total_value)
            data_manager.update_user(user_id, user)
            
            await query.edit_message_text(
                f"💰 **BÁN THÀNH CÔNG!**\n{total_count} con\n+{format_number(int(total_value))} xu (Rank x{current_rank['coin_bonus']})\n💰 Xu: {format_number(user['coins'])}",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ Không có cá!")
    
    elif data == 'leaderboard':
        all_users = []
        try:
            file_content = data_manager.repo.get_contents(GITHUB_FILE_PATH)
            content_str = base64.b64decode(file_content.content).decode()
            lines = content_str.strip().split('\n')
            
            for line in lines:
                if line.strip():
                    try:
                        user_data = json.loads(line)
                        all_users.append(user_data)
                    except:
                        pass
        except:
            pass
        
        sorted_by_exp = sorted(all_users, key=lambda x: x.get('total_exp', 0), reverse=True)[:10]
        
        text = "🏆 **TOP 10 RANK** 🏆\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for i, user_data in enumerate(sorted_by_exp, 1):
            medal = medals[i-1] if i <= 3 else f"{i}."
            user_rank, _, _, _ = get_user_rank(user_data.get('total_exp', 0))
            text += f"{medal} {user_data.get('username', 'User')}\n"
            text += f"   {user_rank['name']} - {format_number(user_data.get('total_exp', 0))} EXP\n"
        
        await query.edit_message_text(text, parse_mode='Markdown')
    
    elif data == 'auto_fishing':
        if user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks[user_id]:
            await query.edit_message_text("⚠️ Đang auto rồi!")
            return
        
        if not ResourceMonitor.check_resources():
            await query.edit_message_text("⚠️ Hệ thống quá tải!")
            return
        
        data_manager.auto_fishing_tasks[user_id] = True
        
        await query.edit_message_text("🤖 **BẮT ĐẦU AUTO...**")
        
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
            await query.edit_message_text("🛑 **ĐÃ DỪNG**")
    
    elif data == 'back_menu':
        user = data_manager.get_user(user_id)
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        
        keyboard = [
            [
                InlineKeyboardButton("🎣 Câu Cá", callback_data='game_fishing'),
                InlineKeyboardButton("🤖 Auto", callback_data='auto_fishing')
            ],
            [
                InlineKeyboardButton("🎣 Cần Câu", callback_data='shop_rods'),
                InlineKeyboardButton("🗺️ Kho Báu", callback_data='game_treasure')
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
                InlineKeyboardButton("🏆 Rank", callback_data='view_rank'),
                InlineKeyboardButton("🎁 Quà", callback_data='daily_reward')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        next_reset = get_next_sunday()
        
        menu_text = f"""
🎮 **MENU CHÍNH** 🎮

👤 {user['username']} | Lv.{user['level']}
💰 {format_number(user['coins'])} xu | ⭐ {format_number(user.get('total_exp', 0))} EXP
🏆 {current_rank['name']}
🎣 {get_current_rod_name(user)}

⏰ Reset: CN {next_reset.strftime('%d/%m')}
        """
        
        await query.edit_message_text(menu_text, reply_markup=reply_markup, parse_mode='Markdown')

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("rank", rank_info))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    next_reset = get_next_sunday()
    
    print("🤖 Bot đang chạy...")
    print("🏆 Hệ thống Rank Ngư Hiệp")
    print(f"⏰ Reset tiếp: {next_reset.strftime('%d/%m/%Y %H:%M')} GMT+7")
    print("📊 Rank buff xu và tỷ lệ cá")
    
    stats = ResourceMonitor.get_system_stats()
    print(f"💻 CPU: {stats['cpu']:.1f}% | RAM: {stats['ram']:.1f}%")
    
    application.run_polling()

if __name__ == '__main__':
    main()
