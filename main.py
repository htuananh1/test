import os, re, json, time, threading, asyncio, queue, requests, io
from collections import deque, defaultdict
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from openai import OpenAI
try:
    from google import genai
except ImportError:
    genai = None

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
MODEL = os.getenv("MODEL", "alibaba/qwen-3-235b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")
PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "7"))

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL) if VERCEL_API_KEY else None
app = Flask(__name__)
histories = defaultdict(lambda: deque(maxlen=32))
locks = defaultdict(asyncio.Lock)
PAGERS = {}

def chunk_pages(raw, per_page=PAGE_CHARS):
    lines = (raw or "").splitlines(); pages=[]; cur=[]; used=0
    for line in lines:
        add=len(line)+1
        if used+add>per_page and cur:
            pages.append("\n".join(cur)); cur=[line]; used=add
        else:
            cur.append(line); used+=add
    if cur: pages.append("\n".join(cur))
    return pages or [""]

def kb(idx,total):
    return None if total<=1 else InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏪", callback_data="pg_prev"),
          InlineKeyboardButton(f"{idx+1}/{total}", callback_data="pg_stay"),
          InlineKeyboardButton("⏩", callback_data="pg_next")]]
    )

def page_payload(p):
    txt=p["pages"][p["idx"]]
    return (f"```{p['lang']}\n{txt}\n```", ParseMode.MARKDOWN) if p["is_code"] else (txt, ParseMode.HTML)

async def send_or_update(ctx, chat_id, msg, p):
    text,mode = page_payload(p); keyboard = kb(p["idx"], len(p["pages"]))
    if msg: await msg.edit_text(text, parse_mode=mode, reply_markup=keyboard)
    else:
        m = await ctx.bot.send_message(chat_id, text, parse_mode=mode, reply_markup=keyboard)
        PAGERS[(m.chat_id, m.message_id)] = p

async def start_pager(ctx, chat_id, raw, is_code=False, lang_hint=""):
    pages = chunk_pages(raw)
    await send_or_update(ctx, chat_id, None, {"pages": pages, "is_code": is_code, "lang": lang_hint or "", "idx": 0})

async def on_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    key=(q.message.chat_id, q.message.message_id); p=PAGERS.get(key)
    if not p: return await q.answer("Hết phiên.")
    if q.data=="pg_prev" and p["idx"]>0: p["idx"]-=1
    elif q.data=="pg_next" and p["idx"]<len(p["pages"])-1: p["idx"]+=1
    else: return await q.answer()
    await send_or_update(context, q.message.chat_id, q.message, p); await q.answer()

def is_codey(t):
    if not t: return False
    t=t.lower(); keys=["```","import ","class ","def ","function","const ","let ","var ","#include","public static","<script","</script>"]
    return any(k in t for k in keys)

def build_messages(cid, user_text, code_mode=False):
    sys_prompt = ("Bạn là lập trình viên kỳ cựu. Viết code đầy đủ, sạch, best practice. Không giới hạn độ dài; nếu dài, cứ trả hết."
                  if code_mode else
                  "Bạn là Linh – mồm mép, bộc trực kiểu Grok; trả lời ngắn gọn, tự nhiên.")
    msgs=[{"role":"system","content":sys_prompt}]
    keep=max(2, CTX_TURNS*2)
    msgs += [{"role":r,"content":c} for r,c in list(histories[cid])[-keep:]]
    msgs.append({"role":"user","content":user_text})
    return msgs

def complete_block(messages, max_tokens):
    if not client:
        return "Chưa cấu hình VERCEL_API_KEY cho chat."
    res = client.chat.completions.create(model=MODEL, max_tokens=max_tokens, temperature=0.7, messages=messages)
    return (res.choices[0].message.content or "").strip()

def create_image_url_via_gateway(prompt, size="1024x1024"):
    if not VERCEL_API_KEY:
        return None
    url = f"{BASE_URL}/images/generations"
    headers = {"Authorization": f"Bearer {VERCEL_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "prompt": prompt, "size": size}
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    j=r.json()
    return (j.get("data") or [{}])[0].get("url")

_gem_client = None
def _get_gem_client():
    global _gem_client
    if _gem_client is None:
        if genai is None:
            raise RuntimeError("Thiếu package google-genai. Cài: pip install google-genai")
        if not GEMINI_API_KEY:
            raise RuntimeError("Thiếu GEMINI_API_KEY.")
        _gem_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gem_client

def create_image_bytes_gemini(prompt: str, size: str = "1024x1024"):
    w,h = (int(x) for x in size.lower().split("x"))
    cli = _get_gem_client()
    resp = cli.models.generate_images(
        model=GEMINI_IMAGE_MODEL,
        prompt=prompt,
        image_size={"width": w, "height": h},
        safety_filter_level="block_few",
    )
    if not getattr(resp, "generated_images", None):
        raise RuntimeError("Gemini không trả ảnh.")
    img = resp.generated_images[0]
    mime = img.mime_type or "image/png"
    data = img.image_bytes
    return data, mime

def want_image(t):
    t=(t or "").lower()
    return any(k in t for k in ["tạo ảnh","vẽ","generate image","draw image","vẽ giúp","create image","/img "])

def geocode_vn(q):
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": q, "count": 1, "language":"vi", "format":"json", "country_code":"VN"},
                     timeout=20)
    r.raise_for_status(); data=r.json()
    if not data.get("results"): return None
    it=data["results"][0]
    return {"name":it["name"],"lat":it["latitude"],"lon":it["longitude"],"admin1":it.get("admin1","")}

