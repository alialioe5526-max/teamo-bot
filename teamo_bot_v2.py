import logging
import sqlite3
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN  = "8578221142:AAFe_J9s1EYZwyb1ao5jffZwo5nFy_hpAK0"
MAIN_ADMIN = 269900681
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

ST_NAME       = "WAITING_NAME"
ST_PHONE      = "WAITING_PHONE"
ST_RECEIPT    = "WAITING_RECEIPT"
ST_WALLET     = "WAITING_WALLET"
ST_WITHDRAW   = "WAITING_WITHDRAW"
ST_BROADCAST  = "WAITING_BROADCAST"
ST_SETWALLET  = "WAITING_SETWALLET"
ST_ADDLINK    = "WAITING_ADDLINK"
ST_SCREENSHOT = "WAITING_SCREENSHOT"

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

def main_kb():
    return ReplyKeyboardMarkup([
        [BTN_TASKS, BTN_WALLET],
        [BTN_PACKAGES, BTN_REFERRAL],
        [BTN_WITHDRAW, BTN_HELP],
    ], resize_keyboard=True, persistent=True)

def back_kb():
    return ReplyKeyboardMarkup([[BTN_BACK, BTN_HOME]], resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup([[BTN_HOME, BTN_ADMIN]], resize_keyboard=True)

def init_db():
    conn = sqlite3.connect("teamo.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        serial_no INTEGER,
        username TEXT,
        full_name TEXT,
        real_name TEXT,
        phone TEXT,
        balance REAL DEFAULT 0,
        package TEXT DEFAULT NULL,
        wallet TEXT DEFAULT NULL,
        ref_code TEXT UNIQUE,
        referred_by INTEGER DEFAULT NULL,
        joined_at TEXT,
        package_expires TEXT DEFAULT NULL,
        is_admin INTEGER DEFAULT 0
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS user_counter (id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0)")
    c.execute("INSERT OR IGNORE INTO user_counter (id,count) VALUES (1,0)")
    c.execute("""CREATE TABLE IF NOT EXISTS packages_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, package TEXT, price REAL,
        status TEXT DEFAULT 'pending', receipt TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS daily_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, task_date TEXT,
        tasks_done INTEGER DEFAULT 0, earned REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS task_screenshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, task_date TEXT, task_num INTEGER,
        file_id TEXT, status TEXT DEFAULT 'pending', created_at TEXT
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS task_links (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, active INTEGER DEFAULT 1)")
    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, amount REAL, wallet TEXT,
        status TEXT DEFAULT 'pending', created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS referral_earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, from_user INTEGER, level INTEGER,
        amount REAL, package TEXT, created_at TEXT
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('wallet',?)", (WALLET_TRC20,))
    c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('tasks_open','1')")
    c.execute("SELECT COUNT(*) FROM task_links")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO task_links (url) VALUES (?)", ("https://youtube.com/watch?v=dQw4w9WgXcQ",))
    for col in ["real_name TEXT", "package_expires TEXT", "is_admin INTEGER DEFAULT 0"]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col}")
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

def is_tasks_open(): return get_setting("tasks_open") == "1"
def tasks_txt(): return "🟢 المهام مفتوحة الآن" if is_tasks_open() else "🔴 المهام مغلقة حالياً"

def next_serial():
    conn = db(); c = conn.cursor()
    c.execute("UPDATE user_counter SET count=count+1 WHERE id=1")
    c.execute("SELECT count FROM user_counter WHERE id=1")
    n = c.fetchone()[0]; conn.commit(); conn.close(); return n

def get_user(uid):
    conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    u = c.fetchone(); conn.close(); return u

def is_admin(uid):
    if uid == MAIN_ADMIN: return True
    u = get_user(uid)
    return bool(u and len(u) > 13 and u[13])

def gen_ref(uid): return f"TMO{uid:06d}"

def register_user(uid, username, real_name, phone, referred_by=None):
    conn = db(); c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if c.fetchone(): conn.close(); return False
    serial = next_serial()
    c.execute("""INSERT INTO users
        (user_id,serial_no,username,full_name,real_name,phone,ref_code,referred_by,joined_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (uid, serial, username, real_name, real_name, phone, gen_ref(uid), referred_by, datetime.now().isoformat()))
    conn.commit(); conn.close(); return True

def get_user_by_ref(ref):
    conn = db(); c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE ref_code=?", (ref,))
    r = c.fetchone(); conn.close()
    return r[0] if r else None

def get_ancestors(uid, levels=6):
    anc = []; conn = db(); c = conn.cursor(); cur = uid
    for _ in range(levels):
        c.execute("SELECT referred_by FROM users WHERE user_id=?", (cur,))
        row = c.fetchone()
        if not row or not row[0]: break
        anc.append(row[0]); cur = row[0]
    conn.close(); return anc

def distribute_commissions(new_uid, pkg):
    comms = REFERRAL_COMMISSIONS.get(pkg, [])
    ancs = get_ancestors(new_uid)
    conn = db(); c = conn.cursor()
    for lvl, anc_id in enumerate(ancs):
        if lvl >= len(comms): break
        amt = comms[lvl]
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, anc_id))
        c.execute("INSERT INTO referral_earnings (user_id,from_user,level,amount,package,created_at) VALUES (?,?,?,?,?,?)",
                  (anc_id, new_uid, lvl+1, amt, pkg, datetime.now().isoformat()))
    conn.commit(); conn.close()

def activate_pkg(uid, pkg):
    expires = (datetime.now() + timedelta(days=PACKAGE_DAYS)).strftime("%Y-%m-%d")
    conn = db(); c = conn.cursor()
    c.execute("UPDATE users SET package=?,package_expires=? WHERE user_id=?", (pkg, expires, uid))
    conn.commit(); conn.close()

def pkg_active(user):
    if not user[7]: return False
    if not user[12]: return True
    try: return datetime.now() <= datetime.strptime(user[12], "%Y-%m-%d")
    except: return True

def get_today(uid):
    today = date.today().isoformat(); conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM daily_tasks WHERE user_id=? AND task_date=?", (uid, today))
    r = c.fetchone(); conn.close(); return r

def get_task_link():
    conn = db(); c = conn.cursor()
    c.execute("SELECT url FROM task_links WHERE active=1 ORDER BY RANDOM() LIMIT 1")
    r = c.fetchone(); conn.close()
    return r[0] if r else "https://youtube.com"

def get_all_admins():
    admins = [MAIN_ADMIN]
    conn = db(); c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_admin=1")
    for row in c.fetchall():
        if row[0] not in admins: admins.append(row[0])
    conn.close(); return admins

def get_stats():
    conn = db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users"); total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM packages_history WHERE status='pending'"); pp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'"); wp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM task_screenshots WHERE status='pending'"); sp = c.fetchone()[0]
    c.execute("SELECT SUM(balance) FROM users"); tb = c.fetchone()[0] or 0
    conn.close(); return total, pp, wp, sp, tb

