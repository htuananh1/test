import os, re, threading, asyncio, io
from collections import deque, defaultdict
from html import escape as htmlesc
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from telegram.error import BadRequest
from openai import OpenAI

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None
try:
    import chardet
except Exception:
    chardet = None
try:
    import PyPDF2
except Exception:
    PyPDF2 = None
try:
    import docx
    from docx import Document as DocxDocument
except Exception:
    docx = None
    DocxDocument = None
try:
    import openpyxl
except Exception:
    openpyxl = None
try:
    from pptx import Presentation
except Exception:
    Presentation = None
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "anthropic/claude-3.5-haiku")
CODE_MODEL = os.getenv("CODE_MODEL", "anthropic/claude-4-opus")
FILE_MODEL = os.getenv("FILE_MODEL", "anthropic/claude-4-sonnet")

PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "900"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
FILE_OUTPUT_TOKENS = int(os.getenv("FILE_OUTPUT_TOKENS", "6000"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "120000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "7"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")
MAX_EMIT_CHARS = int(os.getenv("MAX_EMIT_CHARS", "800000"))
ARCHIVES = (".zip",".rar",".7z",".tar",".tar.gz",".tgz",".tar.bz2",".tar.xz")
TEXT_LIKE = (".txt",".md",".log",".csv",".tsv",".json",".yaml",".yml",".ini",".cfg",".env",".xml",".html",".htm",
             ".py",".js",".ts",".java",".c",".cpp",".cs",".go",".php",".rb",".rs",".sh",".bat",".ps1",".sql")

MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "3"))
SEM = asyncio.Semaphore(MAX_CONCURRENCY)

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL) if VERCEL_API_KEY else None
app = Flask(__name__)
histories = defaultdict(lambda: deque(maxlen=32))
locks = defaultdict(asyncio.Lock)
PAGERS = {}
PENDING_FILE = {}
LAST_RESULT = {}
FILE_MODE = defaultdict(lambda: False)

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
    return (f"```{p['lang']}\n{txt}\n```", ParseMode.MARKDOWN) if p["is_code"] else (htmlesc(txt), ParseMode.HTML)

async def send_or_update(ctx, chat_id, msg, p):
    text,mode = page_payload(p); keyboard = kb(p["idx"], len(p["pages"]))
    try:
        if msg: await msg.edit_text(text, parse_mode=mode, reply_markup=keyboard)
        else:
            m = await ctx.bot.send_message(chat_id, text, parse_mode=mode, reply_markup=keyboard)
            PAGERS[(m.chat_id, m.message_id)] = p
    except BadRequest:
        p["is_code"]=True
        text,mode = page_payload(p)
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
    msgs += [{"role":"user" if r=='user' else 'assistant',"content":c} for r,c in list(histories[cid])[-keep:]]
    msgs.append({"role":"user","content":user_text})
    return msgs

def sys_prompt_linh():
    return ("Bạn tên là Linh. Nói chuyện tự nhiên như người Việt, ngắn gọn, thẳng, có cảm xúc; "
            "cho phép văng tục nhẹ khi hợp ngữ cảnh, không thù hằn và không công kích cá nhân. "
            "Không nịnh bợ, không vòng vo. Tập trung ý chính.")

def complete_with_model(model, messages, max_tokens, temperature=0.7):
    if not client: return "Thiếu VERCEL_API_KEY."
    res = client.chat.completions.create(model=model, max_tokens=max_tokens, temperature=temperature, messages=messages)
    return (res.choices[0].message.content or "").strip()

async def run_llm(model, messages, max_tokens, temperature=0.7):
    async with SEM:
        return await asyncio.to_thread(complete_with_model, model, messages, max_tokens, temperature)

def is_archive(name: str):
    return (name or "").lower().endswith(ARCHIVES)

def detect_decode(data: bytes):
    if not data: return ""
    if chardet:
        enc = (chardet.detect(data) or {}).get("encoding") or "utf-8"
        try: return data.decode(enc, errors="ignore")
        except Exception: pass
    try: return data.decode("utf-8", errors="ignore")
    except Exception: return data.decode("latin-1", errors="ignore")

