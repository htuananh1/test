import os, re, json, time, threading, shutil, sys, traceback, asyncio, queue, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import deque, defaultdict
from flask import Flask
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters,
    CommandHandler, CallbackQueryHandler, Defaults
)
from openai import OpenAI

# ========== ENV ==========
BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ["VERCEL_API_KEY"]
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
MODEL = os.getenv("MODEL", "openai/gpt-5")

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT",
    "Bạn là Linh – mồm mép, bộc trực, thông minh kiểu Grok: nhanh trí, châm biếm duyên dáng, thỉnh thoảng cà khịa nhẹ cho tỉnh ngủ. "
    "Giọng tự nhiên, có thể dùng tiếng lóng/chửi nhẹ đúng lúc (không tục, không 18+). Ưu tiên ngắn gọn, sắc sảo; luôn hữu ích và chính xác."
)
SYSTEM_PROMPT_CODE = os.getenv("SYSTEM_PROMPT_CODE",
    "Bạn là một lập trình viên kỳ cựu. Viết code đầy đủ, sạch, chuẩn best practice, giải thích ngắn gọn. Không giới hạn độ dài; nếu dài, cứ trả hết."
)

WORD_LIMIT = int(os.getenv("WORD_LIMIT", "350"))
SELF_PING_URL = os.getenv("SELF_PING_URL", "").strip()

# quyền & phạm vi
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "0"))   # 0 = mọi group
ALLOWED_TOPIC_ID = int(os.getenv("ALLOWED_TOPIC_ID", "0")) # 0 = mọi topic
OWNER_ID = 2026797305                                      # chỉ ID này được /set

# tiện ích
REMIND_CHAT_IDS = [s.strip() for s in os.getenv("REMIND_CHAT_IDS", "").split(",") if s.strip()]
REMIND_TEXT = os.getenv("REMIND_TEXT", "23h rồi đó, ngủ sớm cho khoẻ nha 🌙")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
CLEAN_INTERVAL_HOURS = int(os.getenv("CLEAN_INTERVAL_HOURS", "6"))

# LLM & buffer
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "6"))  # số lượt cũ (user+assistant)
MAX_DOC_BYTES = int(os.getenv("MAX_DOC_BYTES", str(2 * 1024 * 1024)))

# stream & phân trang
EDIT_INTERVAL = float(os.getenv("EDIT_INTERVAL", "1.0"))
MAX_EDITS = int(os.getenv("MAX_EDITS", "60"))
PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL)
app = Flask(__name__)

histories = defaultdict(lambda: deque(maxlen=32))    # lịch sử hội thoại
locks = defaultdict(asyncio.Lock)

# session cho code + pager theo (chat_id, topic_id)
# ví dụ: sessions[(chat, topic)] = {mode, prompt, buffer, explain, pages, page_idx, page_header, page_msg_id}
sessions: dict[tuple[int, int | None], dict] = {}

# ========== Utils ==========
def log_console(tag, payload):
    try: print(f"[{datetime.utcnow().isoformat()}][{tag}] {json.dumps(payload, ensure_ascii=False)}")
    except Exception: print(f"[{datetime.utcnow().isoformat()}][{tag}] {payload}")
    sys.stdout.flush()

def notify_discord(title, payload):
    if DISCORD_WEBHOOK_URL:
        try:
            text = f"**{title}**\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}```"
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=15)
        except Exception: pass
    log_console(title, payload)

def strip_code(s):  # bỏ fence ```
    return re.sub(r"```[\w-]*\n|\n```", "", s or "", flags=re.S).strip()

def word_clamp(s, limit):
    w=(s or "").split()
    return s if len(w)<=limit else " ".join(w[:limit])+"…"

def html_escape(s:str) -> str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def pretty_text(s: str, max_lines: int = 10) -> str:
    s = strip_code(s)
    lines = [l.strip() for l in (s or "").splitlines() if l.strip()]
    return "\n".join(lines[:max_lines])

def head_body_html(text: str) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines: return "…"
    head = f"<b>{html_escape(lines[0])}</b>"
    body = "\n".join(html_escape(l) for l in lines[1:])
    return head + ("\n" + body if body else "")