async def send_home(message, uid):
    u = get_user(uid)
    if not u: return
    balance = u[6]; pkg = u[7]
    today_row = get_today(uid)
    done = today_row[3] if today_row and pkg and pkg_active(u) else 0
    total = PACKAGES[pkg]["tasks"] if pkg and pkg_active(u) else 0
    earned_today = today_row[4] if today_row else 0.0
    name = u[4] or u[3] or "—"
    exp = f"\n📅 تنتهي: *{u[12]}*" if u[12] else ""
    kb = admin_kb() if is_admin(uid) else main_kb()
    await message.reply_text(
        f"🏠 *الصفحة الرئيسية*\n\n"
        f"🆔 رقمك: *#{u[1]:04d}*\n"
        f"👤 اسمك: *{name}*\n"
        f"💎 باقتك: *{pkg or 'لا توجد'}*{exp}\n"
        f"💰 رصيدك: *{balance:.2f}$*\n"
        f"📋 مهام اليوم: *{done}/{total}*\n"
        f"💵 ربح اليوم: *{earned_today:.2f}$*\n\n"
        f"{tasks_txt()}",
        reply_markup=kb, parse_mode="Markdown"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args

    referred_by = None; referrer = None
    if args:
        ruid = get_user_by_ref(args[0])
        if ruid and ruid != uid:
            referred_by = ruid; referrer = get_user(ruid)

    existing = get_user(uid)
    if existing:
        await send_home(update.message, uid)
        return

    # إذا في منتصف التسجيل — أكمل
    state = context.user_data.get("state")
    if state == ST_PHONE:
        await update.message.reply_text(
            "📱 أكمل التسجيل — أرسل رقم هاتفك:\n\n🇮🇶 `+9647701234567`",
            parse_mode="Markdown"); return
    if state == ST_NAME:
        await update.message.reply_text(
            "📝 أكمل التسجيل — أرسل *اسمك الثلاثي*:",
            parse_mode="Markdown"); return

    context.user_data["referred_by"] = referred_by
    context.user_data["state"] = ST_NAME

    ref_msg = ""
    if referrer:
        ref_name = referrer[4] or referrer[3] or "—"
        ref_msg = f"\n🎁 *دخلت عبر دعوة:*\n👤 {ref_name} | رقم #{referrer[1]:04d}\n\n"

    await update.message.reply_text(
        f"👋 *أهلاً وسهلاً بك في TEAMO!*\n\n"
        f"🚀 منصة المهمات اليومية والربح الحقيقي\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💎 أكمل مهامك اليومية واربح\n"
        f"👥 ادعُ أصدقاءك واربح من 6 مستويات\n"
        f"💸 اسحب أرباحك عبر USDT TRC20\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{ref_msg}"
        f"📝 أرسل *اسمك الثلاثي* للتسجيل:",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )

async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = context.user_data.get("state")
    text = update.message.text.strip() if update.message.text else ""

    # أزرار التنقل دائماً تعمل
    if text in [BTN_HOME, BTN_BACK]:
        context.user_data.clear()
        await send_home(update.message, uid); return
    if text == BTN_ADMIN and is_admin(uid):
        await show_admin(update.message, uid); return
    if text == BTN_TASKS:
        await show_tasks(update.message, uid); return
    if text == BTN_WALLET:
        await show_wallet(update.message, uid); return
    if text == BTN_PACKAGES:
        await show_packages(update.message); return
    if text == BTN_REFERRAL:
        await show_referrals(update.message, uid, context); return
    if text == BTN_WITHDRAW:
        await start_withdraw(update.message, uid, context); return
    if text == BTN_HELP:
        await show_help(update.message); return

    # ── الاسم الثلاثي ──
    if state == ST_NAME:
        if len(text.split()) < 2:
            await update.message.reply_text(
                "❌ أرسل اسمك الثلاثي كاملاً\nمثال: *محمد أحمد علي*",
                parse_mode="Markdown"); return
        context.user_data["real_name"] = text
        context.user_data["state"] = ST_PHONE
        await update.message.reply_text(
            f"✅ اسمك: *{text}*\n\n📱 أرسل رقم هاتفك مع رمز الدولة:\n\n"
            f"🇮🇶 `+9647701234567`\n🇸🇦 `+966501234567`\n🇦🇪 `+971501234567`",
            parse_mode="Markdown"); return

    # ── رقم الهاتف — يعمل حتى بدون حالة ──
    if state == ST_PHONE or (text.startswith("+") and len(text) >= 10 and not get_user(uid)):
        if not text.startswith("+") or len(text) < 10:
            await update.message.reply_text(
                "❌ رقم غير صحيح!\nمثال: `+9647701234567`", parse_mode="Markdown"); return
        real_name = context.user_data.get("real_name") or update.effective_user.full_name
        referred_by = context.user_data.get("referred_by")
        u = update.effective_user
        register_user(uid, u.username or "", real_name, text, referred_by)
        context.user_data.clear()
        db_user = get_user(uid)
        await update.message.reply_text(
            f"✅ *تم التسجيل بنجاح!*\n\n"
            f"🆔 رقمك: *#{db_user[1]:04d}*\n"
            f"👤 اسمك: *{real_name}*\n"
            f"📱 هاتفك: `{text}`\n\n"
            f"اختر باقة لتبدأ الربح 💰",
            reply_markup=main_kb(), parse_mode="Markdown"); return

    # ── وصل الدفع ──
    if state == ST_RECEIPT:
        pkg_name = context.user_data.get("buying_package")
        file_id = None
        if update.message.photo: file_id = update.message.photo[-1].file_id
        elif update.message.document: file_id = update.message.document.file_id
        else:
            await update.message.reply_text("❌ أرسل صورة الوصل فقط."); return
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO packages_history (user_id,package,price,receipt,created_at) VALUES (?,?,?,?,?)",
                  (uid, pkg_name, PACKAGES[pkg_name]["price"], file_id, datetime.now().isoformat()))
        rid = c.lastrowid; conn.commit(); conn.close()
        u = get_user(uid)
        caption = f"🧾 *طلب شراء #{rid}*\n\n👤 {u[4]} | #{u[1]:04d}\n📱 {u[5]}\n📦 {pkg_name} — {PACKAGES[pkg_name]['price']}$"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ قبول #{rid}", callback_data=f"ap_{rid}"),
            InlineKeyboardButton(f"❌ رفض #{rid}", callback_data=f"rj_{rid}")
        ]])
        for adm in get_all_admins():
            try:
                if update.message.photo:
                    await context.bot.send_photo(adm, file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
                else:
                    await context.bot.send_document(adm, file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
            except: pass
        context.user_data.clear()
        await update.message.reply_text(
            "✅ *تم استلام الوصل!*\n\n⏳ سيتم التفعيل خلال 24 ساعة",
            reply_markup=main_kb(), parse_mode="Markdown"); return

    # ── سكرين شوت المهمة ──
    if state == ST_SCREENSHOT:
        file_id = None
        if update.message.photo: file_id = update.message.photo[-1].file_id
        else:
            await update.message.reply_text("❌ أرسل صورة السكرين شوت فقط."); return
        task_num = context.user_data.get("task_num", 1)
        today = date.today().isoformat()
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO task_screenshots (user_id,task_date,task_num,file_id,created_at) VALUES (?,?,?,?,?)",
                  (uid, today, task_num, file_id, datetime.now().isoformat()))
        sid = c.lastrowid; conn.commit(); conn.close()
        u = get_user(uid)
        caption = (f"📸 *سكرين شوت مهمة #{sid}*\n\n"
                   f"👤 {u[4]} | #{u[1]:04d}\n📱 {u[5]}\n"
                   f"📋 المهمة: {task_num}\n📅 {today}")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ قبول #{sid}", callback_data=f"sap_{sid}"),
            InlineKeyboardButton(f"❌ رفض #{sid}", callback_data=f"srj_{sid}")
        ]])
        for adm in get_all_admins():
            try: await context.bot.send_photo(adm, file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
            except: pass
        context.user_data.clear()
        await update.message.reply_text(
            "✅ *تم إرسال السكرين شوت!*\n\n⏳ سيتم مراجعته وإضافة نقاطك",
            reply_markup=main_kb(), parse_mode="Markdown"); return

    # ── محفظة المستخدم ──
    if state == ST_WALLET:
        if len(text) < 30:
            await update.message.reply_text("❌ عنوان غير صحيح. أعد المحاولة:"); return
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET wallet=? WHERE user_id=?", (text, uid))
        conn.commit(); conn.close()
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ *تم حفظ محفظتك!*\n\n`{text}`",
            reply_markup=main_kb(), parse_mode="Markdown"); return

    # ── السحب ──
    if state == ST_WITHDRAW:
        u = get_user(uid); balance = u[6]; wallet = u[8]
        try: amount = float(text)
        except:
            await update.message.reply_text("❌ أدخل رقماً صحيحاً."); return
        if amount < MIN_WITHDRAW:
            await update.message.reply_text(f"❌ الحد الأدنى {MIN_WITHDRAW}$"); return
        if amount > balance:
            await update.message.reply_text(f"❌ رصيدك غير كافٍ ({balance:.2f}$)"); return
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid))
        c.execute("INSERT INTO withdrawals (user_id,amount,wallet,created_at) VALUES (?,?,?,?)",
                  (uid, amount, wallet, datetime.now().isoformat()))
        wid = c.lastrowid; conn.commit(); conn.close()
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ قبول #{wid}", callback_data=f"wap_{wid}"),
            InlineKeyboardButton(f"❌ رفض #{wid}", callback_data=f"wrj_{wid}")
        ]])
        for adm in get_all_admins():
            try:
                await context.bot.send_message(adm,
                    f"💸 *طلب سحب #{wid}*\n\n👤 {u[4]} | #{u[1]:04d}\n📱 {u[5]}\n💰 *{amount:.2f}$*\n👛 `{wallet}`",
                    reply_markup=kb, parse_mode="Markdown")
            except: pass
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ *تم إرسال طلب السحب!*\n\nالمبلغ: *{amount:.2f}$*\n⏳ خلال 24-48 ساعة",
            reply_markup=main_kb(), parse_mode="Markdown"); return

    # ── أدمن: رسالة جماعية ──
    if state == ST_BROADCAST and is_admin(uid):
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id FROM users"); users = c.fetchall(); conn.close()
        sent = failed = 0
        for (u_id,) in users:
            try: await context.bot.send_message(u_id, text); sent += 1
            except: failed += 1
        context.user_data.clear()
        await update.message.reply_text(f"✅ أُرسلت لـ {sent} | ❌ فشل مع {failed}",
            reply_markup=admin_kb()); return

    if state == ST_SETWALLET and is_admin(uid):
        if len(text) < 20:
            await update.message.reply_text("❌ عنوان غير صحيح."); return
        set_setting("wallet", text); context.user_data.clear()
        await update.message.reply_text(f"✅ تم تغيير محفظة الاستلام:\n`{text}`",
            reply_markup=admin_kb(), parse_mode="Markdown"); return

    if state == ST_ADDLINK and is_admin(uid):
        if not text.startswith("http"):
            await update.message.reply_text("❌ أرسل رابطاً صحيحاً."); return
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO task_links (url) VALUES (?)", (text,))
        conn.commit(); conn.close(); context.user_data.clear()
        await update.message.reply_text(f"✅ تمت إضافة الرابط:\n{text}",
            reply_markup=admin_kb()); return

