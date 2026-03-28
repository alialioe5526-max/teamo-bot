import logging
import sqlite3
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

BOT_TOKEN    = "8578221142:AAFe_J9s1EYZwyb1ao5jffZwo5nFy_hpAK0"
ADMIN_ID     = 269900681
WALLET_TRC20 = "TPAgKfYzRdK83Qocc4gXvEVu4jPKfeuer5"

REFERRAL_COMMISSIONS = {
    "A1": [35, 17, 12, 8,  5,  5],
    "A2": [60, 25, 17, 12, 5,  5],
    "A3": [90, 35, 21, 14, 5,  5],
    "B1": [140,85, 35, 20, 9,  9],
    "B2": [220,125,90, 30, 15, 15],
    "B3": [350,175,100,32, 18, 18],
}

PACKAGES = {
    "A1": {"price": 200,  "tasks": 3, "per_task": 1.11,  "daily": 3.33},
    "A2": {"price": 400,  "tasks": 3, "per_task": 2.22,  "daily": 6.66},
    "A3": {"price": 600,  "tasks": 3, "per_task": 3.33,  "daily": 10.00},
    "B1": {"price": 1200, "tasks": 4, "per_task": 5.00,  "daily": 20.00},
    "B2": {"price": 1800, "tasks": 4, "per_task": 7.50,  "daily": 30.00},
    "B3": {"price": 2500, "tasks": 4, "per_task": 10.41, "daily": 41.66},
}

PACKAGE_DAYS = 365
MIN_WITHDRAW = 10

ST_PHONE     = "WAITING_PHONE"
ST_RECEIPT   = "WAITING_RECEIPT"
ST_WALLET    = "WAITING_WALLET"
ST_WITHDRAW  = "WAITING_WITHDRAW"
ST_BROADCAST = "WAITING_BROADCAST"
ST_SETWALLET = "WAITING_SETWALLET"
ST_ADDLINK   = "WAITING_ADDLINK"

# نصوص الأزرار الثابتة
BTN_TASKS    = "📋 مهامي اليومية"
BTN_WALLET   = "💰 محفظتي"
BTN_PACKAGES = "📦 الباقات"
BTN_REFERRAL = "👥 إحالاتي"
BTN_WITHDRAW = "💸 سحب الأرباح"
BTN_HELP     = "ℹ️ مساعدة"
BTN_BACK     = "🔙 رجوع"
BTN_HOME     = "🏠 الرئيسية"
BTN_ADMIN    = "👑 لوحة الأدمن"

logging.basicConfig(level=logging.INFO)

# ===================== Reply Keyboards =====================
def main_reply_keyboard():
    return ReplyKeyboardMarkup([
        [BTN_TASKS,    BTN_WALLET],
        [BTN_PACKAGES, BTN_REFERRAL],
        [BTN_WITHDRAW, BTN_HELP],
    ], resize_keyboard=True, persistent=True)

def back_reply_keyboard():
    return ReplyKeyboardMarkup([
        [BTN_BACK, BTN_HOME]
    ], resize_keyboard=True)

def admin_reply_keyboard():
    return ReplyKeyboardMarkup([
        [BTN_HOME, BTN_ADMIN]
    ], resize_keyboard=True)