def read_any_file(name: str, data: bytes):
    n=(name or "").lower()
    if is_archive(n): return None, "archive"
    if any(n.endswith(ext) for ext in TEXT_LIKE):
        raw = detect_decode(data)
        if n.endswith((".html",".htm")) and BeautifulSoup:
            soup = BeautifulSoup(raw, "html.parser")
            raw = soup.get_text(separator="\n")
        return raw, "text"
    if n.endswith(".pdf"):
        if not PyPDF2: return "Không có PyPDF2 để đọc PDF.", "error"
        buf = io.BytesIO(data); r = PyPDF2.PdfReader(buf)
        parts=[]
        for i in range(min(len(r.pages), 200)):
            try: parts.append(r.pages[i].extract_text() or "")
            except Exception: parts.append("")
        return "\n".join(parts), "text"
    if n.endswith((".docx",".doc")):
        if not docx: return "Không có python-docx để đọc DOCX.", "error"
        if n.endswith(".doc"): return "Không hỗ trợ .doc, hãy chuyển sang .docx.", "error"
        buf = io.BytesIO(data); d = docx.Document(buf)
        parts=[p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(parts), "text"
    if n.endswith((".xlsx",".xlsm",".xltx",".xltm",".xls")):
        if not openpyxl: return "Không có openpyxl để đọc Excel.", "error"
        buf = io.BytesIO(data); wb = openpyxl.load_workbook(buf, read_only=True, data_only=True)
        out=[]
        for ws in wb.worksheets[:12]:
            out.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                vals=[("" if v is None else str(v)) for v in row]
                out.append("\t".join(vals))
        return "\n".join(out), "text"
    if n.endswith(".pptx"):
        if not Presentation: return "Không có python-pptx để đọc PPTX.", "error"
        buf = io.BytesIO(data); prs = Presentation(buf)
        parts=[]
        for i, slide in enumerate(prs.slides[:300]):
            parts.append(f"# Slide {i+1}")
            for shape in slide.shapes:
                if hasattr(shape, "text"): parts.append(shape.text)
        return "\n".join(parts), "text"
    return "Định dạng này chưa hỗ trợ. Hãy gửi văn bản, PDF, DOCX, XLSX, PPTX, HTML, JSON, CSV, v.v.", "error"

def _safe_name(s): return re.sub(r"[^\w\-]+","_", s).strip("_") or "output"

def make_docx_from_text(text: str) -> bytes:
    if DocxDocument is None: raise RuntimeError("Thiếu python-docx")
    doc = DocxDocument()
    for line in (text or "").splitlines():
        doc.add_paragraph(line if line.strip() else "")
    bio = io.BytesIO(); doc.save(bio)
    return bio.getvalue()

def _emit_text_file(base, ext, text):
    out_name = f"{_safe_name(base)}{ext}"
    buf = io.BytesIO((text or "").encode("utf-8")); buf.name = out_name
    return out_name, buf

def _emit_docx_file(base, text):
    data = make_docx_from_text(text)
    out_name = f"{_safe_name(base)}.docx"
    buf = io.BytesIO(data); buf.name = out_name
    return out_name, buf

def _get_gem_client():
    if genai is None or types is None: raise RuntimeError("Thiếu package google-genai")
    if not GEMINI_API_KEY: raise RuntimeError("Thiếu GEMINI_API_KEY")
    return genai.Client(api_key=GEMINI_API_KEY)

def create_image_bytes_gemini(prompt: str):
    cli = _get_gem_client()
    resp = cli.models.generate_content(model=GEMINI_IMAGE_MODEL, contents=prompt, config=types.GenerateContentConfig(response_modalities=['TEXT','IMAGE']))
    parts = resp.candidates[0].content.parts if resp and resp.candidates else []
    for part in parts:
        if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
            return part.inline_data.data, part.inline_data.mime_type or "image/png"
    raise RuntimeError("Gemini không trả ảnh.")

async def run_gemini(prompt: str):
    async with SEM:
        return await asyncio.to_thread(create_image_bytes_gemini, prompt)

def want_image(t):
    t=(t or "").lower()
    return any(k in t for k in ["tạo ảnh","vẽ","generate image","draw image","vẽ giúp","create image","/img "])

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Lệnh:\n"
        "/help\n"
        "/img <mô tả>\n"
        "/code <yêu cầu>\n"
        "/chat – thoát FILE MODE\n"
        "/cancelfile – huỷ file\n"
        "/sendfile – tải kết quả\n"
        "Gửi file để vào FILE MODE, nhắn yêu cầu rồi mình xử lý."
    )

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    if not prompt: return await context.bot.send_message(chat_id, "Dùng: /img <mô tả>")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    try:
        data, mime = await run_gemini(prompt)
        buf = io.BytesIO(data); buf.name = "gen.png"
        await context.bot.send_photo(chat_id, buf)
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi tạo ảnh: {e}")

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = " ".join(context.args).strip()
    if not q: return await context.bot.send_message(chat_id, "Dùng: /code <yêu cầu>")
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        msgs = build_messages(chat_id, q, sys_prompt_linh()+" Bạn là lập trình viên kỳ cựu. Viết code sạch, best practice.")
        result = await run_llm(CODE_MODEL, msgs, MAX_TOKENS_CODE, temperature=0.4) or "..."
        m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
        if m: await start_pager(context, chat_id, m.group(2).rstrip(), is_code=True, lang_hint=m.group(1) or "")
        else: await start_pager(context, chat_id, result, is_code=True, lang_hint="markdown")
        histories[chat_id].append(("user", q)); histories[chat_id].append(("assistant", result[:1000]))