async def show_tasks(message, uid):
    u = get_user(uid)
    if not u or not u[7] or not pkg_active(u):
        await message.reply_text("❌ *ليس لديك باقة مفعّلة*\n\nاشترِ باقة لتبدأ!",
            reply_markup=back_kb(), parse_mode="Markdown"); return
    pkg = PACKAGES[u[7]]
    today_row = get_today(uid)
    done = today_row[3] if today_row else 0; total = pkg["tasks"]
    text = (f"📋 *مهامك اليومية*\n\nباقتك: *{u[7]}*\nالتقدم: *{done}/{total}* ✦\n"
            f"ربح المهمة: *{pkg['per_task']:.2f}$*\nإجمالي اليوم: *{pkg['daily']:.2f}$*\n\n{tasks_txt()}\n\n")
    if done >= total:
        text += "🎉 أنجزت جميع مهامك اليوم!"
        await message.reply_text(text, reply_markup=back_kb(), parse_mode="Markdown")
    elif not is_tasks_open():
        text += "🔒 المهام مغلقة — انتظر فتحها"
        await message.reply_text(text, reply_markup=back_kb(), parse_mode="Markdown")
    else:
        text += "اضغط لبدء المهمة 👇"
        link = get_task_link()
        await message.reply_text(text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 افتح الفيديو", url=link)],
                [InlineKeyboardButton("📸 أرسل سكرين شوت التأكيد", callback_data=f"do_task_{done+1}")]
            ]), parse_mode="Markdown")