def paginate_html(full_text: str, per_page: int = PAGE_CHARS) -> list[str]:
    safe = html_escape(full_text or "")
    pages, cur, used = [], [], 0
    for line in safe.splitlines():
        if used + len(line) + 1 > per_page and cur:
            pages.append("\n".join(cur)); cur=[line]; used=len(line)+1
        else:
            cur.append(line); used += len(line)+1
    if cur: pages.append("\n".join(cur))
    return pages

def current_thread_id(update: Update) -> int | None:
    msg = update.effective_message
    return getattr(msg, "message_thread_id", None)

def session_key(update_or_ids) -> tuple[int, int | None]:
    if isinstance(update_or_ids, Update):
        return (update_or_ids.effective_chat.id, current_thread_id(update_or_ids))
    chat_id, thread_id = update_or_ids
    return (chat_id, thread_id)

def allowed_chat(update: Update):
    chat = update.effective_chat
    if not chat: return False
    if chat.type == "private":
        return update.effective_user and update.effective_user.id == OWNER_ID
    if chat.type in ("group","supergroup"):
        if ALLOWED_CHAT_ID and chat.id != ALLOWED_CHAT_ID:
            return False
        if ALLOWED_TOPIC_ID:
            return (current_thread_id(update) or 0) == ALLOWED_TOPIC_ID
        return True
    return False

def asked_creator(text):
    t=(text or "").lower()
    return any(k in t for k in ["ai tạo","người tạo","ai làm ra","người làm ra","tác giả","dev của bạn"])

def is_codey(text):
    if not text: return False
    t = text.lower()
    keys = ["viết code","code giúp","sửa code","bug","lỗi","stack trace","exception",
        "python","java","kotlin","swift","dart","flutter","go","rust","c++","c#","php","ruby",
        "js","ts","typescript","node","react","vue","svelte","angular","next.js","nuxt",
        "`","```","import ","class ","def ","function","const ","let ","var "]
    return any(k in t for k in keys)

# keepalive + health
@app.get("/")
def root_ok(): return "OK"
@app.get("/health")
def health_ok(): return "OK"

def auto_ping():
    while True:
        if SELF_PING_URL:
            try: requests.head(SELF_PING_URL, timeout=10)
            except Exception: pass
        time.sleep(45)

def cleanup_disk():
    freed=0
    for p in ["/home/runner/.cache","/home/runner/.npm","/tmp"]:
        try:
            if os.path.exists(p):
                size=sum(os.path.getsize(os.path.join(dp,f)) for dp,_,fs in os.walk(p) for f in fs)
                shutil.rmtree(p, ignore_errors=True); freed+=size
        except Exception: pass
    return freed

def cleanup_loop():
    next_run=datetime.utcnow()
    while True:
        if datetime.utcnow()>=next_run:
            b=cleanup_disk()
            notify_discord("cleanup_done", {"freed_bytes": b})
            next_run=datetime.utcnow()+timedelta(hours=CLEAN_INTERVAL_HOURS)
        time.sleep(60)

def reminder_loop(bot, chat_ids):
    tz=ZoneInfo("Asia/Ho_Chi_Minh"); last_sent=None
    while True:
        now=datetime.now(tz)
        if now.hour==23 and last_sent!=now.date():
            for cid in chat_ids:
                try: bot.send_message(chat_id=cid, text=REMIND_TEXT)
                except Exception as e: notify_discord("remind_error", {"chat_id": cid, "error": str(e)})
            last_sent=now.date()
        time.sleep(20)

# ========== Keyboards ==========
def make_code_kb(explain: bool):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Tiếp code", callback_data="CODE_MORE")],
        [
            InlineKeyboardButton("📝 Giải thích" if not explain else "💻 Chỉ code",
                                 callback_data="CODE_TOGGLE_EXPLAIN"),
            InlineKeyboardButton("🔁 Regenerate", callback_data="CODE_REGEN"),
        ],
    ])

