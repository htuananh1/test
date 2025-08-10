import os, re, json, time, threading, shutil, sys, traceback, asyncio, queue, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import deque, defaultdict
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from openai import OpenAI

# ================== ENV ==================
BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ["VERCEL_API_KEY"]
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
MODEL = os.getenv("MODEL", "alibaba/qwen-3-235b")  # dùng CHUNG cho chat + image

PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "7"))

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL)

app = Flask(__name__)
histories = defaultdict(lambda: deque(maxlen=32))
locks = defaultdict(asyncio.Lock)
PAGERS = {}

# ================== Pager (1 message, nhiều trang) ==================
def chunk_pages(raw: str, per_page: int = PAGE_CHARS):
    lines = (raw or "").splitlines()
    pages, cur, used = [], [], 0
    for line in lines:
        add = len(line) + 1
        if used + add > per_page and cur:
            pages.append("\n".join(cur)); cur=[line]; used=add
        else:
            cur.append(line); used += add
    if cur: pages.append("\n".join(cur))
    return pages

def make_kb(idx: int, total: int):
    if total <= 1: return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏪", callback_data="pg_prev"),
                                  InlineKeyboardButton(f"{idx+1}/{total}", callback_data="pg_stay"),
                                  InlineKeyboardButton("⏩", callback_data="pg_next")]])

def page_payload(pager):
    page = pager["pages"][pager["idx"]]
    if pager["is_code"]:
        return f"```{pager['lang']}\n{page}\n```", ParseMode.MARKDOWN
    else:
        return page, ParseMode.HTML

async def send_or_update_page(ctx, chat_id, message, pager):
    text, parse_mode = page_payload(pager)
    kb = make_kb(pager["idx"], len(pager["pages"]))
    if message:
        await message.edit_text(text, parse_mode=parse_mode, reply_markup=kb)
    else:
        msg = await ctx.bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=kb)
        PAGERS[(msg.chat_id, msg.message_id)] = pager

async def start_pager(ctx, chat_id, raw: str, *, is_code=False, lang_hint=""):
    pages = chunk_pages(raw) if len(raw) > PAGE_CHARS else [raw]
    pager = {"pages": pages, "is_code": is_code, "lang": lang_hint or "", "idx": 0}
    await send_or_update_page(ctx, chat_id, None, pager)

async def on_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    key = (q.message.chat_id, q.message.message_id)
    pager = PAGERS.get(key)
    if not pager: await q.answer("Hết phiên."); return
    if q.data == "pg_prev" and pager["idx"] > 0: pager["idx"] -= 1
    elif q.data == "pg_next" and pager["idx"] < len(pager["pages"]) - 1: pager["idx"] += 1
    else: await q.answer(); return
    await send_or_update_page(context, q.message.chat_id, q.message, pager)
    await q.answer()

# ================== Helpers ==================
def is_codey(text):
    if not text: return False
    t = text.lower()
    keys = ["```","import ","class ","def ","function","const ","let ","var ","#include","public static","<script","</script>"]
    return any(k in t for k in keys)

def build_messages(chat_id, user_text, code_mode=False):
    sys_prompt = ("Bạn là lập trình viên kỳ cựu. Viết code đầy đủ, sạch, best practice. Không giới hạn độ dài; nếu dài, cứ trả hết."
                  if code_mode else
                  "Bạn là Linh – mồm mép, bộc trực, thông minh kiểu Grok; nhanh trí, châm biếm duyên dáng; trả lời gọn, tự nhiên.")
    msgs = [{"role": "system", "content": sys_prompt}]
    keep = max(2, CTX_TURNS * 2)
    msgs.extend({"role": r, "content": c} for r, c in list(histories[chat_id])[-keep:])
    msgs.append({"role": "user", "content": user_text})
    return msgs

def complete_block(messages, max_tokens):
    cmp = client.chat.completions.create(model=MODEL, max_tokens=max_tokens, temperature=0.7, messages=messages)
    return (cmp.choices[0].message.content or "").strip()

def detect_image_intent(text: str):
    if not text: return None
    t = text.lower()
    keys = ["tạo ảnh","vẽ","generate image","draw image","vẽ giúp","create image"]
    return any(k in t for k in keys)

def detect_weather_intent(text: str):
    t = (text or "").lower()
    if "thời tiết" not in t: return None
    known = ["hà nội","hn","ha noi","hồ chí minh","tp.hcm","tphcm","sài gòn","đà nẵng","hải phòng","cần thơ","nha trang","đà lạt","huế","quy nhơn","vũng tàu","hạ long","phú quốc","biên hòa","thủ đức"]
    for k in known:
        if k in t: return k
    return "Hà Nội"