async def show_wallet(message, uid):
    u = get_user(uid); balance = u[6]; wallet = u[8]
    conn = db(); c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM referral_earnings WHERE user_id=?", (uid,))
    ref_earned = c.fetchone()[0] or 0; conn.close()
    wt = f"`{wallet}`\n_(اضغط للنسخ)_" if wallet else "_لم تُضف بعد_"
    await message.reply_text(
        f"💰 *محفظتي*\n\n💎 الرصيد: *{balance:.2f}$*\n👥 أرباح الإحالات: *{ref_earned:.2f}$*\n\n👛 محفظة TRC20:\n{wt}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تغيير المحفظة" if wallet else "➕ أضف محفظة", callback_data="add_wallet")]
        ]), parse_mode="Markdown")

async def show_packages(message):
    kb = []
    for name, pkg in PACKAGES.items():
        kb.append([InlineKeyboardButton(
            f"{'⭐ ' if name=='B1' else ''}{name} — {pkg['price']}$ ({pkg['daily']:.2f}$/يوم)",
            callback_data=f"buy_{name}")])
    await message.reply_text(f"📦 *اختر باقتك*\n\n✅ صالحة لمدة *{PACKAGE_DAYS} يوم*",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_referrals(message, uid, context):
    bot_username = (await context.bot.get_me()).username
    u = get_user(uid); ref_code = u[9]
    link = f"https://t.me/{bot_username}?start={ref_code}"
    conn = db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,))
    direct = c.fetchone()[0]
    c.execute("SELECT SUM(amount) FROM referral_earnings WHERE user_id=?", (uid,))
    total_e = c.fetchone()[0] or 0
    c.execute("SELECT level,COUNT(*),SUM(amount) FROM referral_earnings WHERE user_id=? GROUP BY level", (uid,))
    lvls = {r[0]: (r[1], r[2] or 0) for r in c.fetchall()}; conn.close()
    text = (f"👥 *إحالاتي*\n\n🔗 رابط الدعوة:\n`{link}`\n_(اضغط للنسخ)_\n\n"
            f"🎟 كودك:\n`{ref_code}`\n_(اضغط للنسخ)_\n\n"
            f"👤 مباشر: *{direct}* | 💰 إجمالي: *{total_e:.2f}$*\n\n📊 *التفصيل:*\n")
    for lvl in range(1, 7):
        cnt, earned = lvls.get(lvl, (0, 0))
        text += f"L{lvl}: {cnt} شخص — {earned:.2f}$\n"
    await message.reply_text(text, reply_markup=back_kb(), parse_mode="Markdown")

