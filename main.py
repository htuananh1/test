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

# ===== CONFIGURATION =====
BOT_TOKEN = os.getenv('BOT_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO', 'htuananh1/Data-manager')
GITHUB_FILE_PATH = "bot_data.json"
LOCAL_BACKUP_FILE = "local_backup.json"

VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# ===== HỆ THỐNG RANK NGƯ HIỆP MỞ RỘNG =====
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
    "10": {"name": "👑 Ngư Minh Chủ", "exp_required": 50000000, "coin_bonus": 8.0, "fish_bonus": 4.0},
    "11": {"name": "🌊 Ngư Hải Vương", "exp_required": 100000000, "coin_bonus": 10.0, "fish_bonus": 5.0},
    "12": {"name": "🔱 Ngư Thần Thánh", "exp_required": 200000000, "coin_bonus": 13.0, "fish_bonus": 6.0},
    "13": {"name": "⭐ Ngư Tiên Vương", "exp_required": 400000000, "coin_bonus": 17.0, "fish_bonus": 7.5},
    "14": {"name": "🌌 Ngư Thiên Tôn", "exp_required": 800000000, "coin_bonus": 22.0, "fish_bonus": 9.0},
    "15": {"name": "♾️ Ngư Vĩnh Hằng", "exp_required": 1500000000, "coin_bonus": 30.0, "fish_bonus": 12.0},
    "16": {"name": "🔮 Ngư Toàn Năng", "exp_required": 3000000000, "coin_bonus": 40.0, "fish_bonus": 15.0},
    "17": {"name": "🌠 Ngư Sáng Thế", "exp_required": 6000000000, "coin_bonus": 55.0, "fish_bonus": 20.0},
    "18": {"name": "⚜️ Ngư Tối Cao", "exp_required": 10000000000, "coin_bonus": 75.0, "fish_bonus": 25.0},
    "19": {"name": "🎭 Ngư Huyền Thoại", "exp_required": 20000000000, "coin_bonus": 100.0, "fish_bonus": 35.0},
    "20": {"name": "🏆 Ngư Cực Phẩm", "exp_required": 50000000000, "coin_bonus": 150.0, "fish_bonus": 50.0}
}