def weather_vn(q):
    g=geocode_vn(q)
    if not g: return "Không tìm thấy địa danh ở Việt Nam."
    params={"latitude":g["lat"],"longitude":g["lon"],
            "current":"temperature_2m,relative_humidity_2m,precipitation,apparent_temperature,wind_speed_10m",
            "daily":"temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
            "timezone":"Asia/Ho_Chi_Minh"}
    r=requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
    r.raise_for_status(); j=r.json()
    cur=j.get("current",{}); daily=j.get("daily",{})
    name=g["name"]+(f", {g['admin1']}" if g.get("admin1") else "")
    t=cur.get("temperature_2m"); feels=cur.get("apparent_temperature"); rh=cur.get("relative_humidity_2m")
    ws=cur.get("wind_speed_10m"); p=cur.get("precipitation")
    tmax0=daily.get("temperature_2m_max",[None])[0]; tmin0=daily.get("temperature_2m_min",[None])[0]
    rain0=daily.get("precipitation_sum",[None])[0]; prob0=daily.get("precipitation_probability_max",[None])[0]
    tmax1=daily.get("temperature_2m_max",[None,None])[1]; tmin1=daily.get("temperature_2m_min",[None,None])[1]
    rain1=daily.get("precipitation_sum",[None,None])[1]; prob1=daily.get("precipitation_probability_max",[None,None])[1]
    icon="☀️"
    if (prob0 or 0)>=70 or (rain0 or 0)>=5: icon="🌧️"
    elif (prob0 or 0)>=30: icon="🌦️"
    elif (t or 0)>=33: icon="🥵"
    return (f"{icon} Thời tiết {name}\n"
            f"Hiện tại: {t}°C (cảm giác {feels}°C), ẩm {rh}%, gió {ws} km/h, mưa {p} mm\n"
            f"Hôm nay: {tmin0}–{tmax0}°C, mưa ~{rain0} mm, xác suất {prob0}%\n"
            f"Ngày mai: {tmin1}–{tmax1}°C, mưa ~{rain1} mm, xác suất {prob1}%")

def want_weather(t):
    t=(t or "").lower()
    if "thời tiết" not in t: return None
    known=["hà nội","hn","ha noi","hồ chí minh","tp.hcm","tphcm","sài gòn","đà nẵng","hải phòng","cần thơ","nha trang","đà lạt","huế","quy nhơn","vũng tàu","hạ long","phú quốc","biên hòa","thủ đức"]
    for k in known:
        if k in t: return k
    return "Hà Nội"

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    if not prompt:
        return await update.message.reply_text("Dùng: /img <mô tả>")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    use_gemini = bool(GEMINI_API_KEY)
    try:
        if use_gemini:
            data, mime = create_image_bytes_gemini(prompt, size="1024x1024")
            buf = io.BytesIO(data); buf.name = "gen.png"
            await context.bot.send_photo(chat_id, buf, caption=prompt)
        else:
            url = create_image_url_via_gateway(prompt)
            if url: await context.bot.send_photo(chat_id, url, caption=prompt)
            else:   await update.message.reply_text("Không có GEMINI_API_KEY, và gateway không hỗ trợ images.")
    except Exception as e:
        await update.message.reply_text(f"Lỗi tạo ảnh: {e}")

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    place = " ".join(context.args).strip() or "Hà Nội"
    try:
        txt = weather_vn(place)
        await start_pager(context, update.effective_chat.id, txt, is_code=False)
    except Exception:
        await update.message.reply_text("Lỗi lấy thời tiết.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = update.message.text or ""
    if want_image(q):
        prompt = re.sub(r"(?i)(tạo ảnh|vẽ|generate image|draw image|vẽ giúp|create image|/img)[:\-]*", "", q).strip() or "A cute cat in space suit, 3D render"
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        try:
            if GEMINI_API_KEY:
                data, mime = create_image_bytes_gemini(prompt, size="1024x1024")
                buf = io.BytesIO(data); buf.name = "gen.png"
                await context.bot.send_photo(chat_id, buf, caption=prompt)
            else:
                url = create_image_url_via_gateway(prompt)
                if url: await context.bot.send_photo(chat_id, url, caption=prompt)
                else:   await update.message.reply_text("Không có GEMINI_API_KEY, và gateway không hỗ trợ images.")
        except Exception as e:
            return await update.message.reply_text(f"Lỗi tạo ảnh: {e}")
        return
    place = want_weather(q)
    if place:
        try:
            txt = weather_vn(place)
            return await start_pager(context, chat_id, txt, is_code=False)
        except Exception:
            return await update.message.reply_text("Lỗi lấy thời tiết.")
    code_mode = is_codey(q)
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            msgs = build_messages(chat_id, q, code_mode=code_mode)
            result = complete_block(msgs, MAX_TOKENS_CODE if code_mode else MAX_TOKENS) or "..."
            if code_mode:
                m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
                if m: await start_pager(context, chat_id, m.group(2).rstrip(), is_code=True, lang_hint=m.group(1) or "")
                else: await start_pager(context, chat_id, result, is_code=True)
            else:
                await start_pager(context, chat_id, result, is_code=False)
            histories[chat_id].append(("user", q))
            histories[chat_id].append(("assistant", result[:1000]))
        except Exception:
            await update.message.reply_text("Lỗi kết nối.")

def main():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("img", cmd_img))
    app_tg.add_handler(CommandHandler("weather", cmd_weather))
    app_tg.add_handler(CallbackQueryHandler(on_page_nav, pattern=r"^pg_"))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    app_tg.run_polling()

if __name__ == "__main__":
    main()