def split_text_smart(text: str, chunk_chars: int = CHUNK_CHARS):
    if len(text) <= chunk_chars: return [text]
    parts=[]; cur=[]; used=0
    for para in text.split("\n"):
        add=len(para)+1
        if used+add>chunk_chars and cur:
            parts.append("\n".join(cur)); cur=[para]; used=add
        else:
            cur.append(para); used+=add
    if cur: parts.append("\n".join(cur))
    return parts

def system_for_instruction():
    return ("Bạn là Linh. Áp dụng đúng yêu cầu người dùng lên tài liệu được cung cấp. "
            "Chỉ trả kết quả đã xử lý, không giải thích. Giữ cấu trúc hợp lý, rõ ràng.")

async def run_with_instruction(document_text: str, instruction: str):
    chunks = split_text_smart(document_text, CHUNK_CHARS)
    if not client: return document_text
    if len(chunks)==1:
        user = f"Yêu cầu:\n{instruction}\n\nTài liệu:\n{chunks[0]}"
        msgs=[{"role":"system","content":system_for_instruction()},{"role":"user","content":user}]
        return await run_llm(FILE_MODEL, msgs, FILE_OUTPUT_TOKENS, temperature=0.3)
    partials=[]
    for i,ck in enumerate(chunks,1):
        user = f"Yêu cầu:\n{instruction}\n\nTài liệu - phần {i}/{len(chunks)}:\n{ck}"
        msgs=[{"role":"system","content":system_for_instruction()},{"role":"user","content":user}]
        part = await run_llm(FILE_MODEL, msgs, min(FILE_OUTPUT_TOKENS,8000), temperature=0.3)
        partials.append(part)
    merge_user = "Hợp nhất các phần sau thành một phiên bản thống nhất:\n\n" + "\n\n-----\n\n".join(f"[PHẦN {i+1}]\n{p}" for i,p in enumerate(partials))
    msgs=[{"role":"system","content":"Hợp nhất văn bản, liền mạch, không lặp, trung thành với yêu cầu."},{"role":"user","content":merge_user}]
    return await run_llm(FILE_MODEL, msgs, FILE_OUTPUT_TOKENS, temperature=0.2)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    q = (update.message.text or "").strip()

    if want_image(q):
        prompt = re.sub(r"(?i)(tạo ảnh|vẽ|generate image|draw image|vẽ giúp|create image|/img)\s*[:\-]*", "", q).strip() or "A cute cat in space suit, 3D render"
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        try:
            data, _ = await run_gemini(prompt)
            buf = io.BytesIO(data); buf.name = "gen.png"
            await context.bot.send_photo(chat_id, buf)
        except Exception as e:
            await context.bot.send_message(chat_id, f"Lỗi tạo ảnh: {e}")
        return

    if FILE_MODE[chat_id] and chat_id in PENDING_FILE:
        entry = PENDING_FILE[chat_id]
        name, data = entry["name"], entry["data"]
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        text, kind = read_any_file(name, data)
        if kind == "error" or not text:
            return await context.bot.send_message(chat_id, text or "Không trích được nội dung từ file.")
        text = text[:MAX_EMIT_CHARS]
        out = await run_with_instruction(text, q)
        await start_pager(context, chat_id, out, is_code=True, lang_hint="markdown")
        ext = os.path.splitext(name)[1].lower()
        LAST_RESULT[chat_id] = {"name": name, "text": out, "ext": ext}
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    msgs = build_messages(chat_id, q, sys_prompt_linh())
    result = await run_llm(CHAT_MODEL, msgs, MAX_TOKENS, temperature=0.85) or "..."
    await context.bot.send_message(chat_id, f"📝 <i>Lời dẫn</i>\n{htmlesc(result)}", parse_mode=ParseMode.HTML)
    histories[chat_id].append(("user", q)); histories[chat_id].append(("assistant", result[:1000]))