# ===== DANH SÁCH CÁ MỞ RỘNG =====
FISH_TYPES = {
    # Common (35% total)
    "🍤 Tép": {"value": 2, "chance": 8.0, "exp": 1, "rarity": "common"},
    "🦐 Tôm": {"value": 5, "chance": 7.5, "exp": 2, "rarity": "common"},
    "🐟 Cá nhỏ": {"value": 10, "chance": 7.0, "exp": 3, "rarity": "common"},
    "🐠 Cá vàng": {"value": 30, "chance": 6.5, "exp": 5, "rarity": "common"},
    "🦀 Cua nhỏ": {"value": 25, "chance": 6.0, "exp": 4, "rarity": "common"},
    
    # Uncommon (25% total)
    "🐡 Cá nóc": {"value": 50, "chance": 5.5, "exp": 8, "rarity": "uncommon"},
    "🦀 Cua lớn": {"value": 60, "chance": 5.0, "exp": 10, "rarity": "uncommon"},
    "🦑 Mực": {"value": 80, "chance": 4.5, "exp": 12, "rarity": "uncommon"},
    "🐚 Sò điệp": {"value": 70, "chance": 4.0, "exp": 11, "rarity": "uncommon"},
    "🦐 Tôm hùm nhỏ": {"value": 90, "chance": 3.5, "exp": 13, "rarity": "uncommon"},
    "🦪 Hàu": {"value": 85, "chance": 3.0, "exp": 14, "rarity": "uncommon"},
    
    # Rare (20% total)
    "🦈 Cá mập nhỏ": {"value": 150, "chance": 4.0, "exp": 20, "rarity": "rare"},
    "🐙 Bạch tuộc": {"value": 200, "chance": 3.5, "exp": 25, "rarity": "rare"},
    "🦈 Cá mập lớn": {"value": 300, "chance": 3.0, "exp": 30, "rarity": "rare"},
    "🐢 Rùa biển": {"value": 400, "chance": 2.5, "exp": 35, "rarity": "rare"},
    "🦞 Tôm hùm": {"value": 500, "chance": 2.0, "exp": 40, "rarity": "rare"},
    "🦑 Mực khổng lồ": {"value": 600, "chance": 1.8, "exp": 45, "rarity": "rare"},
    "🐠 Cá chép vàng": {"value": 700, "chance": 1.6, "exp": 50, "rarity": "rare"},
    "🐟 Cá kiếm": {"value": 750, "chance": 1.4, "exp": 52, "rarity": "rare"},
    "🦭 Sư tử biển": {"value": 650, "chance": 1.2, "exp": 48, "rarity": "rare"},
    
    # Epic (15% total)
    "🐊 Cá sấu": {"value": 800, "chance": 2.5, "exp": 60, "rarity": "epic"},
    "🐋 Cá voi": {"value": 1000, "chance": 2.2, "exp": 70, "rarity": "epic"},
    "🦭 Hải cẩu": {"value": 900, "chance": 2.0, "exp": 65, "rarity": "epic"},
    "⚡ Cá điện": {"value": 1200, "chance": 1.8, "exp": 75, "rarity": "epic"},
    "🌟 Cá thần": {"value": 1500, "chance": 1.5, "exp": 80, "rarity": "epic"},
    "🦈 Megalodon": {"value": 1800, "chance": 1.3, "exp": 85, "rarity": "epic"},
    "🐙 Kraken nhỏ": {"value": 2000, "chance": 1.1, "exp": 90, "rarity": "epic"},
    "🌊 Cá thủy tinh": {"value": 2200, "chance": 0.9, "exp": 95, "rarity": "epic"},
    "🔥 Cá lửa": {"value": 2400, "chance": 0.8, "exp": 98, "rarity": "epic"},
    "❄️ Cá băng": {"value": 2300, "chance": 0.7, "exp": 96, "rarity": "epic"},
    "🌈 Cá cầu vồng": {"value": 2100, "chance": 0.6, "exp": 92, "rarity": "epic"},
    
    # Legendary (4% total)
    "🐉 Rồng biển": {"value": 2500, "chance": 0.8, "exp": 120, "rarity": "legendary"},
    "💎 Kho báu": {"value": 3000, "chance": 0.7, "exp": 140, "rarity": "legendary"},
    "👑 Vua đại dương": {"value": 5000, "chance": 0.6, "exp": 180, "rarity": "legendary"},
    "🔱 Thủy thần": {"value": 6000, "chance": 0.5, "exp": 200, "rarity": "legendary"},
    "🌊 Hải vương": {"value": 7000, "chance": 0.4, "exp": 220, "rarity": "legendary"},
    "🐙 Kraken": {"value": 8000, "chance": 0.35, "exp": 250, "rarity": "legendary"},
    "🦕 Thủy quái": {"value": 9000, "chance": 0.3, "exp": 280, "rarity": "legendary"},
    "⚓ Tàu ma": {"value": 10000, "chance": 0.25, "exp": 300, "rarity": "legendary"},
    "🏴‍☠️ Hải tặc huyền thoại": {"value": 11000, "chance": 0.2, "exp": 320, "rarity": "legendary"},
    "🧜‍♀️ Tiên cá": {"value": 12000, "chance": 0.15, "exp": 350, "rarity": "legendary"},
    "🔮 Pha lê biển": {"value": 13000, "chance": 0.1, "exp": 380, "rarity": "legendary"},
    
    # Mythic (1% total)
    "🦄 Kỳ lân biển": {"value": 15000, "chance": 0.2, "exp": 500, "rarity": "mythic"},
    "🐲 Long vương": {"value": 20000, "chance": 0.18, "exp": 600, "rarity": "mythic"},
    "☄️ Thiên thạch": {"value": 25000, "chance": 0.15, "exp": 700, "rarity": "mythic"},
    "🌌 Vũ trụ": {"value": 30000, "chance": 0.12, "exp": 800, "rarity": "mythic"},
    "✨ Thần thánh": {"value": 35000, "chance": 0.1, "exp": 900, "rarity": "mythic"},
    "🎇 Tinh vân": {"value": 40000, "chance": 0.08, "exp": 1000, "rarity": "mythic"},
    "🌠 Sao băng": {"value": 45000, "chance": 0.06, "exp": 1100, "rarity": "mythic"},
    "💫 Thiên hà": {"value": 50000, "chance": 0.05, "exp": 1200, "rarity": "mythic"},
    "🪐 Hành tinh": {"value": 55000, "chance": 0.04, "exp": 1300, "rarity": "mythic"},
    "☀️ Mặt trời": {"value": 60000, "chance": 0.02, "exp": 1500, "rarity": "mythic"},
    
    # Secret (0.1% total)
    "🎭 Bí ẩn": {"value": 100000, "chance": 0.02, "exp": 2000, "rarity": "secret"},
    "🗿 Cổ đại": {"value": 150000, "chance": 0.018, "exp": 2500, "rarity": "secret"},
    "🛸 Ngoài hành tinh": {"value": 200000, "chance": 0.015, "exp": 3000, "rarity": "secret"},
    "🔮 Hư không": {"value": 300000, "chance": 0.012, "exp": 4000, "rarity": "secret"},
    "⭐ Vĩnh hằng": {"value": 500000, "chance": 0.01, "exp": 5000, "rarity": "secret"},
    "🌟 Thần thoại": {"value": 750000, "chance": 0.008, "exp": 6000, "rarity": "secret"},
    "💠 Vô cực": {"value": 1000000, "chance": 0.006, "exp": 7500, "rarity": "secret"},
    "🔯 Siêu việt": {"value": 1500000, "chance": 0.004, "exp": 9000, "rarity": "secret"},
    "⚜️ Tối thượng": {"value": 2000000, "chance": 0.003, "exp": 10000, "rarity": "secret"},
    "♾️ Vô hạn": {"value": 5000000, "chance": 0.002, "exp": 15000, "rarity": "secret"},
    "🏆 Ultimate": {"value": 10000000, "chance": 0.001, "exp": 20000, "rarity": "secret"}
}