async def start_withdraw(message, uid, context):
    u = get_user(uid)
    if not u or not u[8]:
        await message.reply_text("❌ أضف محفظتك أولاً!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ أضف محفظة", callback_data="add_wallet")]])); return
    context.user_data["state"] = ST_WITHDRAW
    await message.reply_text(
        f"💸 *سحب الأرباح*\n\nالرصيد: *{u[6]:.2f}$*\nالحد الأدنى: *{MIN_WITHDRAW}$*\n"
        f"المحفظة: `{u[8]}`\n_(اضغط للنسخ)_\n\nأرسل المبلغ:",
        reply_markup=back_kb(), parse_mode="Markdown")

async def show_help(message):
    await message.reply_text(
        "ℹ️ *كيفية الاستخدام*\n\n1️⃣ اشترِ باقة وأرسل وصل الدفع\n2️⃣ انتظر التفعيل (24 ساعة)\n"
        "3️⃣ أكمل مهامك وأرسل سكرين شوت\n4️⃣ ادعُ أصدقاءك واربح 6 مستويات\n"
        "5️⃣ اسحب عبر USDT TRC20\n\n"
        f"📅 مدة الباقة: *{PACKAGE_DAYS} يوم*\n💸 الحد الأدنى: *{MIN_WITHDRAW}$*",
        reply_markup=back_kb(), parse_mode="Markdown")