def make_pager_kb(idx: int, total: int):
    left_disabled  = idx <= 0
    right_disabled = idx >= total - 1
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⏪", callback_data="PAGE_PREV" if not left_disabled else "NOP"),
        InlineKeyboardButton(f"{idx+1}/{total}", callback_data="NOP"),
        InlineKeyboardButton("⏩", callback_data="PAGE_NEXT" if not right_disabled else "NOP"),
    ]])

async def pager_send_first(ctx, chat_id, pages: list[str], header: str, thread_id=None):
    key = (chat_id, thread_id)
    if not pages:
        await ctx.bot.send_message(chat_id, f"<b>{header}</b>", message_thread_id=thread_id)
        return
    idx = 0
    kb = make_pager_kb(idx, len(pages))
    msg = await ctx.bot.send_message(
        chat_id, f"<b>{header}</b>\n{pages[idx]}",
        reply_markup=kb, message_thread_id=thread_id
    )
    sess = sessions.get(key, {})
    sess.update({"pages": pages, "page_idx": idx, "page_header": header, "page_msg_id": msg.message_id})
    sessions[key] = sess

async def pager_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE, direction: int):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat.id
    thread_id = getattr(q.message, "message_thread_id", None)
    key = (chat_id, thread_id)
    sess = sessions.get(key) or {}
    pages = sess.get("pages")
    if not pages:
        return
    idx = max(0, min(len(pages)-1, sess.get("page_idx", 0) + direction))
    sess["page_idx"] = idx
    sessions[key] = sess
    kb = make_pager_kb(idx, len(pages))
    try:
        await q.edit_message_text(f"<b>{sess.get('page_header','📄 Phần')}</b>\n{pages[idx]}", reply_markup=kb)
    except Exception:
        await ctx.bot.send_message(chat_id,
            f"<b>{sess.get('page_header','📄 Phần')}</b>\n{pages[idx]}",
            reply_markup=kb, message_thread_id=thread_id
        )

# ========== LLM ==========
def build_messages(chat_id, user_text, code_mode=False):
    keep = max(2, CTX_TURNS * 2)
    conv = list(histories[chat_id])[-keep:]
    sys_prompt = SYSTEM_PROMPT_CODE if code_mode else SYSTEM_PROMPT
    tail = "\nGiữ giọng tự nhiên." if code_mode else "\nGiữ giọng tự nhiên, 1–4 câu, <350 từ."
    msgs = [{"role":"system","content": sys_prompt + tail}]
    msgs.extend({"role":r,"content":c} for r,c in conv)
    msgs.append({"role":"user","content": user_text})
    return msgs