# ===== CẦN CÂU ĐẦY ĐỦ =====
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
        "description": "Cần mặc định cho người mới"
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
        "description": "Nhẹ và linh hoạt +10% EXP"
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
        "description": "Kim loại bền +30% EXP"
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
    },
    "17": {
        "name": "🌟 Cần thần thoại",
        "price": 2000000000,
        "speed": 0.08,
        "auto_speed": 0.25,
        "common_bonus": 15.0,
        "rare_bonus": 75.0,
        "epic_bonus": 150.0,
        "legendary_bonus": 150.0,
        "mythic_bonus": 75.0,
        "secret_bonus": 1.5,
        "exp_bonus": 40.0,
        "description": "Thần thoại x40 EXP"
    },
    "18": {
        "name": "⚡ Cần lôi thần",
        "price": 5000000000,
        "speed": 0.06,
        "auto_speed": 0.2,
        "common_bonus": 20.0,
        "rare_bonus": 100.0,
        "epic_bonus": 200.0,
        "legendary_bonus": 200.0,
        "mythic_bonus": 100.0,
        "secret_bonus": 2.0,
        "exp_bonus": 50.0,
        "description": "Sấm sét x50 EXP"
    },
    "19": {
        "name": "🏆 Cần tối cao",
        "price": 10000000000,
        "speed": 0.04,
        "auto_speed": 0.15,
        "common_bonus": 30.0,
        "rare_bonus": 150.0,
        "epic_bonus": 300.0,
        "legendary_bonus": 300.0,
        "mythic_bonus": 150.0,
        "secret_bonus": 3.0,
        "exp_bonus": 75.0,
        "description": "Đỉnh cao x75 EXP"
    },
    "20": {
        "name": "👑 Cần chúa tể",
        "price": 50000000000,
        "speed": 0.02,
        "auto_speed": 0.1,
        "common_bonus": 50.0,
        "rare_bonus": 250.0,
        "epic_bonus": 500.0,
        "legendary_bonus": 500.0,
        "mythic_bonus": 250.0,
        "secret_bonus": 5.0,
        "exp_bonus": 100.0,
        "description": "Bá chủ x100 EXP"
    }
}

# ===== CACHE SYSTEM =====
class CacheManager:
    """Quản lý cache để giảm tải GitHub API"""
    def __init__(self):
        self.cache = {}
        self.cache_timeout = 60  # 60 giây
        
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_timeout:
                return data
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, time.time())
        
    def clear(self):
        self.cache = {}

cache_manager = CacheManager()

# ===== UTILITY FUNCTIONS =====
def get_next_sunday():
    """Lấy thời gian reset tuần tiếp theo (Chủ nhật)"""
    now = datetime.now(VIETNAM_TZ)
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.hour >= 0:
        days_until_sunday = 7
    next_sunday = now + timedelta(days=days_until_sunday)
    next_sunday = next_sunday.replace(hour=0, minute=0, second=0, microsecond=0)
    return next_sunday

def should_reset_weekly():
    """Kiểm tra xem có phải thời điểm reset tuần không"""
    now = datetime.now(VIETNAM_TZ)
    return now.weekday() == 6 and now.hour == 0 and now.minute < 1

def get_user_rank(exp):
    """Lấy thông tin rank dựa trên EXP"""
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
    if rank_level < len(FISH_RANKS):
        next_rank = FISH_RANKS.get(str(rank_level + 1))
        if next_rank:
            exp_to_next = next_rank["exp_required"] - exp
    
    return current_rank, rank_level, next_rank, exp_to_next

# ===== LOCAL STORAGE CLASS =====
class LocalStorage:
    """Quản lý lưu trữ dữ liệu local"""
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

# ===== RESOURCE MONITOR CLASS =====
class ResourceMonitor:
    """Giám sát tài nguyên hệ thống"""
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