async def show_admin(message, uid):
    total, pp, wp, sp, tb = get_stats()
    tasks_open = is_tasks_open()
    toggle = "🔴 قفل المهام" if tasks_open else "🟢 فتح المهام"
    await message.reply_text(
        f"👑 *لوحة الأدمن*\n\n"
        f"👥 المستخدمون: *{total}*\n"
        f"⏳ طلبات شراء: *{pp}*\n"
        f"💸 طلبات سحب: *{wp}*\n"
        f"📸 سكرين شوت: *{sp}*\n"
        f"💰 الأرصدة: *{tb:.2f}$*\n\n{tasks_txt()}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 المستخدمون", callback_data="au"),
             InlineKeyboardButton("📊 الإحصائيات", callback_data="as_")],
            [InlineKeyboardButton("⏳ طلبات الشراء", callback_data="ap_list"),
             InlineKeyboardButton("💸 طلبات السحب", callback_data="aw_list")],
            [InlineKeyboardButton("📸 سكرين شوت", callback_data="ass"),
             InlineKeyboardButton("🎬 الفيديوهات", callback_data="al")],
            [InlineKeyboardButton("👛 تغيير المحفظة", callback_data="awt"),
             InlineKeyboardButton(toggle, callback_data="at")],
            [InlineKeyboardButton("📢 رسالة جماعية", callback_data="ab")]
        ]),
        parse_mode="Markdown")

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; data = q.data

    if data.startswith("do_task_"):
        task_num = int(data[8:])
        context.user_data["state"] = ST_SCREENSHOT
        context.user_data["task_num"] = task_num
        await q.edit_message_text(
            f"📸 *تأكيد المهمة {task_num}*\n\n"
            f"أرسل سكرين شوت يُثبت:\n✅ مشاهدة الفيديو\n✅ الاشتراك بالقناة\n✅ الإعجاب بالفيديو\n\n"
            f"⚠️ السكرين شوت لازم يكون من داخل يوتيوب ويُظهر الاشتراك والإعجاب",
            parse_mode="Markdown")

    elif data == "add_wallet":
        context.user_data["state"] = ST_WALLET
        await q.edit_message_text("👛 أرسل عنوان محفظتك TRC20:")

    elif data.startswith("buy_"):
        pkg_name = data[4:]; pkg = PACKAGES[pkg_name]
        comms = REFERRAL_COMMISSIONS[pkg_name]; wallet = get_setting("wallet")
        await q.edit_message_text(
            f"📦 *باقة {pkg_name}*\n\n💰 السعر: *{pkg['price']}$*\n📋 *{pkg['tasks']} مهام/يوم*\n"
            f"💵 ربح المهمة: *{pkg['per_task']:.2f}$*\n📈 اليومي: *{pkg['daily']:.2f}$*\n"
            f"📅 المدة: *{PACKAGE_DAYS} يوم*\n\n"
            f"👥 *عمولات الإحالة:*\nL1:{comms[0]}$ | L2:{comms[1]}$ | L3:{comms[2]}$\n"
            f"L4:{comms[3]}$ | L5:{comms[4]}$ | L6:{comms[5]}$\n\n"
            f"أرسل *{pkg['price']} USDT TRC20* على:\n`{wallet}`\n_(اضغط للنسخ)_",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 أرسل وصل الدفع", callback_data=f"sr_{pkg_name}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="pkgs")]
            ]), parse_mode="Markdown")

    elif data == "pkgs":
        kb = []
        for name, pkg in PACKAGES.items():
            kb.append([InlineKeyboardButton(
                f"{'⭐ ' if name=='B1' else ''}{name} — {pkg['price']}$ ({pkg['daily']:.2f}$/يوم)",
                callback_data=f"buy_{name}")])
        await q.edit_message_text(f"📦 *اختر باقتك*\n\n✅ صالحة لمدة *{PACKAGE_DAYS} يوم*",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data.startswith("sr_"):
        pkg_name = data[3:]
        context.user_data["buying_package"] = pkg_name
        context.user_data["state"] = ST_RECEIPT
        await q.edit_message_text(
            f"📤 *وصل الدفع — باقة {pkg_name}*\n\nأرسل صورة الوصل الآن 👇\n\n⏳ سيتم التفعيل خلال 24 ساعة",
            parse_mode="Markdown")

    elif data.startswith("sap_") and is_admin(uid):
        sid = int(data[4:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id,task_num,task_date FROM task_screenshots WHERE id=? AND status='pending'", (sid,))
        row = c.fetchone()
        if not row: await q.answer("❌ مُعالَج مسبقاً"); conn.close(); return
        target_uid, task_num, task_date = row
        c.execute("UPDATE task_screenshots SET status='approved' WHERE id=?", (sid,))
        target_user = get_user(target_uid)
        per_task = 0
        if target_user and target_user[7]:
            pkg = PACKAGES[target_user[7]]; per_task = pkg["per_task"]
            c.execute("SELECT tasks_done,earned FROM daily_tasks WHERE user_id=? AND task_date=?", (target_uid, task_date))
            tr = c.fetchone()
            if tr:
                c.execute("UPDATE daily_tasks SET tasks_done=tasks_done+1,earned=earned+? WHERE user_id=? AND task_date=?",
                          (per_task, target_uid, task_date))
            else:
                c.execute("INSERT INTO daily_tasks (user_id,task_date,tasks_done,earned) VALUES (?,?,?,?)",
                          (target_uid, task_date, 1, per_task))
            c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (per_task, target_uid))
        conn.commit(); conn.close()
        try:
            await context.bot.send_message(target_uid,
                f"✅ *تمت الموافقة على مهمتك!*\n\n💰 ربحت: *{per_task:.2f}$*",
                reply_markup=main_kb(), parse_mode="Markdown")
        except: pass
        try: await q.edit_message_caption(caption=f"✅ تمت الموافقة على السكرين شوت #{sid}")
        except: await q.edit_message_text(f"✅ تمت الموافقة على السكرين شوت #{sid}")

    elif data.startswith("srj_") and is_admin(uid):
        sid = int(data[4:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id FROM task_screenshots WHERE id=?", (sid,))
        row = c.fetchone()
        c.execute("UPDATE task_screenshots SET status='rejected' WHERE id=?", (sid,))
        conn.commit(); conn.close()
        if row:
            try: await context.bot.send_message(row[0], "❌ تم رفض السكرين شوت. أعد المحاولة بصورة واضحة.")
            except: pass
        try: await q.edit_message_caption(caption=f"❌ تم رفض السكرين شوت #{sid}")
        except: await q.edit_message_text(f"❌ تم رفض السكرين شوت #{sid}")

    elif data.startswith("ap_") and is_admin(uid):
        rid = int(data[3:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id,package FROM packages_history WHERE id=? AND status='pending'", (rid,))
        row = c.fetchone()
        if not row: await q.answer("❌ مُعالَج مسبقاً"); conn.close(); return
        target_uid, pkg_name = row
        c.execute("UPDATE packages_history SET status='approved' WHERE id=?", (rid,))
        conn.commit(); conn.close()
        activate_pkg(target_uid, pkg_name)
        distribute_commissions(target_uid, pkg_name)
        expires = (datetime.now() + timedelta(days=PACKAGE_DAYS)).strftime("%Y-%m-%d")
        try:
            await context.bot.send_message(target_uid,
                f"🎉 *تم تفعيل باقتك {pkg_name}!*\n\n📅 صالحة حتى: *{expires}*\n\nابدأ بإكمال مهامك اليومية 💰",
                reply_markup=main_kb(), parse_mode="Markdown")
        except: pass
        try: await q.edit_message_caption(caption=f"✅ تم تفعيل {pkg_name} — طلب #{rid}\n📅 تنتهي: {expires}")
        except: await q.edit_message_text(f"✅ تم تفعيل {pkg_name} — طلب #{rid}\n📅 تنتهي: {expires}")

    elif data.startswith("rj_") and is_admin(uid):
        rid = int(data[3:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id FROM packages_history WHERE id=?", (rid,))
        row = c.fetchone()
        c.execute("UPDATE packages_history SET status='rejected' WHERE id=?", (rid,))
        conn.commit(); conn.close()
        if row:
            try: await context.bot.send_message(row[0], "❌ تم رفض وصل الدفع. تواصل مع الدعم.")
            except: pass
        try: await q.edit_message_caption(caption=f"❌ تم رفض الطلب #{rid}")
        except: await q.edit_message_text(f"❌ تم رفض الطلب #{rid}")

    elif data.startswith("wap_") and is_admin(uid):
        wid = int(data[4:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id,amount,wallet FROM withdrawals WHERE id=? AND status='pending'", (wid,))
        row = c.fetchone()
        if not row: await q.answer("❌ مُعالَج مسبقاً"); conn.close(); return
        target_uid, amount, wallet = row
        c.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (wid,))
        conn.commit(); conn.close()
        try:
            await context.bot.send_message(target_uid,
                f"✅ *تم إرسال سحبك!*\n\nالمبلغ: *{amount:.2f}$*\nالمحفظة: `{wallet}`",
                parse_mode="Markdown")
        except: pass
        await q.edit_message_text(f"✅ تم قبول السحب #{wid} — {amount}$")

    elif data.startswith("wrj_") and is_admin(uid):
        wid = int(data[4:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id,amount FROM withdrawals WHERE id=? AND status='pending'", (wid,))
        row = c.fetchone()
        if not row: await q.answer("❌ مُعالَج مسبقاً"); conn.close(); return
        target_uid, amount = row
        c.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, target_uid))
        conn.commit(); conn.close()
        try: await context.bot.send_message(target_uid, f"❌ تم رفض طلب السحب. تمت إعادة {amount:.2f}$ لرصيدك.")
        except: pass
        await q.edit_message_text(f"❌ تم رفض السحب #{wid} وإعادة الرصيد")

    elif data == "at" and is_admin(uid):
        cur = get_setting("tasks_open")
        new = "0" if cur == "1" else "1"
        set_setting("tasks_open", new)
        status = "🟢 مفتوحة" if new == "1" else "🔴 مغلقة"
        toggle = "🔴 قفل المهام" if new == "1" else "🟢 فتح المهام"
        total, pp, wp, sp, tb = get_stats()
        await q.edit_message_text(
            f"✅ المهام الآن: *{status}*\n\n👥 {total} | ⏳{pp} | 💸{wp} | 📸{sp}\n\n{tasks_txt()}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 المستخدمون", callback_data="au"),
                 InlineKeyboardButton("📊 الإحصائيات", callback_data="as_")],
                [InlineKeyboardButton("⏳ طلبات الشراء", callback_data="ap_list"),
                 InlineKeyboardButton("💸 طلبات السحب", callback_data="aw_list")],
                [InlineKeyboardButton("📸 سكرين شوت", callback_data="ass"),
                 InlineKeyboardButton("🎬 الفيديوهات", callback_data="al")],
                [InlineKeyboardButton("👛 تغيير المحفظة", callback_data="awt"),
                 InlineKeyboardButton(toggle, callback_data="at")],
                [InlineKeyboardButton("📢 رسالة جماعية", callback_data="ab")]
            ]), parse_mode="Markdown")

    elif data == "as_" and is_admin(uid):
        total, pp, wp, sp, tb = get_stats(); wallet = get_setting("wallet")
        await q.edit_message_text(
            f"📊 *الإحصائيات*\n\n👥 المستخدمون: *{total}*\n⏳ شراء معلق: *{pp}*\n"
            f"💸 سحب معلق: *{wp}*\n📸 سكرين شوت معلق: *{sp}*\n💰 الأرصدة: *{tb:.2f}$*\n\n"
            f"👛 محفظة الاستلام:\n`{wallet}`\n\n{tasks_txt()}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="aback")]]),
            parse_mode="Markdown")

    elif data == "au" and is_admin(uid):
        conn = db(); c = conn.cursor()
        c.execute("SELECT serial_no,real_name,phone,package,balance,package_expires FROM users ORDER BY serial_no")
        users = c.fetchall(); conn.close()
        text = f"👥 *المستخدمون ({len(users)})*\n\n"
        for u in users[:25]:
            serial, name, phone, pkg, balance, expires = u
            exp = f" | ⏳{expires}" if expires else ""
            text += f"*#{serial:04d}* | {name or '—'}\n📱{phone or '—'} | 📦{pkg or '—'}{exp} | 💰{balance:.2f}$\n\n"
        if len(users) > 25: text += f"... و {len(users)-25} آخر"
        await q.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="aback")]]),
            parse_mode="Markdown")

    elif data == "ap_list" and is_admin(uid):
        conn = db(); c = conn.cursor()
        c.execute("""SELECT p.id,u.serial_no,u.real_name,u.phone,p.package,p.price
                     FROM packages_history p JOIN users u ON p.user_id=u.user_id
                     WHERE p.status='pending' ORDER BY p.id""")
        payments = c.fetchall(); conn.close()
        if not payments:
            await q.edit_message_text("✅ لا توجد طلبات شراء معلقة",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="aback")]])); return
        text = f"⏳ *طلبات الشراء ({len(payments)})*\n\n"; kb = []
        for p in payments:
            pid, serial, name, phone, pkg, price = p
            text += f"*#{pid}* | {name} #{serial:04d}\n📱{phone} | 📦{pkg} — {price}$\n\n"
            kb.append([InlineKeyboardButton(f"✅ قبول #{pid}", callback_data=f"ap_{pid}"),
                       InlineKeyboardButton(f"❌ رفض #{pid}", callback_data=f"rj_{pid}")])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="aback")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "aw_list" and is_admin(uid):
        conn = db(); c = conn.cursor()
        c.execute("""SELECT w.id,u.serial_no,u.real_name,u.phone,w.amount,w.wallet
                     FROM withdrawals w JOIN users u ON w.user_id=u.user_id
                     WHERE w.status='pending' ORDER BY w.id""")
        wds = c.fetchall(); conn.close()
        if not wds:
            await q.edit_message_text("✅ لا توجد طلبات سحب معلقة",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="aback")]])); return
        text = f"💸 *طلبات السحب ({len(wds)})*\n\n"; kb = []
        for w in wds:
            wid, serial, name, phone, amount, wallet = w
            text += f"*#{wid}* | {name} #{serial:04d}\n📱{phone}\n💰 *{amount:.2f}$*\n👛 `{wallet}`\n\n"
            kb.append([InlineKeyboardButton(f"✅ قبول #{wid}", callback_data=f"wap_{wid}"),
                       InlineKeyboardButton(f"❌ رفض #{wid}", callback_data=f"wrj_{wid}")])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="aback")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "ass" and is_admin(uid):
        conn = db(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM task_screenshots WHERE status='pending'")
        sp = c.fetchone()[0]; conn.close()
        await q.edit_message_text(
            f"📸 *سكرين شوت المهام*\n\nمعلق: *{sp}*\n\nالسكرين شوت يُرسل لك مباشرة مع أزرار القبول والرفض 👆",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="aback")]]),
            parse_mode="Markdown")

    elif data == "al" and is_admin(uid):
        conn = db(); c = conn.cursor()
        c.execute("SELECT id,url FROM task_links WHERE active=1")
        links = c.fetchall(); conn.close()
        text = "🎬 *روابط المهام:*\n\n"; kb = []
        for lid, url in links:
            text += f"• {url[:60]}\n"
            kb.append([InlineKeyboardButton(f"🗑 حذف #{lid}", callback_data=f"dl_{lid}")])
        kb += [[InlineKeyboardButton("➕ إضافة رابط", callback_data="addl")],
               [InlineKeyboardButton("🔙 رجوع", callback_data="aback")]]
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "addl" and is_admin(uid):
        context.user_data["state"] = ST_ADDLINK
        await q.edit_message_text("🎬 أرسل رابط يوتيوب الجديد:")

    elif data.startswith("dl_") and is_admin(uid):
        lid = int(data[3:])
        conn = db(); c = conn.cursor()
        c.execute("UPDATE task_links SET active=0 WHERE id=?", (lid,))
        conn.commit(); conn.close()
        await q.answer("✅ تم حذف الرابط")
        conn = db(); c = conn.cursor()
        c.execute("SELECT id,url FROM task_links WHERE active=1")
        links = c.fetchall(); conn.close()
        text = "🎬 *روابط المهام:*\n\n"; kb = []
        for l_id, url in links:
            text += f"• {url[:60]}\n"
            kb.append([InlineKeyboardButton(f"🗑 حذف #{l_id}", callback_data=f"dl_{l_id}")])
        kb += [[InlineKeyboardButton("➕ إضافة", callback_data="addl")],
               [InlineKeyboardButton("🔙 رجوع", callback_data="aback")]]
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "awt" and is_admin(uid):
        context.user_data["state"] = ST_SETWALLET
        wallet = get_setting("wallet")
        await q.edit_message_text(
            f"👛 *تغيير محفظة الاستلام*\n\nالحالية:\n`{wallet}`\n\nأرسل العنوان الجديد:",
            parse_mode="Markdown")

    elif data == "ab" and is_admin(uid):
        context.user_data["state"] = ST_BROADCAST
        await q.edit_message_text("📢 أرسل الرسالة الجماعية الآن:")

    elif data == "aback" and is_admin(uid):
        total, pp, wp, sp, tb = get_stats()
        tasks_open = is_tasks_open()
        toggle = "🔴 قفل المهام" if tasks_open else "🟢 فتح المهام"
        await q.edit_message_text(
            f"👑 *لوحة الأدمن*\n\n👥 {total} | ⏳{pp} | 💸{wp} | 📸{sp}\n\n{tasks_txt()}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 المستخدمون", callback_data="au"),
                 InlineKeyboardButton("📊 الإحصائيات", callback_data="as_")],
                [InlineKeyboardButton("⏳ طلبات الشراء", callback_data="ap_list"),
                 InlineKeyboardButton("💸 طلبات السحب", callback_data="aw_list")],
                [InlineKeyboardButton("📸 سكرين شوت", callback_data="ass"),
                 InlineKeyboardButton("🎬 الفيديوهات", callback_data="al")],
                [InlineKeyboardButton("👛 تغيير المحفظة", callback_data="awt"),
                 InlineKeyboardButton(toggle, callback_data="at")],
                [InlineKeyboardButton("📢 رسالة جماعية", callback_data="ab")]
            ]), parse_mode="Markdown")

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid): return
    await show_admin(update.message, uid)
    await update.message.reply_text("✅ أنت في وضع الأدمن", reply_markup=admin_kb())

