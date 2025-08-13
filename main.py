
import os, re, asyncio, io, logging, random, datetime, base64, json
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
VERCEL_API_KEY = os.getenv("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "anthropic/claude-3.5-haiku")
CODE_MODEL = os.getenv("CODE_MODEL", "anthropic/claude-4-sonnet")
FILE_MODEL = os.getenv("FILE_MODEL", "anthropic/claude-4.1-opus")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "900"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
FILE_OUTPUT_TOKENS = int(os.getenv("FILE_OUTPUT_TOKENS", "6000"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "120000"))
PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "12"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "3"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "90"))
MAX_EMIT_CHARS = int(os.getenv("MAX_EMIT_CHARS", "800000"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL, timeout=REQUEST_TIMEOUT) if VERCEL_API_KEY else None
SEM = asyncio.Semaphore(MAX_CONCURRENCY)
FILE_MODE = defaultdict(lambda: False)
PAGERS = {}
LAST_RESULT = defaultdict(lambda: None)

def sys_prompt_linh() -> str:
    current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"Bạn tên là Linh. Nói chuyện tự nhiên tiếng Việt, ngắn gọn, thẳng. "
        f"Không dùng Markdown. Thời gian UTC: {current_time}."
    )

def build_msgs(sys_prompt: str, user_text: str, kind: str = "chat") -> list:
    sys = {"role": "system", "content": sys_prompt}
    if kind == "code":
        user = {"role": "user", "content": f"Viết code theo yêu cầu sau, trả lời chỉ văn bản thuần, không markdown:\n{user_text}"}
    else:
        user = {"role": "user", "content": user_text}
    return [sys, user]

def complete_with_model(model: str, messages: list, max_tokens: int, temperature: float = 0.7) -> str:
    if not client:
        return "Thiếu VERCEL_API_KEY."
    try:
        res = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        txt = res.choices[0].message.content if res and res.choices else ""
        if not txt:
            return ""
        if len(txt) > MAX_EMIT_CHARS:
            txt = txt[:MAX_EMIT_CHARS]
        return txt
    except Exception as e:
        return f"Lỗi gọi model: {e}"

async def run_llm(model: str, messages: list, max_tokens: int, temperature: float = 0.7) -> str:
    tries = 2
    last = None
    for i in range(tries):
        try:
            return await asyncio.to_thread(
                complete_with_model,
                model,
                messages,
                max_tokens,
                temperature
            )
        except Exception as e:
            last = e
            await asyncio.sleep(1.0 + random.random())
    if last:
        raise last
    return ""

def detect_decode(data: bytes) -> str:
    if not data:
        return ""
    enc = None
    if chardet:
        try:
            info = chardet.detect(data)
            enc = info.get("encoding")
        except Exception:
            enc = None
    for codec in [enc, "utf-8", "utf-16", "latin-1"]:
        if not codec:
            continue
        try:
            return data.decode(codec, errors="replace")
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")