# ===== DATA MANAGER CLASS =====
class DataManager:
    """Quản lý dữ liệu người chơi với GitHub"""
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
        """Kiểm tra và thực hiện reset tuần"""
        while True:
            if should_reset_weekly():
                logging.info("Starting weekly reset...")
                self.reset_all_users_coins()
                time.sleep(60)
            time.sleep(30)
    
    def start_weekly_reset_check(self):
        """Khởi động thread kiểm tra reset tuần"""
        reset_thread = threading.Thread(target=self.check_and_reset_weekly, daemon=True)
        reset_thread.start()
    
    def reset_all_users_coins(self):
        """Reset xu của tất cả người chơi về 100"""
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
            
            # Clear cache sau khi reset
            cache_manager.clear()
        except Exception as e:
            logging.error(f"Error in weekly reset: {e}")
    
    def load_user_from_github(self, user_id):
        """Load dữ liệu người chơi từ GitHub với cache"""
        # Kiểm tra cache trước
        cached_data = cache_manager.get(f"user_{user_id}")
        if cached_data:
            return cached_data
        
        try:
            file_content = self.repo.get_contents(GITHUB_FILE_PATH)
            content_str = base64.b64decode(file_content.content).decode()
            lines = content_str.strip().split('\n')
            
            for line in lines:
                if line.strip():
                    try:
                        user_data = json.loads(line)
                        if user_data.get('user_id') == str(user_id):
                            # Validate và fix data
                            if 'owned_rods' not in user_data:
                                user_data['owned_rods'] = ["1"]
                            if 'inventory' not in user_data:
                                user_data['inventory'] = {"rod": "1", "fish": {}}
                            elif 'rod' not in user_data['inventory']:
                                user_data['inventory']['rod'] = "1"
                            if 'total_exp' not in user_data:
                                user_data['total_exp'] = user_data.get('exp', 0)
                            
                            # Lưu vào cache
                            cache_manager.set(f"user_{user_id}", user_data)
                            return user_data
                    except:
                        pass
        except Exception as e:
            logging.error(f"Error loading from GitHub: {e}")
            # Fallback to local backup
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
        """Tạo người chơi mới"""
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
        """Thêm user vào queue để save"""
        with self.lock:
            # Update cache
            cache_manager.set(f"user_{user_data['user_id']}", user_data)
            self.save_queue.append(user_data)
    
    def batch_save_to_github(self):
        """Save batch data lên GitHub"""
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
            
            # Update users
            for user_data in users_to_save:
                all_users[user_data['user_id']] = user_data
            
            # Save local backup
            LocalStorage.save_local(all_users)
            
            # Prepare content
            lines = []
            for user_id, data in all_users.items():
                data['user_id'] = user_id
                lines.append(json.dumps(data, ensure_ascii=False))
            
            content = '\n'.join(lines)
            
            # Save to GitHub
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
        """Auto save định kỳ"""
        while True:
            time.sleep(30)  # Save mỗi 30 giây
            if self.save_queue:
                self.executor.submit(self.batch_save_to_github)
    
    def start_auto_save(self):
        """Khởi động auto save thread"""
        save_thread = threading.Thread(target=self.auto_save, daemon=True)
        save_thread.start()
    
    def get_user(self, user_id):
        """Lấy thông tin user với validation"""
        user_data = self.load_user_from_github(user_id)
        # Validate data
        if 'inventory' not in user_data or 'rod' not in user_data['inventory']:
            user_data['inventory'] = {"rod": "1", "fish": {}}
        if user_data['inventory']['rod'] not in FISHING_RODS:
            user_data['inventory']['rod'] = "1"
        if 'total_exp' not in user_data:
            user_data['total_exp'] = user_data.get('exp', 0)
        return user_data
    
    def update_user(self, user_id, data):
        """Update thông tin user"""
        data['user_id'] = str(user_id)
        self.save_user_to_github(data)

# Khởi tạo data manager
data_manager = DataManager()

# ===== HELPER FUNCTIONS =====
def format_number(num):
    """Format số với dấu phẩy"""
    return "{:,}".format(num)

def get_level_title(level):
    """Lấy danh hiệu theo level"""
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
        500: "♾️ Vĩnh hằng",
        1000: "🏆 Tối cao",
        2000: "👑 Chúa tể"
    }
    
    for min_level in sorted(titles.keys(), reverse=True):
        if level >= min_level:
            return titles[min_level]
    return titles[1]

def get_rarity_color(rarity):
    """Lấy icon màu theo độ hiếm"""
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
    """Lấy tên cần câu hiện tại của người chơi"""
    rod_id = user.get('inventory', {}).get('rod', '1')
    if rod_id in FISHING_RODS:
        return FISHING_RODS[rod_id]['name']
    return FISHING_RODS['1']['name']