async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    doc = update.message.document
    name = doc.file_name or "file"
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        if is_archive(name): return await context.bot.send_message(chat_id, "Không nhận file nén.")
        f = await context.bot.get_file(doc.file_id)
        bio = io.BytesIO(); await f.download_to_memory(out=bio)
        data = bio.getvalue(); bio.close()
        PENDING_FILE[chat_id] = {"name": name, "data": data}
        FILE_MODE[chat_id] = True
        await context.bot.send_message(chat_id, "Đã nhận file. Đang ở FILE MODE. Gửi yêu cầu để xử lý. /chat để thoát, /cancelfile để huỷ, /sendfile để tải kết quả.")
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi nhận file: {e}")

async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    FILE_MODE[chat_id] = False
    await context.bot.send_message(chat_id, "Đã thoát FILE MODE. Quay lại chat thường.")

async def cmd_cancelfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    FILE_MODE[chat_id] = False
    PENDING_FILE.pop(chat_id, None)
    LAST_RESULT.pop(chat_id, None)
    await context.bot.send_message(chat_id, "Đã huỷ file và thoát FILE MODE.")

async def cmd_sendfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    r = LAST_RESULT.get(chat_id)
    if not r:
        return await context.bot.send_message(chat_id, "Chưa có kết quả để gửi.")
    base = os.path.splitext(r["name"])[0]
    ext = r["ext"] or ".txt"
    if ext.lower() in TEXT_LIKE:
        out_name, buf = _emit_text_file(base, ext, r["text"])
    elif ext.lower()==".docx" and DocxDocument is not None:
        out_name, buf = _emit_docx_file(base, r["text"])
    else:
        out_name, buf = _emit_text_file(base, ".txt", r["text"])
    await context.bot.send_document(chat_id, document=buf, caption=out_name)
    buf.close()

def main():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("help", cmd_help))
    app_tg.add_handler(CommandHandler("img", cmd_img))
    app_tg.add_handler(CommandHandler("code", cmd_code))
    app_tg.add_handler(CommandHandler("chat", cmd_chat))
    app_tg.add_handler(CommandHandler("cancelfile", cmd_cancelfile))
    app_tg.add_handler(CommandHandler("sendfile", cmd_sendfile))
    app_tg.add_handler(CallbackQueryHandler(on_page_nav, pattern=r"^pg_"))
    app_tg.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    app_tg.run_polling()

if __name__ == "__main__":
    main()