def stream_worker(messages, out_q: "queue.Queue[str]", max_tokens):
    try:
        stream = client.chat.completions.create(
            model=MODEL, stream=True, max_tokens=max_tokens, temperature=0.7, messages=messages
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta: out_q.put(delta)
    except Exception as e:
        out_q.put(f"\n[stream_error] {type(e).__name__}: {e}")
    finally:
        out_q.put(None)

async def call_stream(messages, max_tokens):
    out_q = queue.Queue()
    t = threading.Thread(target=stream_worker, args=(messages, out_q, max_tokens), daemon=True)
    t.start()
    loop = asyncio.get_event_loop()
    while True:
        part = await loop.run_in_executor(None, out_q.get)
        if part is None: break
        yield part

def complete_block(messages, max_tokens):
    cmp = client.chat.completions.create(
        model=MODEL, stream=False, max_tokens=max_tokens, temperature=0.7, messages=messages
    )
    return (cmp.choices[0].message.content or "").strip()

# ========== Files & Weather ==========
async def get_document_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc: return None, None
    if doc.file_size and doc.file_size > MAX_DOC_BYTES:
        return None, f"Tệp quá lớn ({doc.file_size} bytes). Giới hạn ~{MAX_DOC_BYTES} bytes."
    f = await context.bot.get_file(doc.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}"
    try:
        r = requests.get(url, timeout=60); r.raise_for_status()
        data = r.content if not r.encoding else r.text.encode(r.encoding)
        if len(data) > MAX_DOC_BYTES: return None, f"Tệp quá lớn sau tải ({len(data)} bytes)."
        try: text = data.decode("utf-8")
        except Exception:
            try: text = data.decode("latin-1")
            except Exception: text = ""
        return text, None
    except Exception as e:
        return None, f"Lỗi tải tệp: {e}"

def geocode_vn(q):
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": q, "count": 1, "language": "vi", "format": "json", "country_code": "VN"},
                     timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("results"): return None
    it = data["results"][0]
    return {"name": it["name"], "lat": it["latitude"], "lon": it["longitude"], "admin1": it.get("admin1",""), "country": it.get("country","")}

def weather_vn(q):
    g = geocode_vn(q)
    if not g: return None, "Không tìm thấy địa danh ở Việt Nam."
    params = {
        "latitude": g["lat"], "longitude": g["lon"],
        "current": "temperature_2m,relative_humidity_2m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
        "timezone": "Asia/Ho_Chi_Minh"
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20); r.raise_for_status()
    j = r.json(); cur = j.get("current", {}); daily = j.get("daily", {})
    name = g["name"] + (f", {g['admin1']}" if g.get("admin1") else "")
    t = cur.get("temperature_2m"); rh = cur.get("relative_humidity_2m"); p = cur.get("precipitation")
    tmax0 = daily.get("temperature_2m_max",[None])[0]; tmin0 = daily.get("temperature_2m_min",[None])[0]
    rain0 = daily.get("precipitation_sum",[None])[0]; prob0 = daily.get("precipitation_probability_max",[None])[0]
    tmax1 = daily.get("temperature_2m_max",[None, None])[1]; tmin1 = daily.get("temperature_2m_min",[None, None])[1]
    rain1 = daily.get("precipitation_sum",[None, None])[1]; prob1 = daily.get("precipitation_probability_max",[None, None])[1]
    icon = "☀️"
    if (prob0 or 0) >= 70 or (rain0 or 0) >= 5: icon = "🌧️"
    elif (prob0 or 0) >= 30: icon = "🌦️"
    elif (t or 0) >= 33: icon = "🥵"
    txt = (
        f"{icon} Thời tiết {name}\n"
        f"Hiện tại: {t}°C, ẩm {rh}% ; mưa {p} mm\n"
        f"Hôm nay: {tmin0}–{tmax0}°C, mưa ~{rain0} mm, xác suất {prob0}%\n"
        f"Ngày mai: {tmin1}–{tmax1}°C, mưa ~{rain1} mm, xác suất {prob1}%"
    )
    return g, txt

def try_weather_from_text(text):
    t = (text or "").lower()
    if "thời tiết" not in t: return None
    known = ["hà nội","hn","ha noi","hồ chí minh","tp.hcm","tphcm","sài gòn","đà nẵng","hải phòng","cần thơ","nha trang",
             "đà lạt","huế","quy nhơn","vũng tàu","hạ long","phú quốc","biên hòa","thủ đức"]
    for k in known:
        if k in t: return k
    return "Hà Nội"

# ========== Commands ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update):
        await update.message.reply_text("<b>Em là Linh đây ✨</b>\nCứ nhắn là tám nha!")

async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update):
        await update.message.reply_text(
            f"<b>Gateway:</b> Vercel AI\n<b>Model:</b> {MODEL}\n<b>Context turns:</b> {CTX_TURNS}\n"
            f"<b>Code:</b> stream + lật trang\n<b>Allowed:</b> chat={ALLOWED_CHAT_ID or 'all'}; topic={ALLOWED_TOPIC_ID or 'all'}"
        )

async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update):
        b=cleanup_disk()
        await update.message.reply_text(f"Đã dọn xong ~<b>{round(b/1024/1024,2)}</b> MB. ✅")

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    place = " ".join(context.args).strip() or "Hà Nội"
    try:
        _, text = weather_vn(place)
        await update.message.reply_text(html_escape(text))
    except Exception as e:
        notify_discord("weather_error", {"error": str(e)})
        await update.message.reply_text("Lấy thời tiết bị lỗi, thử tên khác giúp mình nhé.")