# ===== GAME FUNCTIONS =====
async def treasure_hunt(user_id):
    """
    Chức năng tìm kho báu
    Chi phí: 50 xu
    Cơ hội thắng: 30%
    Phần thưởng: x3-x10 số xu đặt cược
    """
    user = data_manager.get_user(user_id)
    
    # Kiểm tra xu
    if user["coins"] < 50:
        return None, "❌ Cần 50 xu để tìm kho báu!"
    
    # Trừ xu
    user["coins"] -= 50
    
    # Tính toán kết quả (30% cơ hội thắng)
    win = random.random() < 0.3
    
    if win:
        # Random hệ số nhân từ 3-10
        multiplier = random.uniform(3, 10)
        reward = int(50 * multiplier)
        user["coins"] += reward
        user["treasures_found"] = user.get("treasures_found", 0) + 1
        
        # Cập nhật best multiplier
        if multiplier > user.get("best_multiplier", 0):
            user["best_multiplier"] = round(multiplier, 2)
        
        data_manager.update_user(user_id, user)
        return {
            "success": True,
            "reward": reward,
            "multiplier": round(multiplier, 2),
            "coins": user["coins"]
        }, None
    else:
        data_manager.update_user(user_id, user)
        return {
            "success": False,
            "coins": user["coins"]
        }, None

async def odd_even_game(user_id, choice, bet_amount):
    """
    Chức năng chẵn lẻ
    Người chơi đoán kết quả tung xúc xắc là chẵn hay lẻ
    Thắng: x2 số xu cược
    """
    user = data_manager.get_user(user_id)
    
    # Kiểm tra xu
    if user["coins"] < bet_amount:
        return None, f"❌ Không đủ xu! (Có: {format_number(user['coins'])} xu)"
    
    if bet_amount < 10:
        return None, "❌ Cược tối thiểu 10 xu!"
    
    if bet_amount > 10000:
        return None, "❌ Cược tối đa 10,000 xu!"
    
    # Trừ xu cược
    user["coins"] -= bet_amount
    
    # Tung xúc xắc (1-6)
    dice = random.randint(1, 6)
    dice_is_even = (dice % 2 == 0)
    player_wins = (choice == "even" and dice_is_even) or (choice == "odd" and not dice_is_even)
    
    if player_wins:
        # Thắng x2
        winnings = bet_amount * 2
        user["coins"] += winnings
        user["win_count"] = user.get("win_count", 0) + 1
        
        data_manager.update_user(user_id, user)
        return {
            "success": True,
            "dice": dice,
            "winnings": winnings,
            "coins": user["coins"],
            "choice": choice
        }, None
    else:
        user["lose_count"] = user.get("lose_count", 0) + 1
        data_manager.update_user(user_id, user)
        return {
            "success": False,
            "dice": dice,
            "coins": user["coins"],
            "choice": choice
        }, None

async def process_fishing(user_id, is_auto=False):
    """Xử lý logic câu cá"""
    user = data_manager.get_user(user_id)
    
    if user["coins"] < 10:
        return None, "❌ Cần 10 xu!"
    
    user["coins"] -= 10
    rod_id = user.get('inventory', {}).get('rod', '1')
    if rod_id not in FISHING_RODS:
        rod_id = '1'
    rod_data = FISHING_RODS[rod_id]
    
    current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    
    # Tính toán câu cá với xác suất mượt hơn
    rand = random.uniform(0, 100)
    cumulative = 0
    caught_fish = None
    reward = 0
    exp = 0
    
    # Shuffle để tránh bias
    fish_items = list(FISH_TYPES.items())
    random.shuffle(fish_items)
    
    for fish_name, fish_data in fish_items:
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
        
        # Giảm tỷ lệ cá hiếm khi auto
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
    """Task auto câu cá"""
    count = 0
    total_coins = 0
    total_exp = 0
    fish_caught = {}
    rarity_count = {
        "common": 0, "uncommon": 0, "rare": 0,
        "epic": 0, "legendary": 0, "mythic": 0, "secret": 0
    }
    
    while user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks[user_id]:
        # Kiểm tra resource mỗi 10 lần
        if count % 10 == 0 and not ResourceMonitor.check_resources():
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⛔ **TẠM DỪNG**\nHệ thống quá tải!\nĐã câu {count} lần",
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
                text=f"⛔ **DỪNG AUTO**\n{error}\nĐã câu {count-1} lần\n💰 Thu được: {format_number(total_coins)} xu",
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
        
        # Update UI mỗi lần câu
        user = data_manager.get_user(user_id)
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        rod_id = user.get('inventory', {}).get('rod', '1')
        if rod_id not in FISHING_RODS:
            rod_id = '1'
        rod_data = FISHING_RODS[rod_id]
        
        status_text = f"""
🤖 **AUTO FISHING** 🤖

📊 **Thống kê:**
├ 🔄 Số lần: {count}
├ 💰 Thu được: {format_number(total_coins)} xu
├ ⭐ Tổng EXP: {total_exp}
└ 💰 Xu hiện tại: {format_number(result['coins'] if result else user['coins'])} xu

🏆 **Rank:** {current_rank['name']}
📈 **Buff:** 💰x{current_rank['coin_bonus']} | 🎣x{current_rank['fish_bonus']}

📈 **Độ hiếm đã câu:**
"""
        for rarity, cnt in rarity_count.items():
            if cnt > 0:
                status_text += f"{get_rarity_color(rarity)} {cnt} "
        
        status_text += f"\n\n🎣 **Cần:** {rod_data['name']}"
        status_text += f"\n⏱️ **Tốc độ:** {rod_data['auto_speed']}s"
        
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
            pass  # Ignore telegram flood errors
        
        # Delay theo tốc độ cần câu
        await asyncio.sleep(rod_data['auto_speed'])
    
    # Cleanup
    if user_id in data_manager.auto_fishing_tasks:
        del data_manager.auto_fishing_tasks[user_id]