# ================== Image (dùng CHUNG MODEL) ==================
def create_image(prompt: str, size: str = "1024x1024"):
    url = f"{BASE_URL}/images/generations"
    headers = {"Authorization": f"Bearer {VERCEL_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "prompt": prompt, "size": size}  # dùng chung MODEL
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    j = r.json()
    if "data" in j and j["data"]:
        return j["data"][0].get("url")
    return None

# ================== Weather (VN) ==================
def geocode_vn(q):
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": q, "count": 1, "language": "vi", "format": "json", "country_code": "VN"},
                     timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("results"): return None
    it = data["results"][0]
    return {"name": it["name"], "lat": it["latitude"], "lon": it["longitude"], "admin1": it.get("admin1","")}

def weather_vn(q):
    g = geocode_vn(q)
    if not g: return "Không tìm thấy địa danh ở Việt Nam."
    params = {
        "latitude": g["lat"], "longitude": g["lon"],
        "current": "temperature_2m,relative_humidity_2m,precipitation,apparent_temperature,wind_speed_10m",
        "hourly": "temperature_2m,precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
        "timezone": "Asia/Ho_Chi_Minh"
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
    r.raise_for_status()
    j = r.json()
    cur = j.get("current", {})
    daily = j.get("daily", {})
    name = g["name"] + (f", {g['admin1']}" if g.get("admin1") else "")
    t = cur.get("temperature_2m"); rh = cur.get("relative_humidity_2m")
    feels = cur.get("apparent_temperature"); ws = cur.get("wind_speed_10m"); p = cur.get("precipitation")
    tmax0 = daily.get("temperature_2m_max",[None])[0]; tmin0 = daily.get("temperature_2m_min",[None])[0]
    rain0 = daily.get("precipitation_sum",[None])[0]; prob0 = daily.get("precipitation_probability_max",[None])[0]
    tmax1 = daily.get("temperature_2m_max",[None, None])[1]; tmin1 = daily.get("temperature_2m_min",[None, None])[1]
    rain1 = daily.get("precipitation_sum",[None, None])[1]; prob1 = daily.get("precipitation_probability_max",[None, None])[1]
    icon = "☀️"
    if (prob0 or 0) >= 70 or (rain0 or 0) >= 5: icon = "🌧️"
    elif (prob0 or 0) >= 30: icon = "🌦️"
    elif (t or 0) >= 33: icon = "🥵"
    return (f"{icon} Thời tiết {name}\n"
            f"Hiện tại: {t}°C (cảm giác {feels}°C), ẩm {rh}%, gió {ws} km/h, mưa {p} mm\n"
            f"Hôm nay: {tmin0}–{tmax0}°C, mưa ~{rain0} mm, xác suất {prob0}%\n"
            f"Ngày mai: {tmin1}–{tmax1}°C, mưa ~{rain1} mm, xác suất {prob1}%")

# ================== Commands ==================
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("Dùng: /img <mô tả>")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    try:
        url = create_image(prompt)
        if url: await context.bot.send_photo(chat_id, url, caption=prompt)
        else: await update.message.reply_text("Tạo ảnh thất bại (model không hỗ trợ images?).")
    except Exception:
        await update.message.reply_text("Lỗi tạo ảnh.")

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    place = " ".join(context.args).strip() or "Hà Nội"
    try:
        text = weather_vn(place)
        await start_pager(context, chat_id, text, is_code=False)
    except Exception:
        await update.message.reply_text("Lỗi lấy thời tiết.")

# ================== Message ==================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = update.message.text or ""

    if detect_image_intent(q):
        prompt = re.sub(r"(?i)(tạo ảnh|vẽ|generate image|draw image|vẽ giúp|create image)[:\-]*", "", q).strip() or "A cute cat in space suit, 3D render"
        await cmd_img(update, context.__class__(application=context.application, args=[prompt], bot=context.bot, chat_data=context.chat_data, user_data=context.user_data, update_queue=context.update_queue, job_queue=context.job_queue))
        return

    place = detect_weather_intent(q)
    if place:
        await cmd_weather(update, context.__class__(application=context.application, args=[place], bot=context.bot, chat_data=context.chat_data, user_data=context.user_data, update_queue=context.update_queue, job_queue=context.job_queue))
        return

    code_mode = is_codey(q)
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            messages = build_messages(chat_id, q, code_mode=code_mode)
            result = complete_block(messages, MAX_TOKENS_CODE if code_mode else MAX_TOKENS) or "..."
            if code_mode:
                m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
                if m:
                    await start_pager(context, chat_id, m.group(2).rstrip(), is_code=True, lang_hint=m.group(1) or "")
                else:
                    await start_pager(context, chat_id, result, is_code=True)
            else:
                await start_pager(context, chat_id, result, is_code=False)

            histories[chat_id].append(("user", q))
            histories[chat_id].append(("assistant", result[:1000]))
        except Exception:
            await update.message.reply_text("Lỗi kết nối.")

# ================== Boot ==================
def main():
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("img", cmd_img))
    app_tg.add_handler(CommandHandler("weather", cmd_weather))
    app_tg.add_handler(CallbackQueryHandler(on_page_nav, pattern=r"^pg_"))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app_tg.run_polling()

if __name__ == "__main__":
    main()