async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOWED_CHAT_ID, ALLOWED_TOPIC_ID
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ Bạn không có quyền dùng lệnh này.")
        return
    if not context.args:
        await update.message.reply_text("Dùng: /set <chat_id> [topic_id]\nVí dụ: /set -1001234567890 42")
        return
    try:
        chat_id = int(context.args[0])
        topic_id = int(context.args[1]) if len(context.args) > 1 else 0
    except ValueError:
        await update.message.reply_text("ID phải là số.")
        return
    ALLOWED_CHAT_ID, ALLOWED_TOPIC_ID = chat_id, topic_id
    await update.message.reply_text(
        f"✅ Đã set group: <code>{chat_id}</code>\n✅ Topic: <code>{topic_id or 'none'}</code>"
    )

# ========== on_text ==========
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    chat_id = update.effective_chat.id
    thread_id = current_thread_id(update)
    q = update.message.text or ""
    if asked_creator(q):
        await update.message.reply_text("Tuấn Anh đẹp trai"); return

    wplace = try_weather_from_text(q)
    if wplace:
        try:
            _, text = weather_vn(wplace)
            await update.message.reply_text(html_escape(text)); return
        except Exception as e:
            notify_discord("weather_error", {"error": str(e)})

    code_mode = is_codey(q)
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING, message_thread_id=thread_id)
        try:
            messages = build_messages(chat_id, q, code_mode=code_mode)

            # ----- CODE MODE -----
            if code_mode:
                msg = await update.message.reply_text("…")
                acc, last_edit, edits = "", time.monotonic(), 0
                buffer_all = ""

                async for chunk in call_stream(messages, MAX_TOKENS_CODE):
                    acc += chunk; buffer_all += chunk
                    now = time.monotonic()
                    if len(strip_code(acc)) >= PAGE_CHARS:
                        try:
                            preview = pretty_text(strip_code(acc), max_lines=10)
                            await msg.edit_text(head_body_html(preview))
                        except Exception: pass
                        acc = ""; break

                    if (now - last_edit) >= EDIT_INTERVAL and edits < MAX_EDITS:
                        tmp = word_clamp(strip_code(acc), max(WORD_LIMIT, 800)) or "…"
                        try:
                            await msg.edit_text(head_body_html(tmp))
                            last_edit = now; edits += 1
                        except Exception: pass

                plain = strip_code(buffer_all)

                # nếu dài -> pager
                if len(plain) >= PAGE_CHARS:
                    pages = paginate_html(plain, PAGE_CHARS)
                    await pager_send_first(context, chat_id, pages, "📄 Phần", thread_id)
                else:
                    final_txt = word_clamp(plain, max(WORD_LIMIT, 800)) or "…"
                    try: await msg.edit_text(head_body_html(final_txt))
                    except Exception: await update.message.reply_text(head_body_html(final_txt))

                # tách code block (nếu có)
                m = re.search(r"```(\w+)?\n(.*?)```", buffer_all, flags=re.S)
                if m:
                    await send_code(context, chat_id, m.group(2), lang_hint=m.group(1) or "", thread_id=thread_id)
                    explain = (buffer_all[:m.start()] + "\n" + buffer_all[m.end():]).strip()
                    explain = pretty_text(explain)
                    if explain:
                        await context.bot.send_message(chat_id, f"<b>📝 Giải thích</b>\n{html_escape(explain)}",
                                                       reply_markup=make_code_kb(explain=True),
                                                       message_thread_id=thread_id)
                else:
                    # vẫn gắn keyboard để có thể tiếp code
                    await context.bot.send_message(chat_id, "Điều khiển:", reply_markup=make_code_kb(explain=True),
                                                   message_thread_id=thread_id)

                # lưu session để tiếp code
                key = (chat_id, thread_id)
                sessions[key] = {"mode":"code","prompt": q,"buffer": plain,"explain": True}

                histories[chat_id].append(("user", q))
                histories[chat_id].append(("assistant", (plain or "")[:1000]))
                return

            # ----- CHAT THƯỜNG -----
            msg = await update.message.reply_text("…")
            acc, last_edit, edits = "", time.monotonic(), 0
            buffer_all = ""

            async for chunk in call_stream(messages, MAX_TOKENS):
                acc += chunk; buffer_all += chunk
                now = time.monotonic()

                if len(strip_code(acc)) >= PAGE_CHARS:
                    try:
                        preview = pretty_text(strip_code(acc), max_lines=10)
                        await msg.edit_text(head_body_html(preview))
                    except Exception: pass
                    acc = ""; break

                if (now - last_edit) >= EDIT_INTERVAL and edits < MAX_EDITS:
                    tmp = word_clamp(strip_code(acc), WORD_LIMIT) or "…"
                    try:
                        await msg.edit_text(head_body_html(tmp))
                        last_edit = now; edits += 1
                    except Exception: pass

            final_plain = strip_code(buffer_all)
            if len(final_plain) >= PAGE_CHARS:
                pages = paginate_html(final_plain, PAGE_CHARS)
                await pager_send_first(context, chat_id, pages, "📄 Phần", thread_id)
            else:
                final_txt = word_clamp(final_plain, WORD_LIMIT) or "Em bị lag mất rồi, nhắn lại giúp em nha."
                try: await msg.edit_text(head_body_html(final_txt))
                except Exception: await update.message.reply_text(head_body_html(final_txt))

            histories[chat_id].append(("user", q))
            histories[chat_id].append(("assistant", final_plain[:1000]))

        except Exception as e:
            notify_discord("gateway_stream_error", {"error": str(e), "trace": traceback.format_exc()})
            await update.message.reply_text("Có lỗi kết nối, thử lại giúp em nhé.")