# ===== TELEGRAM HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /start command"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    user = data_manager.get_user(user_id)
    user["username"] = user_name
    data_manager.update_user(user_id, user)
    
    current_rank, rank_level, next_rank, exp_to_next = get_user_rank(user.get('total_exp', 0))
    stats = ResourceMonitor.get_system_stats()
    next_reset = get_next_sunday()
    
    welcome_text = f"""
🎮 **FISHING GAME BOT** 🎮

👤 **Xin chào {user_name}!**

📊 **Thông tin của bạn:**
├ 💰 Xu: {format_number(user['coins'])}
├ ⭐ Level: {user['level']} - {get_level_title(user['level'])}
├ 🎯 Tổng EXP: {format_number(user.get('total_exp', 0))}
├ 🏆 Rank: {current_rank['name']}
└ 🎣 Cần: {get_current_rod_name(user)}

⏰ **Reset xu:** Chủ nhật {next_reset.strftime('%d/%m %H:%M')} GMT+7

📜 **Commands:**
├ /menu - Menu chính
├ /fish - Câu cá nhanh
├ /rank - Xem hệ thống rank
├ /rods - Shop cần câu
└ /stats - Thống kê cá nhân

💻 **Hệ thống:** CPU {stats['cpu']:.1f}% | RAM {stats['ram']:.1f}%
    """
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /menu command"""
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    
    keyboard = [
        [
            InlineKeyboardButton("🎣 Câu Cá", callback_data='game_fishing'),
            InlineKeyboardButton("🤖 Auto Câu", callback_data='auto_fishing')
        ],
        [
            InlineKeyboardButton("🎣 Shop Cần", callback_data='shop_rods'),
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
            InlineKeyboardButton("🏆 Hệ Thống Rank", callback_data='view_rank'),
            InlineKeyboardButton("🎁 Quà Hàng Ngày", callback_data='daily_reward')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    next_reset = get_next_sunday()
    
    menu_text = f"""
🎮 **MENU CHÍNH** 🎮

👤 **{user['username']}** | Level {user['level']}
💰 **Xu:** {format_number(user['coins'])}
⭐ **EXP:** {format_number(user.get('total_exp', 0))}
🏆 **Rank:** {current_rank['name']}
🎣 **Cần:** {get_current_rod_name(user)}

⏰ **Reset xu:** Chủ nhật {next_reset.strftime('%d/%m')}