async def makeadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN: return
    if not context.args:
        await update.message.reply_text("❌ الصيغة: /makeadmin user_id"); return
    try:
        target_id = int(context.args[0])
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (target_id,))
        conn.commit(); conn.close()
        target = get_user(target_id)
        name = target[4] if target else str(target_id)
        await update.message.reply_text(f"✅ تم تعيين *{name}* أدمناً مشاركاً", parse_mode="Markdown")
        try:
            await context.bot.send_message(target_id,
                "🎉 *تم تعيينك أدمناً مشاركاً في TEAMO!*\n\nاستخدم /admin للوحة التحكم",
                reply_markup=admin_kb(), parse_mode="Markdown")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def removeadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN: return
    if not context.args:
        await update.message.reply_text("❌ الصيغة: /removeadmin user_id"); return
    try:
        target_id = int(context.args[0])
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET is_admin=0 WHERE user_id=?", (target_id,))
        conn.commit(); conn.close()
        await update.message.reply_text(f"✅ تم إزالة صلاحيات الأدمن من {target_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def activate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2:
        await update.message.reply_text("❌ الصيغة: /activate user_id باقة\nمثال: /activate 123456 A1"); return
    try:
        target_id = int(context.args[0])
        pkg_name = context.args[1].upper()
        if pkg_name not in PACKAGES:
            await update.message.reply_text(f"❌ الباقات المتاحة: {', '.join(PACKAGES.keys())}"); return
        activate_pkg(target_id, pkg_name)
        distribute_commissions(target_id, pkg_name)
        expires = (datetime.now() + timedelta(days=PACKAGE_DAYS)).strftime("%Y-%m-%d")
        target = get_user(target_id)
        name = target[4] if target else str(target_id)
        await update.message.reply_text(
            f"✅ تم تفعيل باقة *{pkg_name}* للمستخدم *{name}*\n📅 تنتهي: {expires}",
            parse_mode="Markdown")
        try:
            await context.bot.send_message(target_id,
                f"🎉 *تم تفعيل باقتك {pkg_name}!*\n\n📅 صالحة حتى: *{expires}*\n\nابدأ بإكمال مهامك 💰",
                reply_markup=main_kb(), parse_mode="Markdown")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("makeadmin", makeadmin_cmd))
    app.add_handler(CommandHandler("removeadmin", removeadmin_cmd))
    app.add_handler(CommandHandler("activate", activate_cmd))
    app.add_handler(CallbackQueryHandler(btn_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, msg_handler))
    print("🤖 TEAMO Bot يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