# ===================== قاعدة البيانات =====================
def init_db():
    conn = sqlite3.connect("teamo.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, serial_no INTEGER,
        username TEXT, full_name TEXT, phone TEXT,
        balance REAL DEFAULT 0, package TEXT DEFAULT NULL,
        wallet TEXT DEFAULT NULL, ref_code TEXT UNIQUE,
        referred_by INTEGER DEFAULT NULL, joined_at TEXT,
        package_expires TEXT DEFAULT NULL
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS user_counter (id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0)")
    c.execute("INSERT OR IGNORE INTO user_counter (id,count) VALUES (1,0)")
    c.execute("""CREATE TABLE IF NOT EXISTS packages_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        package TEXT, price REAL, status TEXT DEFAULT 'pending',
        receipt TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS daily_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        task_date TEXT, tasks_done INTEGER DEFAULT 0, earned REAL DEFAULT 0
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS task_links (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, active INTEGER DEFAULT 1)")
    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        amount REAL, wallet TEXT, status TEXT DEFAULT 'pending', created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS referral_earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        from_user INTEGER, level INTEGER, amount REAL, package TEXT, created_at TEXT
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('wallet',?)", (WALLET_TRC20,))
    c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('tasks_open','1')")
    c.execute("SELECT COUNT(*) FROM task_links")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO task_links (url) VALUES (?)", ("https://youtube.com/watch?v=dQw4w9WgXcQ",))
    try:
        c.execute("ALTER TABLE users ADD COLUMN package_expires TEXT DEFAULT NULL")
    except: pass
    conn.commit(); conn.close()

def db(): return sqlite3.connect("teamo.db")

def get_setting(key):
    conn = db(); c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    r = c.fetchone(); conn.close()
    return r[0] if r else None

def set_setting(key, value):
    conn = db(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))
    conn.commit(); conn.close()

def is_tasks_open():
    return get_setting("tasks_open") == "1"

def tasks_status_text():
    return "🟢 المهام مفتوحة الآن" if is_tasks_open() else "🔴 المهام مغلقة حالياً"

def next_serial():
    conn = db(); c = conn.cursor()
    c.execute("UPDATE user_counter SET count=count+1 WHERE id=1")
    c.execute("SELECT count FROM user_counter WHERE id=1")
    n = c.fetchone()[0]; conn.commit(); conn.close(); return n

def get_user(user_id):
    conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    u = c.fetchone(); conn.close(); return u

def gen_ref_code(user_id): return f"TMO{user_id:06d}"

def register_user(user_id, username, full_name, phone, referred_by=None):
    conn = db(); c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if c.fetchone(): conn.close(); return False
    serial = next_serial()
    c.execute("""INSERT INTO users (user_id,serial_no,username,full_name,phone,ref_code,referred_by,joined_at)
                 VALUES (?,?,?,?,?,?,?,?)""",
              (user_id, serial, username, full_name, phone, gen_ref_code(user_id), referred_by, datetime.now().isoformat()))
    conn.commit(); conn.close(); return True

def get_user_by_refcode(ref_code):
    conn = db(); c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE ref_code=?", (ref_code,))
    r = c.fetchone(); conn.close()
    return r[0] if r else None

def get_ancestors(user_id, levels=6):
    ancestors = []; conn = db(); c = conn.cursor(); current = user_id
    for _ in range(levels):
        c.execute("SELECT referred_by FROM users WHERE user_id=?", (current,))
        row = c.fetchone()
        if not row or not row[0]: break
        ancestors.append(row[0]); current = row[0]
    conn.close(); return ancestors

def distribute_referral_commissions(new_user_id, package_name):
    commissions = REFERRAL_COMMISSIONS.get(package_name, [])
    ancestors = get_ancestors(new_user_id)
    conn = db(); c = conn.cursor()
    for level, ancestor_id in enumerate(ancestors):
        if level >= len(commissions): break
        amount = commissions[level]
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, ancestor_id))
        c.execute("INSERT INTO referral_earnings (user_id,from_user,level,amount,package,created_at) VALUES (?,?,?,?,?,?)",
                  (ancestor_id, new_user_id, level+1, amount, package_name, datetime.now().isoformat()))
    conn.commit(); conn.close()

def activate_package(user_id, package_name):
    expires = (datetime.now() + timedelta(days=PACKAGE_DAYS)).strftime("%Y-%m-%d")
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET package=?, package_expires=? WHERE user_id=?", (package_name, expires, user_id))
    conn.commit(); conn.close()

def is_package_active(user):
    if not user[6]: return False
    if not user[11]: return True
    expires = datetime.strptime(user[11], "%Y-%m-%d")
    return datetime.now() <= expires

def get_today_tasks(user_id):
    today = date.today().isoformat(); conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM daily_tasks WHERE user_id=? AND task_date=?", (user_id, today))
    row = c.fetchone(); conn.close(); return row

def get_task_link():
    conn = db(); c = conn.cursor()
    c.execute("SELECT url FROM task_links WHERE active=1 ORDER BY RANDOM() LIMIT 1")
    r = c.fetchone(); conn.close()
    return r[0] if r else "https://youtube.com"

def complete_task(user_id):
    if not is_tasks_open(): return False, "closed"
    today = date.today().isoformat(); user = get_user(user_id)
    if not user or not user[6]: return False, "no_package"
    if not is_package_active(user): return False, "expired"
    package = PACKAGES[user[6]]; max_tasks, per_task = package["tasks"], package["per_task"]
    conn = db(); c = conn.cursor()
    c.execute("SELECT tasks_done, earned FROM daily_tasks WHERE user_id=? AND task_date=?", (user_id, today))
    row = c.fetchone()
    if row:
        done, earned = row
        if done >= max_tasks: conn.close(); return False, "max_reached"
        done += 1; earned += per_task
        c.execute("UPDATE daily_tasks SET tasks_done=?,earned=? WHERE user_id=? AND task_date=?",
                  (done, earned, user_id, today))
    else:
        done, earned = 1, per_task
        c.execute("INSERT INTO daily_tasks (user_id,task_date,tasks_done,earned) VALUES (?,?,?,?)",
                  (user_id, today, 1, per_task))
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (per_task, user_id))
    conn.commit(); conn.close(); return True, (done, max_tasks, per_task, earned)

def get_stats():
    conn = db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users"); total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM packages_history WHERE status='pending'"); pp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'"); wp = c.fetchone()[0]
    c.execute("SELECT SUM(balance) FROM users"); tb = c.fetchone()[0] or 0
    conn.close(); return total, pp, wp, tb

# ===================== دالة الصفحة الرئيسية =====================
async def send_main_menu(update_or_message, user_id, context=None):
    db_user = get_user(user_id)
    if not db_user: return
    balance = db_user[5]; package = db_user[6]
    today_row = get_today_tasks(user_id)
    done = today_row[3] if today_row and package and is_package_active(db_user) else 0
    total = PACKAGES[package]["tasks"] if package and is_package_active(db_user) else 0
    today_earned = today_row[4] if today_row else 0.0
    expires_text = f"\n📅 تنتهي باقتك: *{db_user[11]}*" if db_user[11] else ""

    text = (f"🏠 *الصفحة الرئيسية*\n\n"
            f"🆔 رقمك: *#{db_user[1]:04d}*\n"
            f"💎 باقتك: *{package or 'لا توجد'}*{expires_text}\n"
            f"💰 رصيدك: *{balance:.2f}$*\n"
            f"📋 مهام اليوم: *{done}/{total}*\n"
            f"💵 ربح اليوم: *{today_earned:.2f}$*\n\n"
            f"{tasks_status_text()}")

    if hasattr(update_or_message, 'reply_text'):
        await update_or_message.reply_text(text, reply_markup=main_reply_keyboard(), parse_mode="Markdown")
    else:
        await update_or_message.message.reply_text(text, reply_markup=main_reply_keyboard(), parse_mode="Markdown")

# ===================== /start =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = None; referrer = None
    if args:
        ref_uid = get_user_by_refcode(args[0])
        if ref_uid and ref_uid != user.id:
            referred_by = ref_uid; referrer = get_user(ref_uid)

    existing = get_user(user.id)
    if not existing:
        context.user_data["referred_by"] = referred_by
        context.user_data["state"] = ST_PHONE
        ref_msg = ""
        if referrer:
            ref_msg = f"\n🎁 *دخلت عبر دعوة:*\n👤 {referrer[3]} | رقم #{referrer[1]:04d}\n\n"
        await update.message.reply_text(
            f"👋 *أهلاً وسهلاً بك في TEAMO!*\n\n"
            f"🚀 منصة المهمات اليومية والربح الحقيقي\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💎 أكمل مهامك اليومية واربح\n"
            f"👥 ادعُ أصدقاءك واربح من 6 مستويات\n"
            f"💸 اسحب أرباحك عبر USDT TRC20\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{ref_msg}"
            f"📱 للتسجيل أرسل *رقم هاتفك* مع رمز الدولة:\n\n"
            f"🇮🇶 `+9647701234567`\n"
            f"🇸🇦 `+966501234567`\n"
            f"🇦🇪 `+971501234567`",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        ); return

    await send_main_menu(update.message, user.id)

# ===================== معالج الرسائل النصية (الأزرار) =====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    text = update.message.text.strip() if update.message.text else ""

    # ── أزرار التنقل الرئيسية ──
    if text == BTN_HOME:
        context.user_data.clear()
        await send_main_menu(update.message, user_id)
        return

    if text == BTN_BACK:
        context.user_data.clear()
        await send_main_menu(update.message, user_id)
        return

    if text == BTN_ADMIN and user_id == ADMIN_ID:
        await show_admin_panel(update.message, user_id)
        return

    # ── أزرار القائمة الرئيسية ──
    if text == BTN_TASKS:
        await show_daily_tasks(update.message, user_id)
        return

    if text == BTN_WALLET:
        await show_wallet(update.message, user_id)
        return

    if text == BTN_PACKAGES:
        await show_packages(update.message)
        return

    if text == BTN_REFERRAL:
        await show_referrals(update.message, user_id, context)
        return

    if text == BTN_WITHDRAW:
        await start_withdraw(update.message, user_id, context)
        return

    if text == BTN_HELP:
        await show_help(update.message)
        return

    # ── حالات المحادثة ──
    if state == ST_PHONE:
        if not text.startswith("+") or len(text) < 10:
            await update.message.reply_text("❌ رقم غير صحيح!\nمثال: `+9647701234567`", parse_mode="Markdown")
            return
        referred_by = context.user_data.get("referred_by")
        u = update.effective_user
        register_user(user_id, u.username or "", u.full_name, text, referred_by)
        context.user_data.clear()
        db_user = get_user(user_id)
        await update.message.reply_text(
            f"✅ *تم التسجيل بنجاح!*\n\n🆔 رقمك: *#{db_user[1]:04d}*\n📱 هاتفك: `{text}`\n\nاختر باقة لتبدأ الربح 💰",
            reply_markup=main_reply_keyboard(), parse_mode="Markdown"
        )
        return

    if state == ST_RECEIPT:
        pkg_name = context.user_data.get("buying_package")
        file_id = None
        if update.message.photo: file_id = update.message.photo[-1].file_id
        elif update.message.document: file_id = update.message.document.file_id
        else:
            await update.message.reply_text("❌ أرسل صورة الوصل فقط."); return
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO packages_history (user_id,package,price,receipt,created_at) VALUES (?,?,?,?,?)",
                  (user_id, pkg_name, PACKAGES[pkg_name]["price"], file_id, datetime.now().isoformat()))
        request_id = c.lastrowid; conn.commit(); conn.close()
        u = get_user(user_id)
        caption = (f"🧾 *طلب شراء #{request_id}*\n\n👤 {u[3]} | #{u[1]:04d}\n📱 {u[4]}\n📦 {pkg_name} — {PACKAGES[pkg_name]['price']}$")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ قبول #{request_id}", callback_data=f"adm_approve_{request_id}"),
            InlineKeyboardButton(f"❌ رفض #{request_id}", callback_data=f"adm_reject_{request_id}")
        ]])
        try:
            if update.message.photo:
                await context.bot.send_photo(ADMIN_ID, file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
            else:
                await context.bot.send_document(ADMIN_ID, file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
        except: pass
        context.user_data.clear()
        await update.message.reply_text(
            "✅ *تم استلام الوصل!*\n\n⏳ سيتم التفعيل خلال 24 ساعة\n📩 ستصلك إشعار فور التفعيل",
            reply_markup=main_reply_keyboard(), parse_mode="Markdown"
        )
        return

    if state == ST_WALLET:
        if len(text) < 30:
            await update.message.reply_text("❌ عنوان غير صحيح. أعد المحاولة:"); return
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET wallet=? WHERE user_id=?", (text, user_id))
        conn.commit(); conn.close()
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ *تم حفظ محفظتك!*\n\n`{text}`",
            reply_markup=main_reply_keyboard(), parse_mode="Markdown"
        )
        return

    if state == ST_WITHDRAW:
        user = get_user(user_id); balance = user[5]; wallet = user[7]
        try: amount = float(text)
        except:
            await update.message.reply_text("❌ أدخل رقماً صحيحاً."); return
        if amount < MIN_WITHDRAW:
            await update.message.reply_text(f"❌ الحد الأدنى {MIN_WITHDRAW}$"); return
        if amount > balance:
            await update.message.reply_text(f"❌ رصيدك غير كافٍ ({balance:.2f}$)"); return
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id))
        c.execute("INSERT INTO withdrawals (user_id,amount,wallet,created_at) VALUES (?,?,?,?)",
                  (user_id, amount, wallet, datetime.now().isoformat()))
        request_id = c.lastrowid; conn.commit(); conn.close()
        u = get_user(user_id)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ قبول #{request_id}", callback_data=f"adm_wapprove_{request_id}"),
            InlineKeyboardButton(f"❌ رفض #{request_id}", callback_data=f"adm_wreject_{request_id}")
        ]])
        try:
            await context.bot.send_message(ADMIN_ID,
                f"💸 *طلب سحب #{request_id}*\n\n👤 {u[3]} | #{u[1]:04d}\n📱 {u[4]}\n💰 *{amount:.2f}$*\n👛 `{wallet}`",
                reply_markup=kb, parse_mode="Markdown")
        except: pass
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ *تم إرسال طلب السحب!*\n\nالمبلغ: *{amount:.2f}$*\n⏳ المعالجة خلال 24-48 ساعة",
            reply_markup=main_reply_keyboard(), parse_mode="Markdown"
        )
        return

    if state == ST_BROADCAST and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id FROM users"); users = c.fetchall(); conn.close()
        sent, failed = 0, 0
        for (uid,) in users:
            try: await context.bot.send_message(uid, text); sent += 1
            except: failed += 1
        context.user_data.clear()
        await update.message.reply_text(f"✅ أُرسلت لـ {sent} | ❌ فشل مع {failed}", reply_markup=admin_reply_keyboard())
        return

    if state == ST_SETWALLET and user_id == ADMIN_ID:
        if len(text) < 20:
            await update.message.reply_text("❌ عنوان غير صحيح."); return
        set_setting("wallet", text); context.user_data.clear()
        await update.message.reply_text(
            f"✅ تم تغيير محفظة الاستلام:\n`{text}`",
            reply_markup=admin_reply_keyboard(), parse_mode="Markdown"
        )
        return

    if state == ST_ADDLINK and user_id == ADMIN_ID:
        if not text.startswith("http"):
            await update.message.reply_text("❌ أرسل رابطاً صحيحاً."); return
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO task_links (url) VALUES (?)", (text,))
        conn.commit(); conn.close(); context.user_data.clear()
        await update.message.reply_text(f"✅ تمت إضافة الرابط:\n{text}", reply_markup=admin_reply_keyboard())
        return

# ===================== دوال الصفحات =====================
async def show_daily_tasks(message, user_id):
    user = get_user(user_id)
    if not user or not user[6] or not is_package_active(user):
        await message.reply_text(
            "❌ *ليس لديك باقة مفعّلة*\n\nاشترِ باقة لتبدأ!",
            reply_markup=back_reply_keyboard(), parse_mode="Markdown"
        )
        return
    pkg = PACKAGES[user[6]]
    today_row = get_today_tasks(user_id)
    done = today_row[3] if today_row else 0; total = pkg["tasks"]
    text = (f"📋 *مهامك اليومية*\n\n"
            f"باقتك: *{user[6]}*\n"
            f"التقدم: *{done}/{total}* ✦\n"
            f"ربح المهمة: *{pkg['per_task']:.2f}$*\n"
            f"إجمالي اليوم: *{pkg['daily']:.2f}$*\n\n"
            f"{tasks_status_text()}\n\n")

    if done >= total:
        text += "🎉 أنجزت جميع مهامك اليوم!"
        await message.reply_text(text, reply_markup=back_reply_keyboard(), parse_mode="Markdown")
    elif not is_tasks_open():
        text += "🔒 المهام مغلقة — انتظر فتحها"
        await message.reply_text(text, reply_markup=back_reply_keyboard(), parse_mode="Markdown")
    else:
        text += "اضغط لإكمال مهمتك 👇"
        link = get_task_link()
        await message.reply_text(text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 افتح الفيديو", url=link)],
                [InlineKeyboardButton("✅ تأكيد إكمال المهمة", callback_data="confirm_task")]
            ]), parse_mode="Markdown")

async def show_wallet(message, user_id):
    user = get_user(user_id); balance = user[5]; wallet = user[7]
    conn = db(); c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM referral_earnings WHERE user_id=?", (user_id,))
    ref_earned = c.fetchone()[0] or 0; conn.close()
    wallet_text = f"`{wallet}`\n_(اضغط للنسخ)_" if wallet else "_لم تُضف بعد_"
    await message.reply_text(
        f"💰 *محفظتي*\n\n"
        f"💎 الرصيد: *{balance:.2f}$*\n"
        f"👥 أرباح الإحالات: *{ref_earned:.2f}$*\n\n"
        f"👛 محفظة TRC20:\n{wallet_text}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تغيير المحفظة" if wallet else "➕ أضف محفظة TRC20", callback_data="add_wallet")],
        ]),
        parse_mode="Markdown"
    )

async def show_packages(message):
    keyboard = []
    for name, pkg in PACKAGES.items():
        keyboard.append([InlineKeyboardButton(
            f"{'⭐ ' if name=='B1' else ''}{name} — {pkg['price']}$ ({pkg['daily']:.2f}$/يوم)",
            callback_data=f"buy_{name}")])
    await message.reply_text(
        f"📦 *اختر باقتك*\n\n✅ الباقة صالحة لمدة *{PACKAGE_DAYS} يوم*\n",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_referrals(message, user_id, context):
    bot_username = (await context.bot.get_me()).username
    user = get_user(user_id); ref_code = user[8]
    ref_link = f"https://t.me/{bot_username}?start={ref_code}"
    conn = db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
    direct = c.fetchone()[0]
    c.execute("SELECT SUM(amount) FROM referral_earnings WHERE user_id=?", (user_id,))
    total_earned = c.fetchone()[0] or 0
    c.execute("SELECT level,COUNT(*),SUM(amount) FROM referral_earnings WHERE user_id=? GROUP BY level", (user_id,))
    levels = {r[0]: (r[1], r[2] or 0) for r in c.fetchall()}; conn.close()

    text = (f"👥 *إحالاتي*\n\n"
            f"🔗 رابط الدعوة:\n`{ref_link}`\n_(اضغط للنسخ)_\n\n"
            f"🎟 كود الإحالة:\n`{ref_code}`\n_(اضغط للنسخ)_\n\n"
            f"👤 إحالات مباشرة: *{direct}*\n"
            f"💰 إجمالي الأرباح: *{total_earned:.2f}$*\n\n"
            f"📊 *التفصيل:*\n")
    for lvl in range(1, 7):
        count, earned = levels.get(lvl, (0, 0))
        text += f"L{lvl}: {count} شخص — {earned:.2f}$\n"
    await message.reply_text(text, reply_markup=back_reply_keyboard(), parse_mode="Markdown")

async def start_withdraw(message, user_id, context):
    user = get_user(user_id)
    if not user or not user[7]:
        await message.reply_text(
            "❌ أضف محفظتك أولاً!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ أضف محفظة", callback_data="add_wallet")]]))
        return
    context.user_data["state"] = ST_WITHDRAW
    await message.reply_text(
        f"💸 *سحب الأرباح*\n\n"
        f"الرصيد: *{user[5]:.2f}$*\n"
        f"الحد الأدنى: *{MIN_WITHDRAW}$*\n"
        f"المحفظة: `{user[7]}`\n_(اضغط للنسخ)_\n\n"
        f"أرسل المبلغ الذي تريد سحبه:",
        reply_markup=back_reply_keyboard(), parse_mode="Markdown"
    )

async def show_help(message):
    await message.reply_text(
        "ℹ️ *كيفية الاستخدام*\n\n"
        "1️⃣ اشترِ باقة وأرسل وصل الدفع\n"
        "2️⃣ انتظر التفعيل (24 ساعة)\n"
        "3️⃣ أكمل مهامك اليومية واربح\n"
        "4️⃣ ادعُ أصدقاءك واربح من 6 مستويات\n"
        "5️⃣ اسحب أرباحك عبر USDT TRC20\n\n"
        f"📅 مدة الباقة: *{PACKAGE_DAYS} يوم*\n"
        f"💸 الحد الأدنى: *{MIN_WITHDRAW}$*",
        reply_markup=back_reply_keyboard(), parse_mode="Markdown"
    )

async def show_admin_panel(message, user_id):
    total, pp, wp, tb = get_stats()
    tasks_open = is_tasks_open()
    toggle_label = "🔴 قفل المهام" if tasks_open else "🟢 فتح المهام"
    await message.reply_text(
        f"👑 *لوحة الأدمن*\n\n"
        f"👥 المستخدمون: *{total}*\n"
        f"⏳ طلبات شراء: *{pp}*\n"
        f"💸 طلبات سحب: *{wp}*\n"
        f"💰 الأرصدة: *{tb:.2f}$*\n\n"
        f"{tasks_status_text()}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 المستخدمون", callback_data="adm_users"),
             InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
            [InlineKeyboardButton("⏳ طلبات الشراء", callback_data="adm_payments"),
             InlineKeyboardButton("💸 طلبات السحب", callback_data="adm_withdrawals")],
            [InlineKeyboardButton("🎬 الفيديوهات", callback_data="adm_links"),
             InlineKeyboardButton("👛 تغيير المحفظة", callback_data="adm_wallet")],
            [InlineKeyboardButton(toggle_label, callback_data="adm_toggle_tasks"),
             InlineKeyboardButton("📢 رسالة جماعية", callback_data="adm_broadcast")]
        ]),
        parse_mode="Markdown"
    )

# ===================== معالج الأزرار Inline =====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user_id = query.from_user.id; data = query.data

    if data == "confirm_task":
        success, result = complete_task(user_id)
        if success:
            done, total, per_task, earned = result
            kb = []
            if done < total:
                kb.append([InlineKeyboardButton(f"▶️ المهمة التالية {done+1}", callback_data="next_task")])
            await query.edit_message_text(
                f"✅ *مبروك!*\n\n💰 ربحت: *{per_task:.2f}$*\n📋 التقدم: *{done}/{total}*\n💵 ربح اليوم: *{earned:.2f}$*\n\n"
                f"{'🎉 أنجزت جميع مهامك!' if done >= total else '💪 استمر!'}",
                reply_markup=InlineKeyboardMarkup(kb) if kb else None,
                parse_mode="Markdown")
        elif result == "closed":
            await query.edit_message_text("⛔ المهام مغلقة الآن.")
        elif result == "expired":
            await query.edit_message_text("❌ انتهت صلاحية باقتك! جدّد اشتراكك.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 الباقات", callback_data="show_packages")]]))
        elif result == "max_reached":
            await query.edit_message_text("⚠️ أكملت جميع مهماتك اليوم! عد غداً 🌟")
        else:
            await query.edit_message_text("❌ ليس لديك باقة مفعّلة!")

    elif data == "next_task":
        user = get_user(user_id)
        if not user or not user[6]: return
        link = get_task_link()
        today_row = get_today_tasks(user_id)
        done = today_row[3] if today_row else 0
        pkg = PACKAGES[user[6]]
        await query.edit_message_text(
            f"📌 *المهمة {done+1}*\n\n1️⃣ شاهد الفيديو 30 ثانية\n2️⃣ اشترك بالقناة\n3️⃣ أعجب بالفيديو\n\nثم اضغط *تأكيد*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 افتح الفيديو", url=link)],
                [InlineKeyboardButton("✅ تأكيد", callback_data="confirm_task")]
            ]), parse_mode="Markdown")

    elif data == "add_wallet":
        context.user_data["state"] = ST_WALLET
        await query.edit_message_text("👛 *أضف محفظة TRC20*\n\nأرسل عنوان محفظتك:", parse_mode="Markdown")

    elif data == "show_packages":
        keyboard = []
        for name, pkg in PACKAGES.items():
            keyboard.append([InlineKeyboardButton(
                f"{'⭐ ' if name=='B1' else ''}{name} — {pkg['price']}$ ({pkg['daily']:.2f}$/يوم)",
                callback_data=f"buy_{name}")])
        await query.edit_message_text(f"📦 *اختر باقتك*\n", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("buy_"):
        pkg_name = data[4:]; pkg = PACKAGES[pkg_name]
        commissions = REFERRAL_COMMISSIONS[pkg_name]; wallet = get_setting("wallet")
        await query.edit_message_text(
            f"📦 *باقة {pkg_name}*\n\n💰 السعر: *{pkg['price']}$*\n📋 *{pkg['tasks']} مهام/يوم*\n"
            f"💵 ربح المهمة: *{pkg['per_task']:.2f}$*\n📈 الربح اليومي: *{pkg['daily']:.2f}$*\n"
            f"📅 المدة: *{PACKAGE_DAYS} يوم*\n\n"
            f"👥 *عمولات الإحالة:*\n"
            f"L1:{commissions[0]}$ | L2:{commissions[1]}$ | L3:{commissions[2]}$\n"
            f"L4:{commissions[3]}$ | L5:{commissions[4]}$ | L6:{commissions[5]}$\n\n"
            f"أرسل *{pkg['price']} USDT TRC20* على:\n`{wallet}`\n_(اضغط للنسخ)_",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 أرسل وصل الدفع", callback_data=f"send_receipt_{pkg_name}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="show_packages")]
            ]), parse_mode="Markdown")

    elif data.startswith("send_receipt_"):
        pkg_name = data[13:]
        context.user_data["buying_package"] = pkg_name
        context.user_data["state"] = ST_RECEIPT
        await query.edit_message_text(
            f"📤 *وصل الدفع — باقة {pkg_name}*\n\nأرسل صورة الوصل الآن 👇\n\n⏳ سيتم التفعيل خلال 24 ساعة",
            parse_mode="Markdown")

    # ── أدمن ──
    elif data == "adm_toggle_tasks" and user_id == ADMIN_ID:
        current = get_setting("tasks_open")
        new_val = "0" if current == "1" else "1"
        set_setting("tasks_open", new_val)
        status = "🟢 مفتوحة" if new_val == "1" else "🔴 مغلقة"
        tasks_open = new_val == "1"
        toggle_label = "🔴 قفل المهام" if tasks_open else "🟢 فتح المهام"
        await query.edit_message_text(
            f"✅ تم تغيير حالة المهام\nالحالة الآن: *{status}*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 المستخدمون", callback_data="adm_users"),
                 InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
                [InlineKeyboardButton("⏳ طلبات الشراء", callback_data="adm_payments"),
                 InlineKeyboardButton("💸 طلبات السحب", callback_data="adm_withdrawals")],
                [InlineKeyboardButton("🎬 الفيديوهات", callback_data="adm_links"),
                 InlineKeyboardButton("👛 تغيير المحفظة", callback_data="adm_wallet")],
                [InlineKeyboardButton(toggle_label, callback_data="adm_toggle_tasks"),
                 InlineKeyboardButton("📢 رسالة جماعية", callback_data="adm_broadcast")]
            ]),
            parse_mode="Markdown")

    elif data == "adm_stats" and user_id == ADMIN_ID:
        total, pp, wp, tb = get_stats(); wallet = get_setting("wallet")
        await query.edit_message_text(
            f"📊 *الإحصائيات*\n\n👥 المستخدمون: *{total}*\n⏳ شراء معلق: *{pp}*\n"
            f"💸 سحب معلق: *{wp}*\n💰 إجمالي الأرصدة: *{tb:.2f}$*\n\n"
            f"👛 محفظة الاستلام:\n`{wallet}`\n\n{tasks_status_text()}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]),
            parse_mode="Markdown")

    elif data == "adm_users" and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("SELECT serial_no,full_name,phone,package,balance,package_expires FROM users ORDER BY serial_no")
        users = c.fetchall(); conn.close()
        text = f"👥 *المستخدمون ({len(users)})*\n\n"
        for u in users[:25]:
            serial, name, phone, pkg, balance, expires = u
            exp_text = f" | ⏳{expires}" if expires else ""
            text += f"*#{serial:04d}* | {name}\n📱{phone or '—'} | 📦{pkg or '—'}{exp_text} | 💰{balance:.2f}$\n\n"
        if len(users) > 25: text += f"... و {len(users)-25} مستخدم آخر"
        await query.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]),
            parse_mode="Markdown")

    elif data == "adm_payments" and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("""SELECT p.id,u.serial_no,u.full_name,u.phone,p.package,p.price
                     FROM packages_history p JOIN users u ON p.user_id=u.user_id
                     WHERE p.status='pending' ORDER BY p.id""")
        payments = c.fetchall(); conn.close()
        if not payments:
            await query.edit_message_text("✅ لا توجد طلبات شراء معلقة",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]])); return
        text = f"⏳ *طلبات الشراء ({len(payments)})*\n\n"; keyboard = []
        for p in payments:
            pid, serial, name, phone, pkg, price = p
            text += f"*#{pid}* | {name} #{serial:04d}\n📱{phone} | 📦{pkg} — {price}$\n\n"
            keyboard.append([
                InlineKeyboardButton(f"✅ قبول #{pid}", callback_data=f"adm_approve_{pid}"),
                InlineKeyboardButton(f"❌ رفض #{pid}", callback_data=f"adm_reject_{pid}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "adm_withdrawals" and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("""SELECT w.id,u.serial_no,u.full_name,u.phone,w.amount,w.wallet
                     FROM withdrawals w JOIN users u ON w.user_id=u.user_id
                     WHERE w.status='pending' ORDER BY w.id""")
        withdrawals = c.fetchall(); conn.close()
        if not withdrawals:
            await query.edit_message_text("✅ لا توجد طلبات سحب معلقة",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]])); return
        text = f"💸 *طلبات السحب ({len(withdrawals)})*\n\n"; keyboard = []
        for w in withdrawals:
            wid, serial, name, phone, amount, wallet = w
            text += f"*#{wid}* | {name} #{serial:04d}\n📱{phone}\n💰 *{amount:.2f}$*\n👛 `{wallet}`\n\n"
            keyboard.append([
                InlineKeyboardButton(f"✅ قبول #{wid}", callback_data=f"adm_wapprove_{wid}"),
                InlineKeyboardButton(f"❌ رفض #{wid}", callback_data=f"adm_wreject_{wid}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "adm_wallet" and user_id == ADMIN_ID:
        context.user_data["state"] = ST_SETWALLET; wallet = get_setting("wallet")
        await query.edit_message_text(
            f"👛 *تغيير محفظة الاستلام*\n\nالحالية:\n`{wallet}`\n\nأرسل العنوان الجديد:",
            parse_mode="Markdown")

    elif data == "adm_links" and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("SELECT id,url FROM task_links WHERE active=1")
        links = c.fetchall(); conn.close()
        text = "🎬 *روابط المهام:*\n\n"; keyboard = []
        for lid, url in links:
            text += f"• {url[:60]}\n"
            keyboard.append([InlineKeyboardButton(f"🗑 حذف #{lid}", callback_data=f"adm_dellink_{lid}")])
        keyboard += [[InlineKeyboardButton("➕ إضافة رابط", callback_data="adm_addlink")],
                     [InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "adm_addlink" and user_id == ADMIN_ID:
        context.user_data["state"] = ST_ADDLINK
        await query.edit_message_text("🎬 أرسل رابط يوتيوب الجديد:")

    elif data.startswith("adm_dellink_") and user_id == ADMIN_ID:
        lid = int(data[12:])
        conn = db(); c = conn.cursor()
        c.execute("UPDATE task_links SET active=0 WHERE id=?", (lid,))
        conn.commit(); conn.close()
        await query.answer("✅ تم حذف الرابط")
        conn = db(); c = conn.cursor()
        c.execute("SELECT id,url FROM task_links WHERE active=1")
        links = c.fetchall(); conn.close()
        text = "🎬 *روابط المهام:*\n\n"; keyboard = []
        for l_id, url in links:
            text += f"• {url[:60]}\n"
            keyboard.append([InlineKeyboardButton(f"🗑 حذف #{l_id}", callback_data=f"adm_dellink_{l_id}")])
        keyboard += [[InlineKeyboardButton("➕ إضافة", callback_data="adm_addlink")],
                     [InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "adm_broadcast" and user_id == ADMIN_ID:
        context.user_data["state"] = ST_BROADCAST
        await query.edit_message_text("📢 أرسل الرسالة الجماعية الآن:")

    elif data == "adm_back" and user_id == ADMIN_ID:
        total, pp, wp, tb = get_stats()
        tasks_open = is_tasks_open()
        toggle_label = "🔴 قفل المهام" if tasks_open else "🟢 فتح المهام"
        await query.edit_message_text(
            f"👑 *لوحة الأدمن*\n\n👥 المستخدمون: *{total}*\n⏳ طلبات شراء: *{pp}*\n"
            f"💸 طلبات سحب: *{wp}*\n\n{tasks_status_text()}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 المستخدمون", callback_data="adm_users"),
                 InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
                [InlineKeyboardButton("⏳ طلبات الشراء", callback_data="adm_payments"),
                 InlineKeyboardButton("💸 طلبات السحب", callback_data="adm_withdrawals")],
                [InlineKeyboardButton("🎬 الفيديوهات", callback_data="adm_links"),
                 InlineKeyboardButton("👛 تغيير المحفظة", callback_data="adm_wallet")],
                [InlineKeyboardButton(toggle_label, callback_data="adm_toggle_tasks"),
                 InlineKeyboardButton("📢 رسالة جماعية", callback_data="adm_broadcast")]
            ]),
            parse_mode="Markdown")

    elif data.startswith("adm_approve_") and user_id == ADMIN_ID:
        request_id = int(data[12:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id,package FROM packages_history WHERE id=? AND status='pending'", (request_id,))
        row = c.fetchone()
        if not row: await query.answer("❌ مُعالَج مسبقاً"); conn.close(); return
        uid, pkg_name = row
        c.execute("UPDATE packages_history SET status='approved' WHERE id=?", (request_id,))
        conn.commit(); conn.close()
        activate_package(uid, pkg_name)
        distribute_referral_commissions(uid, pkg_name)
        expires = (datetime.now() + timedelta(days=PACKAGE_DAYS)).strftime("%Y-%m-%d")
        try:
            await context.bot.send_message(uid,
                f"🎉 *تم تفعيل باقتك {pkg_name}!*\n\n📅 صالحة حتى: *{expires}*\n\nابدأ بإكمال مهامك اليومية 💰",
                reply_markup=main_reply_keyboard(), parse_mode="Markdown")
        except: pass
        await query.edit_message_text(f"✅ تم تفعيل {pkg_name} — طلب #{request_id}\n📅 تنتهي: {expires}")

    elif data.startswith("adm_reject_") and user_id == ADMIN_ID:
        request_id = int(data[11:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id FROM packages_history WHERE id=?", (request_id,))
        row = c.fetchone()
        c.execute("UPDATE packages_history SET status='rejected' WHERE id=?", (request_id,))
        conn.commit(); conn.close()
        if row:
            try: await context.bot.send_message(row[0], "❌ تم رفض وصل الدفع. تواصل مع الدعم.")
            except: pass
        await query.edit_message_text(f"❌ تم رفض الطلب #{request_id}")

    elif data.startswith("adm_wapprove_") and user_id == ADMIN_ID:
        wid = int(data[13:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id,amount,wallet FROM withdrawals WHERE id=? AND status='pending'", (wid,))
        row = c.fetchone()
        if not row: await query.answer("❌ مُعالَج مسبقاً"); conn.close(); return
        uid, amount, wallet = row
        c.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (wid,))
        conn.commit(); conn.close()
        try:
            await context.bot.send_message(uid,
                f"✅ *تم إرسال سحبك!*\n\nالمبلغ: *{amount:.2f}$*\nالمحفظة: `{wallet}`",
                parse_mode="Markdown")
        except: pass
        await query.edit_message_text(f"✅ تم قبول السحب #{wid} — {amount}$")

    elif data.startswith("adm_wreject_") and user_id == ADMIN_ID:
        wid = int(data[12:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id,amount FROM withdrawals WHERE id=? AND status='pending'", (wid,))
        row = c.fetchone()
        if not row: await query.answer("❌ مُعالَج مسبقاً"); conn.close(); return
        uid, amount = row
        c.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))
        conn.commit(); conn.close()
        try: await context.bot.send_message(uid, f"❌ تم رفض طلب السحب. تمت إعادة {amount:.2f}$ لرصيدك.")
        except: pass
        await query.edit_message_text(f"❌ تم رفض السحب #{wid} وإعادة الرصيد")

# ===================== أمر الأدمن =====================
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await show_admin_panel(update.message, update.effective_user.id)
    # إضافة زر الأدمن للكيبورد
    await update.message.reply_text(
        "✅ أنت في وضع الأدمن",
        reply_markup=admin_reply_keyboard()
    )

# ===================== تشغيل =====================
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
    print("🤖 TEAMO Bot يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
