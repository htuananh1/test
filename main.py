import os, re, json, time, threading, asyncio, queue, requests, io, csv
from collections import deque, defaultdict
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from openai import OpenAI
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
try:
    import PyPDF2
except Exception:
    PyPDF2 = None

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "alibaba/qwen-3-235b")
CODE_MODEL = os.getenv("CODE_MODEL", "anthropic/claude-3.7-sonnet")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash-exp")
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

def build_messages(cid, user_text, sys_prompt):
    msgs=[{"role":"system","content":sys_prompt}]
    keep=max(2, CTX_TURNS*2)
    msgs += [{"role":r,"content":c} for r,c in list(histories[cid])[-keep:]]
    msgs.append({"role":"user","content":user_text})
    return msgs

def complete_with_model(model, messages, max_tokens):
    if not client:
        return "Thiếu VERCEL_API_KEY."
    res = client.chat.completions.create(model=model, max_tokens=max_tokens, temperature=0.7, messages=messages)
    return (res.choices[0].message.content or "").strip()

def _get_gem_client():
    if genai is None or types is None:
        raise RuntimeError("Thiếu package google-genai")
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")
    return genai.Client(api_key=GEMINI_API_KEY)

def create_image_bytes_gemini(prompt: str):
    cli = _get_gem_client()
    resp = cli.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=['TEXT','IMAGE'])
    )
    parts = resp.candidates[0].content.parts if resp and resp.candidates else []
    for part in parts:
        if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
            return part.inline_data.data, part.inline_data.mime_type or "image/png"
    raise RuntimeError("Gemini không trả ảnh.")

def analyze_image_gemini(data: bytes, mime: str, user_hint: str = ""):
    cli = _get_gem_client()
    parts = [types.Part.from_bytes(data=data, mime_type=mime)]
    prompt = "Mô tả ảnh chi tiết, nêu bối cảnh, hành động, đồ vật, chữ hiển thị nếu đọc được. Nói ngắn gọn, trung lập, không khẳng định danh tính người thật nếu không chắc. " + (user_hint or "")
    resp = cli.models.generate_content(model=GEMINI_VISION_MODEL, contents=[*parts, prompt])
    return resp.text.strip() if getattr(resp, "text", None) else "Không phân tích được ảnh."

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

def want_image(t):
    t=(t or "").lower()
    return any(k in t for k in ["tạo ảnh","vẽ","generate image","draw image","vẽ giúp","create image","/img "])

def want_weather(t):
    t=(t or "").lower()
    if "thời tiết" not in t: return None
    known=["hà nội","hn","ha noi","hồ chí minh","tp.hcm","tphcm","sài gòn","đà nẵng","hải phòng","cần thơ","nha trang","đà lạt","huế","quy nhơn","vũng tàu","hạ long","phú quốc","biên hòa","thủ đức"]
    for k in known:
        if k in t: return k
    return "Hà Nội"

def guess_mime_from_name(name: str):
    n=name.lower()
    if n.endswith((".png",".jpg",".jpeg",".webp",".gif")): return "image"
    if n.endswith((".txt",".md",".json",".csv",".log")): return "text"
    if n.endswith(".pdf"): return "pdf"
    return "other"