TEXT_LIKE = (".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".yaml", ".yml", ".html", ".htm", ".css", ".xml")
ARCHIVE_LIKE = (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2")

def is_archive(name: str) -> bool:
    name = (name or "").lower()
    return any(name.endswith(ext) for ext in ARCHIVE_LIKE)

def extract_text_from_file(name: str, data: bytes) -> tuple[str, str]:
    n = (name or "").lower()
    if is_archive(n):
        return "Định dạng nén chưa hỗ trợ.", "error"
    if any(n.endswith(ext) for ext in TEXT_LIKE):
        raw = detect_decode(data)
        if n.endswith((".html", ".htm")) and BeautifulSoup:
            try:
                soup = BeautifulSoup(raw, "html.parser")
                raw = soup.get_text(separator="\n")
            except Exception:
                pass
        return raw, "text"
    if n.endswith(".pdf"):
        if not PyPDF2:
            return "Chưa cài PyPDF2.", "error"
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            texts = []
            for page in reader.pages:
                try:
                    texts.append(page.extract_text() or "")
                except Exception:
                    texts.append("")
            return "\n".join(texts), "text"
        except Exception as e:
            return f"Lỗi đọc PDF: {e}", "error"
    if n.endswith((".docx", ".doc")):
        if not DocxDocument:
            return "Chưa cài python-docx.", "error"
        try:
            bio = io.BytesIO(data)
            doc = DocxDocument(bio)
            txt = "\n".join([p.text for p in doc.paragraphs])
            return txt, "text"
        except Exception as e:
            return f"Lỗi đọc DOCX: {e}", "error"
    if n.endswith((".xlsx", ".xls")):
        if not openpyxl:
            return "Chưa cài openpyxl.", "error"
        try:
            bio = io.BytesIO(data)
            wb = openpyxl.load_workbook(bio, data_only=True)
            rows = []
            for ws in wb.worksheets:
                for r in ws.iter_rows(values_only=True):
                    rows.append("\t".join("" if v is None else str(v) for v in r))
            return "\n".join(rows), "text"
        except Exception as e:
            return f"Lỗi đọc XLSX: {e}", "error"
    if n.endswith((".pptx", ".ppt")):
        if not Presentation:
            return "Chưa cài python-pptx.", "error"
        try:
            prs = Presentation(io.BytesIO(data))
            texts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        texts.append(shape.text or "")
            return "\n".join(texts), "text"
        except Exception as e:
            return f"Lỗi đọc PPTX: {e}", "error"
    return "Định dạng này chưa hỗ trợ.", "error"

def split_pages(text: str, page_chars: int = PAGE_CHARS) -> list[str]:
    text = text or ""
    if len(text) <= page_chars:
        return [text]
    pages = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + page_chars)
        pages.append(text[start:end])
        start = end
    return pages

def make_pager(chat_id: int, pages: list[str], page_idx: int = 0):
    PAGERS[chat_id] = {"pages": pages, "i": page_idx}
    btns = []
    total = len(pages)
    left = InlineKeyboardButton("←", callback_data=f"pg_{chat_id}_{max(0, page_idx-1)}")
    right = InlineKeyboardButton("→", callback_data=f"pg_{chat_id}_{min(total-1, page_idx+1)}")
    btns.append([left, right])
    kb = InlineKeyboardMarkup(btns)
    return pages[page_idx], kb

async def on_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    try:
        _, cid, idx = q.data.split("_")
        cid = int(cid)
        idx = int(idx)
    except Exception:
        await q.answer()
        return
    info = PAGERS.get(cid)
    if not info:
        await q.answer()
        return
    pages = info["pages"]
    idx = max(0, min(len(pages)-1, idx))
    PAGERS[cid]["i"] = idx
    await q.edit_message_text(pages[idx], disable_web_page_preview=True, reply_markup=make_pager(cid, pages, idx)[1])
    await q.answer()

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        update.effective_chat.id,
        "/help – Hiện lệnh\n"
        "/img <mô tả> – Tạo ảnh (Gemini)\n"
        "/code <yêu cầu> – Viết code\n"
        "/chat <hỏi> – Chat nhanh\n"
        "/cancelfile – Thoát FILE MODE\n"
        "/sendfile – Tải kết quả gần nhất\n"
        "Gửi file để vào FILE MODE."
    )

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = " ".join(context.args).strip()
    if not q:
        await context.bot.send_message(chat_id, "Dùng: /img <mô tả>")
        return
    if not GEMINI_API_KEY:
        await context.bot.send_message(chat_id, "Thiếu GEMINI_API_KEY.")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    try:
        if genai is None or types is None:
            await context.bot.send_message(chat_id, "Chưa cài google-genai.")
            return
        client = genai.Client(api_key=GEMINI_API_KEY)
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=q)])]
        config = types.GenerateContentConfig(response_modalities=["IMAGE","TEXT"])
        got = 0
        async for chunk in client.models.generate_content_stream(
            model=GEMINI_IMAGE_MODEL,
            contents=contents,
            config=config,
        ):
            cands = getattr(chunk, "candidates", None)
            if not cands:
                if getattr(chunk, "text", None):
                    await context.bot.send_message(chat_id, chunk.text)
                continue
            content = cands[0].content if cands[0] else None
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                continue
            part = parts[0]
            inline = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
            if inline and getattr(inline, "data", None):
                img_b64 = inline.data
                try:
                    img_bytes = base64.b64decode(img_b64)
                    await context.bot.send_photo(chat_id, photo=io.BytesIO(img_bytes))
                    got += 1
                except Exception:
                    pass
            elif getattr(chunk, "text", None):
                await context.bot.send_message(chat_id, chunk.text)
        if got == 0:
            await context.bot.send_message(chat_id, "Không nhận được ảnh từ Gemini.")
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi tạo ảnh: {e}")

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = " ".join(context.args).strip()
    if not q:
        await context.bot.send_message(chat_id, "Dùng: /code <yêu cầu>")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    sys_prompt = sys_prompt_linh()
    msgs = build_msgs(sys_prompt, q, kind="code")
    try:
        out = await run_llm(CODE_MODEL, msgs, MAX_TOKENS_CODE, temperature=0.2)
        out = out or "Không nhận được phản hồi."
        LAST_RESULT[chat_id] = out
        pages = split_pages(out)
        text, kb = make_pager(chat_id, pages, 0)
        await context.bot.send_message(chat_id, text, disable_web_page_preview=True, reply_markup=kb)
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi /code: {e}")