# ========== on_document ==========
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    chat_id = update.effective_chat.id
    thread_id = current_thread_id(update)
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING, message_thread_id=thread_id)
        try:
            text, err = await get_document_text(update, context)
            if err: await update.message.reply_text(html_escape(err)); return
            if not text.strip():
                await update.message.reply_text("Không đọc được nội dung tệp (có thể là nhị phân)."); return

            prompt = ("Phân tích tệp mã nguồn dưới đây: liệt kê lỗi, hiệu năng/bảo mật, style, đề xuất cải thiện. "
                      "Nếu hợp lý, đưa bản vá (diff) hoặc code đã sửa.\n\n=== NỘI DUNG TỆP ===\n" + text[:MAX_DOC_BYTES].rstrip())
            messages = [{"role":"system","content": SYSTEM_PROMPT_CODE},{"role":"user","content": prompt}]
            result = complete_block(messages, MAX_TOKENS_CODE) or "Không nhận được phản hồi."

            m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
            if m:
                await send_code(context, chat_id, m.group(2), lang_hint=m.group(1) or "", thread_id=thread_id)
                explain = (result[:m.start()] + "\n" + result[m.end():]).strip()
                if explain:
                    await context.bot.send_message(chat_id, f"<b>📝 Giải thích</b>\n{html_escape(pretty_text(explain, 20))}",
                                                   message_thread_id=thread_id)
            else:
                pages = paginate_html(result, PAGE_CHARS)
                await pager_send_first(context, chat_id, pages, "🔎 Phân tích", thread_id)

            histories[chat_id].append(("user", "[tệp đính kèm]"))
            histories[chat_id].append(("assistant", result[:1000]))
        except Exception as e:
            notify_discord("doc_analyze_error", {"error": str(e), "trace": traceback.format_exc()})
            await update.message.reply_text("Phân tích tệp bị lỗi, thử lại giúp mình nhé.")