Chọn chức năng bên dưới:
    """
    
    await update.message.reply_text(menu_text, reply_markup=reply_markup, parse_mode='Markdown')

async def rank_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /rank command"""
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    
    current_rank, rank_level, next_rank, exp_to_next = get_user_rank(user.get('total_exp', 0))
    
    text = f"""
🏆 **HỆ THỐNG RANK NGƯ HIỆP** 🏆

👤 **{user['username']}**
🎯 **Tổng EXP:** {format_number(user.get('total_exp', 0))}
🏆 **Rank hiện tại:** {current_rank['name']}

📊 **Buff hiện tại:**
├ 💰 Xu câu cá: x{current_rank['coin_bonus']}
└ 🎣 Tỷ lệ cá hiếm: x{current_rank['fish_bonus']}
"""
    
    if next_rank:
        progress = user.get('total_exp', 0) - current_rank['exp_required']
        total_needed = next_rank['exp_required'] - current_rank['exp_required']
        percent = (progress / total_needed * 100) if total_needed > 0 else 0
        
        text += f"""
📈 **Tiến độ lên rank:**
├ Rank tiếp theo: {next_rank['name']}
├ Cần thêm: {format_number(exp_to_next)} EXP
└ Tiến độ: {percent:.1f}%
"""
    else:
        text += "\n👑 **Bạn đã đạt rank cao nhất!**"
    
    text += "\n\n📋 **Danh sách Rank:**"
    
    # Hiển thị rank xung quanh rank hiện tại
    start_rank = max(1, rank_level - 2)
    end_rank = min(len(FISH_RANKS), rank_level + 3)
    
    for level in range(start_rank, end_rank + 1):
        rank_data = FISH_RANKS.get(str(level))
        if rank_data:
            if level <= rank_level:
                text += f"\n✅ {rank_data['name']} - {format_number(rank_data['exp_required'])} EXP"
            else:
                text += f"\n⬜ {rank_data['name']} - {format_number(rank_data['exp_required'])} EXP"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý callback từ các nút bấm"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # === CHỨC NĂNG CẦN CÂU ===
    if data == 'shop_rods':
        """Hiển thị shop cần câu"""
        user = data_manager.get_user(user_id)
        current_rod = user.get('inventory', {}).get('rod', '1')
        owned_rods = user.get('owned_rods', ['1'])
        
        text = f"""
🎣 **SHOP CẦN CÂU** 🎣

💰 **Xu hiện có:** {format_number(user['coins'])}
🎣 **Đang dùng:** {FISHING_RODS[current_rod]['name']}

📋 **Danh sách cần câu:**
"""
        
        keyboard = []
        
        # Hiển thị 5 cần gần nhất với cần hiện tại
        current_rod_num = int(current_rod)
        start_rod = max(1, current_rod_num - 2)
        end_rod = min(len(FISHING_RODS), current_rod_num + 3)
        
        for rod_id in range(start_rod, end_rod + 1):
            rod_id_str = str(rod_id)
            if rod_id_str in FISHING_RODS:
                rod_data = FISHING_RODS[rod_id_str]
                
                if rod_id_str in owned_rods:
                    text += f"\n✅ **{rod_data['name']}**"
                    text += f"\n   {rod_data['description']}"
                    if rod_id_str != current_rod:
                        keyboard.append([InlineKeyboardButton(
                            f"Dùng {rod_data['name']}", 
                            callback_data=f'equip_rod_{rod_id_str}'
                        )])
                else:
                    text += f"\n⬜ **{rod_data['name']}** - {format_number(rod_data['price'])} xu"
                    text += f"\n   {rod_data['description']}"
                    if user['coins'] >= rod_data['price']:
                        keyboard.append([InlineKeyboardButton(
                            f"Mua {rod_data['name']} ({format_number(rod_data['price'])} xu)", 
                            callback_data=f'buy_rod_{rod_id_str}'
                        )])
        
        keyboard.append([InlineKeyboardButton("↩️ Quay lại", callback_data='back_menu')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data.startswith('buy_rod_'):
        """Mua cần câu"""
        rod_id = data.replace('buy_rod_', '')
        user = data_manager.get_user(user_id)
        
        if rod_id not in FISHING_RODS:
            await query.edit_message_text("❌ Cần không tồn tại!")
            return
        
        rod_data = FISHING_RODS[rod_id]
        
        if user['coins'] < rod_data['price']:
            await query.edit_message_text(f"❌ Không đủ xu! Cần {format_number(rod_data['price'])} xu")
            return
        
        # Mua cần
        user['coins'] -= rod_data['price']
        if 'owned_rods' not in user:
            user['owned_rods'] = ['1']
        user['owned_rods'].append(rod_id)
        user['inventory']['rod'] = rod_id
        
        data_manager.update_user(user_id, user)
        
        await query.edit_message_text(
            f"✅ **MUA THÀNH CÔNG!**\n\n{rod_data['name']}\n{rod_data['description']}\n\n💰 Xu còn lại: {format_number(user['coins'])}",
            parse_mode='Markdown'
        )
    
    elif data.startswith('equip_rod_'):
        """Trang bị cần câu"""
        rod_id = data.replace('equip_rod_', '')
        user = data_manager.get_user(user_id)
        
        if rod_id not in user.get('owned_rods', []):
            await query.edit_message_text("❌ Bạn chưa sở hữu cần này!")
            return
        
        user['inventory']['rod'] = rod_id
        data_manager.update_user(user_id, user)
        
        rod_data = FISHING_RODS[rod_id]
        await query.edit_message_text(
            f"✅ **Đã trang bị:** {rod_data['name']}\n\n{rod_data['description']}",
            parse_mode='Markdown'
        )
    
    # === CHỨC NĂNG KHO BÁU ===
    elif data == 'game_treasure':
        """Menu tìm kho báu"""
        user = data_manager.get_user(user_id)
        
        text = f"""
🗺️ **TÌM KHO BÁU** 🗺️

💰 **Xu hiện có:** {format_number(user['coins'])}
🏆 **Đã tìm thấy:** {user.get('treasures_found', 0)} kho báu
🎯 **Kỷ lục:** x{user.get('best_multiplier', 0)}

📋 **Luật chơi:**
├ 💰 Chi phí: 50 xu
├ 🎲 Cơ hội thắng: 30%
├ 💎 Phần thưởng: x3 - x10 tiền cược
└ 🏆 Tối đa có thể nhận: 500 xu

Bạn có muốn thử vận may không?
"""
        
        keyboard = [
            [InlineKeyboardButton("🗺️ Tìm kho báu (50 xu)", callback_data='treasure_hunt')],
            [InlineKeyboardButton("↩️ Quay lại", callback_data='back_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == 'treasure_hunt':
        """Thực hiện tìm kho báu"""
        await query.edit_message_text("🗺️ Đang tìm kiếm kho báu...")
        await asyncio.sleep(2)
        
        result, error = await treasure_hunt(user_id)
        
        if error:
            await query.edit_message_text(error)
            return
        
        if result["success"]:
            text = f"""
🎉 **TÌM THẤY KHO BÁU!** 🎉

💎 **Hệ số nhân:** x{result['multiplier']}
💰 **Phần thưởng:** {format_number(result['reward'])} xu
💰 **Tổng xu:** {format_number(result['coins'])}

Chúc mừng bạn đã tìm thấy kho báu!
"""
        else:
            text = f"""
😢 **KHÔNG TÌM THẤY!**

Kho báu đã bị ai đó lấy mất rồi!

💰 **Xu còn lại:** {format_number(result['coins'])}

Hãy thử lại lần nữa nhé!
"""
        
        keyboard = [
            [InlineKeyboardButton("🗺️ Tìm tiếp", callback_data='treasure_hunt')],
            [InlineKeyboardButton("↩️ Quay lại", callback_data='back_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    # === CHỨC NĂNG CHẴN LẺ ===
    elif data == 'game_chanle':
        """Menu game chẵn lẻ"""
        user = data_manager.get_user(user_id)
        
        text = f"""
🎲 **GAME CHẴN LẺ** 🎲

💰 **Xu hiện có:** {format_number(user['coins'])}
🏆 **Thắng:** {user.get('win_count', 0)} lần
💔 **Thua:** {user.get('lose_count', 0)} lần

📋 **Luật chơi:**
├ 🎲 Tung xúc xắc (1-6)
├ 🎯 Đoán kết quả chẵn hoặc lẻ
├ 💰 Thắng: x2 tiền cược
├ 📉 Cược tối thiểu: 10 xu
└ 📈 Cược tối đa: 10,000 xu

Chọn số xu muốn cược:
"""
        
        keyboard = [
            [
                InlineKeyboardButton("10 xu", callback_data='chanle_bet_10'),
                InlineKeyboardButton("50 xu", callback_data='chanle_bet_50'),
                InlineKeyboardButton("100 xu", callback_data='chanle_bet_100')
            ],
            [
                InlineKeyboardButton("500 xu", callback_data='chanle_bet_500'),
                InlineKeyboardButton("1000 xu", callback_data='chanle_bet_1000'),
                InlineKeyboardButton("5000 xu", callback_data='chanle_bet_5000')
            ],
            [InlineKeyboardButton("↩️ Quay lại", callback_data='back_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data.startswith('chanle_bet_'):
        """Chọn số xu cược"""
        bet_amount = int(data.replace('chanle_bet_', ''))
        
        # Lưu số xu cược vào context
        context.user_data['chanle_bet'] = bet_amount
        
        text = f"💰 **Cược:** {format_number(bet_amount)} xu\n\nChọn CHẴN hoặc LẺ:"
        
        keyboard = [
            [
                InlineKeyboardButton("CHẴN", callback_data='chanle_even'),
                InlineKeyboardButton("LẺ", callback_data='chanle_odd')
            ],
            [InlineKeyboardButton("↩️ Quay lại", callback_data='game_chanle')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data in ['chanle_even', 'chanle_odd']:
        """Thực hiện game chẵn lẻ"""
        choice = 'even' if data == 'chanle_even' else 'odd'
        bet_amount = context