async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = " ".join(context.args).strip()
    if not q:
        await context.bot.send_message(chat_id, "Dùng: /chat <câu hỏi>")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    sys_prompt = sys_prompt_linh()
    msgs = build_msgs(sys_prompt, q, kind="chat")
    try:
        out = await run_llm(CHAT_MODEL, msgs, MAX_TOKENS, temperature=0.7)
        out = out or "Không nhận được phản hồi."
        LAST_RESULT[chat_id] = out
        pages = split_pages(out)
        text, kb = make_pager(chat_id, pages, 0)
        await context.bot.send_message(chat_id, text, disable_web_page_preview=True, reply_markup=kb)
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi /chat: {e}")

async def cmd_cancelfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    FILE_MODE[chat_id] = False
    await context.bot.send_message(chat_id, "Đã thoát FILE MODE.")

async def cmd_sendfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = LAST_RESULT.get(chat_id)
    if not data:
        await context.bot.send_message(chat_id, "Chưa có kết quả để gửi.")
        return
    bio = io.BytesIO(data.encode("utf-8"))
    bio.name = "result.txt"
    await context.bot.send_document(chat_id, document=bio)

async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    doc = update.message.document if update.message else None
    if not doc:
        return
    FILE_MODE[chat_id] = True
    f = await context.bot.get_file(doc.file_id)
    bio = io.BytesIO()
    await f.download_to_memory(bio)
    content, kind = extract_text_from_file(doc.file_name or "file", bio.getvalue())
    if kind == "error":
        await context.bot.send_message(chat_id, content)
        return
    sys_prompt = sys_prompt_linh()
    msgs = build_msgs(sys_prompt, f"Hãy tóm tắt file này ngắn gọn:\n{content[:CHUNK_CHARS]}", kind="chat")
    try:
        out = await run_llm(FILE_MODEL, msgs, FILE_OUTPUT_TOKENS, temperature=0.5)
        out = out or "Không nhận được phản hồi."
        LAST_RESULT[chat_id] = out
        pages = split_pages(out)
        text, kb = make_pager(chat_id, pages, 0)
        await context.bot.send_message(chat_id, text, disable_web_page_preview=True, reply_markup=kb)
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi xử lý file: {e}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    if text.startswith("/"):
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    sys_prompt = sys_prompt_linh()
    msgs = build_msgs(sys_prompt, text, kind="chat")
    try:
        out = await run_llm(CHAT_MODEL, msgs, MAX_TOKENS, temperature=0.7)
        out = out or "Không nhận được phản hồi."
        LAST_RESULT[chat_id] = out
        pages = split_pages(out)
        msg, kb = make_pager(chat_id, pages, 0)
        await context.bot.send_message(chat_id, msg, disable_web_page_preview=True, reply_markup=kb)
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi chat: {e}")

async def on_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    try:
        _, cid, idx = q.data.split("_")
        cid = int(cid)
        idx = int(idx)
    except Exception:
        await q.answer()
        return
    info = PAGERS.get(cid)
    if not info:
        await q.answer()
        return
    pages = info["pages"]
    idx = max(0, min(len(pages)-1, idx))
    PAGERS[cid]["i"] = idx
    await q.edit_message_text(pages[idx], disable_web_page_preview=True, reply_markup=make_pager(cid, pages, idx)[1])
    await q.answer()

def main():
    if not BOT_TOKEN:
        print("Thiếu BOT_TOKEN: đặt biến môi trường BOT_TOKEN trước khi chạy.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("chat", cmd_chat))
    app.add_handler(CommandHandler("cancelfile", cmd_cancelfile))
    app.add_handler(CommandHandler("sendfile", cmd_sendfile))
    app.add_handler(CallbackQueryHandler(on_page_nav, pattern=r"^pg_"))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Starting Telegram polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