# ========== Callback buttons ==========
async def on_code_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    chat_id = q.message.chat.id
    thread_id = getattr(q.message, "message_thread_id", None)
    key = (chat_id, thread_id)
    sess = sessions.get(key)
    if not sess or sess.get("mode") != "code":
        await q.edit_message_text("Hết phiên hoặc không có code để tiếp tục.")
        return

    base_messages = build_messages(chat_id, sess["prompt"], code_mode=True)

    if data == "CODE_MORE":
        tail = "\n".join(sess["buffer"].splitlines()[-60:])
        prompt_more = "Hãy TIẾP TỤC code ngay sau phần dưới đây. Không lặp lại, giữ cấu trúc & phong cách.\n=== CONTEXT CUỐI ===\n" + tail
        messages = base_messages + [{"role": "user", "content": prompt_more}]

        msg = await q.message.reply_text("…")
        acc, last_edit, edits = "", time.monotonic(), 0
        buffer_more = ""
        async for chunk in call_stream(messages, MAX_TOKENS_CODE):
            acc += chunk; buffer_more += chunk
            now = time.monotonic()
            if (now - last_edit) >= EDIT_INTERVAL and edits < MAX_EDITS:
                tmp = word_clamp(strip_code(acc), max(WORD_LIMIT, 800)) or "…"
                try: await msg.edit_text(head_body_html(tmp))
                except: pass
                last_edit = now; edits += 1

        more_plain = strip_code(buffer_more)
        sess["buffer"] += ("\n" + more_plain)
        sessions[key] = sess

        m = re.search(r"```(\w+)?\n(.*?)```", buffer_more, flags=re.S)
        if m:
            await send_code(context, chat_id, m.group(2), lang_hint=m.group(1) or "", thread_id=thread_id)
            explain = (buffer_more[:m.start()] + "\n" + buffer_more[m.end():]).strip()
            if explain and sess.get("explain", True):
                await context.bot.send_message(chat_id, f"<b>📝 Giải thích</b>\n{html_escape(pretty_text(explain, 20))}",
                                               message_thread_id=thread_id)
        else:
            pages = paginate_html(more_plain, PAGE_CHARS)
            await pager_send_first(context, chat_id, pages, "📄 Phần tiếp", thread_id)

    elif data == "CODE_TOGGLE_EXPLAIN":
        sess["explain"] = not sess.get("explain", True)
        sessions[key] = sess
        await q.edit_message_text(
            f"Chế độ giải thích: {'BẬT' if sess['explain'] else 'TẮT'}",
            reply_markup=make_code_kb(sess["explain"])
        )

    elif data == "CODE_REGEN":
        messages = build_messages(chat_id, sess["prompt"], code_mode=True)
        text = complete_block(messages, MAX_TOKENS_CODE) or "Không nhận được phản hồi."
        sess["buffer"] = strip_code(text)
        sessions[key] = sess
        m = re.search(r"```(\w+)?\n(.*?)```", text, flags=re.S)
        if m:
            await send_code(context, chat_id, m.group(2), lang_hint=m.group(1) or "", thread_id=thread_id)
            explain = (text[:m.start()] + "\n" + text[m.end():]).strip()
            if explain and sess.get("explain", True):
                await context.bot.send_message(chat_id, f"<b>📝 Giải thích</b>\n{html_escape(pretty_text(explain, 20))}",
                                               message_thread_id=thread_id)
        else:
            await context.bot.send_message(chat_id, html_escape(pretty_text(text, 20)), message_thread_id=thread_id)

async def on_pager_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "PAGE_PREV":
        await pager_edit(update, context, -1)
    elif data == "PAGE_NEXT":
        await pager_edit(update, context, +1)
    else:
        await update.callback_query.answer()

# ========== Boot ==========
def main():
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    threading.Thread(target=auto_ping, daemon=True).start()
    threading.Thread(target=cleanup_loop, daemon=True).start()

    defaults = Defaults(parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    app_tg = ApplicationBuilder().token(BOT_TOKEN).defaults(defaults).build()

    targets = [int(s) for s in REMIND_CHAT_IDS if s] or ([ALLOWED_CHAT_ID] if ALLOWED_CHAT_ID else [])
    if targets: threading.Thread(target=reminder_loop, args=(app_tg.bot, targets), daemon=True).start()

    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("model", cmd_model))
    app_tg.add_handler(CommandHandler("clean", cmd_clean))
    app_tg.add_handler(CommandHandler("weather", cmd_weather))
    app_tg.add_handler(CommandHandler("set", cmd_set))   # chỉ OWNER_ID
    app_tg.add_handler(CallbackQueryHandler(on_code_buttons, pattern="^CODE_"))
    app_tg.add_handler(CallbackQueryHandler(on_pager_buttons, pattern="^PAGE_|^NOP$"))
    app_tg.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app_tg.run_polling()

if __name__ == "__main__":
    main()