def read_text_from_bytes(name: str, data: bytes, limit: int = 200_000):
    kind=guess_mime_from_name(name)
    if kind=="text":
        try:
            return data.decode("utf-8", errors="ignore")[:limit]
        except Exception:
            return data.decode("latin-1", errors="ignore")[:limit]
    if kind=="pdf":
        if not PyPDF2: return "Không có PyPDF2 để đọc PDF."
        buf=io.BytesIO(data); r=PyPDF2.PdfReader(buf)
        parts=[]
        for i in range(min(len(r.pages), 50)):
            try:
                parts.append(r.pages[i].extract_text() or "")
            except Exception:
                parts.append("")
        return "\n".join(parts)[:limit] or "PDF không trích được chữ."
    return None

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Lệnh:\n"
        "/help – Hỗ trợ lệnh\n"
        "/img <mô tả> – tạo ảnh (Gemini)\n"
        "/weather <địa danh VN> – thời tiết\n"
        "/code <yêu cầu> – code (Claude)\n"
        "Gửi ảnh để phân tích nội dung.\n"
        "Gửi file .txt/.md/.json/.csv/.pdf để đọc và tóm tắt.\n"
        "BOT được tạo bởi (@cuocdoivandep)\n"
    )
    await update.message.reply_text(txt)

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    if not prompt:
        return await update.message.reply_text("Dùng: /img <mô tả>")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    try:
        data, mime = create_image_bytes_gemini(prompt)
        buf = io.BytesIO(data); buf.name = "gen.png"
        await context.bot.send_photo(chat_id, buf, caption=prompt)
    except Exception as e:
        await update.message.reply_text(f"Lỗi tạo ảnh: {e}")

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    place = " ".join(context.args).strip() or "Hà Nội"
    try:
        txt = weather_vn(place)
        await start_pager(context, update.effective_chat.id, txt, is_code=False)
    except Exception:
        await update.message.reply_text("Lỗi lấy thời tiết.")

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = " ".join(context.args).strip()
    if not q:
        return await update.message.reply_text("Dùng: /code <yêu cầu>")
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            msgs = build_messages(chat_id, q, sys_prompt="Bạn là lập trình viên kỳ cựu. Viết code đầy đủ, sạch, best practice. Không giới hạn độ dài; nếu dài, cứ trả hết.")
            result = complete_with_model(CODE_MODEL, msgs, MAX_TOKENS_CODE) or "..."
            m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
            if m: await start_pager(context, chat_id, m.group(2).rstrip(), is_code=True, lang_hint=m.group(1) or "")
            else: await start_pager(context, chat_id, result, is_code=True)
            histories[chat_id].append(("user", q))
            histories[chat_id].append(("assistant", result[:1000]))
        except Exception:
            await update.message.reply_text("Lỗi kết nối.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    q = update.message.text or ""
    if want_image(q):
        prompt = re.sub(r"(?i)(tạo ảnh|vẽ|generate image|draw image|vẽ giúp|create image|/img)[:\-]*", "", q).strip() or "A cute cat in space suit, 3D render"
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        try:
            data, mime = create_image_bytes_gemini(prompt)
            buf = io.BytesIO(data); buf.name = "gen.png"
            await context.bot.send_photo(chat_id, buf, caption=prompt)
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
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            msgs = build_messages(chat_id, q, sys_prompt="Bạn là Linh – mồm mép, bộc trực kiểu Grok; trả lời ngắn gọn, tự nhiên.")
            result = complete_with_model(CHAT_MODEL, msgs, MAX_TOKENS) or "..."
            await start_pager(context, chat_id, result, is_code=False)
            histories[chat_id].append(("user", q))
            histories[chat_id].append(("assistant", result[:1000]))
        except Exception:
            await update.message.reply_text("Lỗi kết nối.")

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        ph = update.message.photo[-1]
        f = await context.bot.get_file(ph.file_id)
        bio = io.BytesIO()
        await f.download_to_memory(out=bio)
        data=bio.getvalue()
        desc = analyze_image_gemini(data, "image/jpeg")
        await start_pager(context, chat_id, desc, is_code=False)
    except Exception as e:
        await update.message.reply_text(f"Lỗi phân tích ảnh: {e}")

async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    doc = update.message.document
    name = doc.file_name or "file"
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        f = await context.bot.get_file(doc.file_id)
        bio = io.BytesIO()
        await f.download_to_memory(out=bio)
        data=bio.getvalue()
        kind = guess_mime_from_name(name)
        if kind=="image":
            desc = analyze_image_gemini(data, doc.mime_type or "image/*")
            return await start_pager(context, chat_id, f"Ảnh: {name}\n\n{desc}", is_code=False)
        text = read_text_from_bytes(name, data)
        if text is None:
            return await update.message.reply_text("File này chưa hỗ trợ. Thử .txt/.md/.json/.csv/.pdf hoặc gửi ảnh.")
        sys = "Từ nội dung sau, tóm tắt gọn, nêu mục chính, liệt kê dữ kiện quan trọng, chỉ ra điểm bất thường nếu có."
        msgs = [{"role":"system","content":sys},{"role":"user","content":text[:15000]}]
        summary = complete_with_model(CHAT_MODEL, msgs, MAX_TOKENS) if client else text[:PAGE_CHARS]
        await start_pager(context, chat_id, f"Tóm tắt {name}:\n\n{summary}", is_code=False)
    except Exception as e:
        await update.message.reply_text(f"Lỗi đọc file: {e}")

def main():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("help", cmd_help))
    app_tg.add_handler(CommandHandler("img", cmd_img))
    app_tg.add_handler(CommandHandler("weather", cmd_weather))
    app_tg.add_handler(CommandHandler("code", cmd_code))
    app_tg.add_handler(CallbackQueryHandler(on_page_nav, pattern=r"^pg_"))
    app_tg.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app_tg.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    app_tg.run_polling()

if __name__ == "__main__":
    main()
