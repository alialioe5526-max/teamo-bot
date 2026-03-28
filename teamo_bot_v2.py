import logging
import sqlite3
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

BOT_TOKEN    = "8578221142:AAFe_J9s1EYZwyb1ao5jffZwo5nFy_hpAK0"
ADMIN_ID     = 269900681
WALLET_TRC20 = "TPAgKfYzRdK83Qocc4gXvEVu4jPKfeuer5"

REFERRAL_COMMISSIONS = {
    "A1": [35, 17, 8,  4,  2,  1],
    "A2": [60, 30, 15, 7,  3,  1],
    "A3": [90, 45, 22, 11, 5,  2],
    "B1": [140,70, 35, 17, 8,  4],
    "B2": [220,110,55, 27, 13, 6],
    "B3": [350,175,87, 43, 21, 10],
}

PACKAGES = {
    "A1": {"price": 200,  "tasks": 3, "per_task": 1.11,  "daily": 3.33},
    "A2": {"price": 400,  "tasks": 3, "per_task": 2.22,  "daily": 6.66},
    "A3": {"price": 600,  "tasks": 3, "per_task": 3.33,  "daily": 10.00},
    "B1": {"price": 1200, "tasks": 4, "per_task": 5.00,  "daily": 20.00},
    "B2": {"price": 1800, "tasks": 4, "per_task": 7.50,  "daily": 30.00},
    "B3": {"price": 2500, "tasks": 4, "per_task": 10.41, "daily": 41.66},
}

MIN_WITHDRAW = 10
ST_PHONE = "WAITING_PHONE"
ST_RECEIPT = "WAITING_RECEIPT"
ST_WALLET = "WAITING_WALLET"
ST_WITHDRAW = "WAITING_WITHDRAW"
ST_BROADCAST = "WAITING_BROADCAST"
ST_SETWALLET = "WAITING_SETWALLET"
ST_ADDLINK = "WAITING_ADDLINK"

logging.basicConfig(level=logging.INFO)

def init_db():
    conn = sqlite3.connect("teamo.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, serial_no INTEGER,
        username TEXT, full_name TEXT, phone TEXT,
        balance REAL DEFAULT 0, package TEXT DEFAULT NULL,
        wallet TEXT DEFAULT NULL, ref_code TEXT UNIQUE,
        referred_by INTEGER DEFAULT NULL, joined_at TEXT
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
    c.execute("SELECT COUNT(*) FROM task_links")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO task_links (url) VALUES (?)", ("https://youtube.com/watch?v=dQw4w9WgXcQ",))
    conn.commit()
    conn.close()

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

def next_serial():
    conn = db(); c = conn.cursor()
    c.execute("UPDATE user_counter SET count=count+1 WHERE id=1")
    c.execute("SELECT count FROM user_counter WHERE id=1")
    n = c.fetchone()[0]; conn.commit(); conn.close()
    return n

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
    today = date.today().isoformat(); user = get_user(user_id)
    if not user or not user[6]: return False, "no_package"
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

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 مهامي اليومية", callback_data="daily_tasks"),
         InlineKeyboardButton("💰 محفظتي", callback_data="wallet")],
        [InlineKeyboardButton("📦 الباقات", callback_data="packages"),
         InlineKeyboardButton("👥 إحالاتي", callback_data="referrals")],
        [InlineKeyboardButton("💸 سحب الأرباح", callback_data="withdraw"),
         InlineKeyboardButton("ℹ️ مساعدة", callback_data="help")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المستخدمون", callback_data="adm_users"),
         InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
        [InlineKeyboardButton("⏳ طلبات الشراء", callback_data="adm_payments"),
         InlineKeyboardButton("💸 طلبات السحب", callback_data="adm_withdrawals")],
        [InlineKeyboardButton("🎬 الفيديوهات", callback_data="adm_links"),
         InlineKeyboardButton("👛 تغيير المحفظة", callback_data="adm_wallet")],
        [InlineKeyboardButton("📢 رسالة جماعية", callback_data="adm_broadcast")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = None
    if args:
        ref_uid = get_user_by_refcode(args[0])
        if ref_uid and ref_uid != user.id:
            referred_by = ref_uid
    existing = get_user(user.id)
    if not existing:
        context.user_data["referred_by"] = referred_by
        context.user_data["state"] = ST_PHONE
        await update.message.reply_text(
            f"👋 *أهلاً وسهلاً بك في TEAMO!*\n\n"
            f"🚀 منصة المهمات اليومية والربح الحقيقي\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💎 أكمل مهامك اليومية واربح يومياً\n"
            f"👥 ادعُ أصدقاءك واربح من 6 مستويات\n"
            f"💸 اسحب أرباحك عبر USDT TRC20\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"📱 للتسجيل أرسل *رقم هاتفك* مع رمز الدولة:\n\n"
            f"🇮🇶 `+9647701234567`\n"
            f"🇸🇦 `+966501234567`\n"
            f"🇦🇪 `+971501234567`",
            parse_mode="Markdown"
        )
        return
    db_user = get_user(user.id)
    balance = db_user[5]; package = db_user[6]
    today_row = get_today_tasks(user.id)
    done = today_row[3] if today_row and package else 0
    total = PACKAGES[package]["tasks"] if package else 0
    today_earned = today_row[4] if today_row else 0.0
    await update.message.reply_text(
        f"👋 أهلاً *{user.first_name}!*\n\n"
        f"🆔 رقمك: *#{db_user[1]:04d}*\n"
        f"💎 باقتك: *{package or 'لا توجد'}*\n"
        f"💰 رصيدك: *{balance:.2f}$*\n"
        f"📋 مهام اليوم: *{done}/{total}*\n"
        f"💵 ربح اليوم: *{today_earned:.2f}$*\n\n"
        f"اختر من القائمة 👇",
        reply_markup=main_keyboard(), parse_mode="Markdown"
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")
    text = update.message.text.strip() if update.message.text else ""

    if state == ST_PHONE:
        if not text.startswith("+") or len(text) < 10:
            await update.message.reply_text("❌ رقم غير صحيح!\nأرسل مثلاً: `+9647701234567`", parse_mode="Markdown")
            return
        referred_by = context.user_data.get("referred_by")
        u = update.effective_user
        register_user(user_id, u.username or "", u.full_name, text, referred_by)
        context.user_data.clear()
        db_user = get_user(user_id)
        await update.message.reply_text(
            f"✅ *تم التسجيل بنجاح!*\n\n🆔 رقمك: *#{db_user[1]:04d}*\n📱 هاتفك: `{text}`\n\nاختر باقة لتبدأ الربح 💰",
            reply_markup=main_keyboard(), parse_mode="Markdown"
        )

    elif state == ST_RECEIPT:
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
            if update.message.photo: await context.bot.send_photo(ADMIN_ID, file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
            else: await context.bot.send_document(ADMIN_ID, file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
        except: pass
        context.user_data.clear()
        await update.message.reply_text("✅ *تم استلام الوصل!*\n\n⏳ سيتم التفعيل خلال 24 ساعة",
            reply_markup=main_keyboard(), parse_mode="Markdown")

    elif state == ST_WALLET:
        if len(text) < 30:
            await update.message.reply_text("❌ عنوان غير صحيح."); return
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET wallet=? WHERE user_id=?", (text, user_id))
        conn.commit(); conn.close()
        context.user_data.clear()
        await update.message.reply_text(f"✅ *تم حفظ محفظتك!*\n\n`{text}`",
            reply_markup=main_keyboard(), parse_mode="Markdown")

    elif state == ST_WITHDRAW:
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
        await update.message.reply_text(f"✅ *تم إرسال طلب السحب!*\n\nالمبلغ: *{amount:.2f}$*\n⏳ المعالجة خلال 24-48 ساعة",
            reply_markup=main_keyboard(), parse_mode="Markdown")

    elif state == ST_BROADCAST and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id FROM users"); users = c.fetchall(); conn.close()
        sent, failed = 0, 0
        for (uid,) in users:
            try: await context.bot.send_message(uid, text); sent += 1
            except: failed += 1
        context.user_data.clear()
        await update.message.reply_text(f"✅ أُرسلت لـ {sent} | ❌ فشل مع {failed}", reply_markup=admin_keyboard())

    elif state == ST_SETWALLET and user_id == ADMIN_ID:
        if len(text) < 20:
            await update.message.reply_text("❌ عنوان غير صحيح."); return
        set_setting("wallet", text); context.user_data.clear()
        await update.message.reply_text(f"✅ تم تغيير محفظة الاستلام:\n`{text}`",
            reply_markup=admin_keyboard(), parse_mode="Markdown")

    elif state == ST_ADDLINK and user_id == ADMIN_ID:
        if not text.startswith("http"):
            await update.message.reply_text("❌ أرسل رابطاً صحيحاً."); return
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO task_links (url) VALUES (?)", (text,))
        conn.commit(); conn.close(); context.user_data.clear()
        await update.message.reply_text(f"✅ تمت إضافة الرابط:\n{text}", reply_markup=admin_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user_id = query.from_user.id; data = query.data

    if data == "daily_tasks":
        user = get_user(user_id)
        if not user or not user[6]:
            await query.edit_message_text("❌ *ليس لديك باقة مفعّلة*",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📦 اشترِ باقة", callback_data="packages")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
                ]), parse_mode="Markdown"); return
        pkg = PACKAGES[user[6]]; today_row = get_today_tasks(user_id)
        done = today_row[3] if today_row else 0; total = pkg["tasks"]
        keyboard = []
        text = (f"📋 *مهامك اليومية*\n\nباقتك: *{user[6]}*\nالتقدم: *{done}/{total}* ✦\n"
                f"ربح المهمة: *{pkg['per_task']:.2f}$*\nإجمالي اليوم: *{pkg['daily']:.2f}$*\n\n")
        if done >= total: text += "🎉 أنجزت جميع مهامك! عد غداً."
        else:
            text += "اضغط لإكمال مهمتك 👇"
            keyboard.append([InlineKeyboardButton(f"▶️ ابدأ المهمة {done+1}", callback_data="start_task")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "start_task":
        link = get_task_link()
        await query.edit_message_text(
            "📌 *مهمتك اليومية*\n\n1️⃣ شاهد الفيديو 30 ثانية\n2️⃣ اشترك بالقناة\n3️⃣ أعجب بالفيديو\n\nثم اضغط *تأكيد* 👇",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 افتح الفيديو", url=link)],
                [InlineKeyboardButton("✅ تأكيد إكمال المهمة", callback_data="confirm_task")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="daily_tasks")]
            ]), parse_mode="Markdown")

    elif data == "confirm_task":
        success, result = complete_task(user_id)
        if success:
            done, total, per_task, earned = result
            keyboard = []
            if done < total: keyboard.append([InlineKeyboardButton("📋 المهمة التالية", callback_data="daily_tasks")])
            keyboard += [[InlineKeyboardButton("💰 رصيدي", callback_data="wallet")],
                         [InlineKeyboardButton("🏠 الرئيسية", callback_data="back_main")]]
            await query.edit_message_text(
                f"✅ *مبروك!*\n\n💰 ربحت: *{per_task:.2f}$*\n📋 *{done}/{total}*\n💵 ربح اليوم: *{earned:.2f}$*\n\n"
                f"{'🎉 أنجزت جميع مهامك!' if done >= total else '💪 استمر!'}",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif result == "max_reached":
            await query.edit_message_text("⚠️ أكملت جميع مهماتك اليوم! عد غداً 🌟",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))
        else:
            await query.edit_message_text("❌ ليس لديك باقة!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 الباقات", callback_data="packages")]]))

    elif data == "wallet":
        user = get_user(user_id); balance = user[5]; wallet = user[7]
        conn = db(); c = conn.cursor()
        c.execute("SELECT SUM(amount) FROM referral_earnings WHERE user_id=?", (user_id,))
        ref_earned = c.fetchone()[0] or 0; conn.close()
        keyboard = [[InlineKeyboardButton("✏️ تغيير المحفظة" if wallet else "➕ أضف محفظة TRC20", callback_data="add_wallet")],
                    [InlineKeyboardButton("💸 سحب الأرباح", callback_data="withdraw")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
        await query.edit_message_text(
            f"💰 *محفظتي*\n\n💎 الرصيد: *{balance:.2f}$*\n👥 أرباح الإحالات: *{ref_earned:.2f}$*\n\n"
            f"👛 محفظة TRC20:\n`{wallet or 'لم تُضف بعد'}`",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "add_wallet":
        context.user_data["state"] = ST_WALLET
        await query.edit_message_text("👛 *تغيير محفظة TRC20*\n\nأرسل عنوان محفظتك:", parse_mode="Markdown")

    elif data == "packages":
        keyboard = []
        for name, pkg in PACKAGES.items():
            keyboard.append([InlineKeyboardButton(
                f"{'⭐ ' if name=='B1' else ''}{name} — {pkg['price']}$ ({pkg['daily']:.2f}$/يوم)",
                callback_data=f"buy_{name}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
        await query.edit_message_text("📦 *اختر باقتك*\n", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("buy_"):
        pkg_name = data[4:]; pkg = PACKAGES[pkg_name]
        commissions = REFERRAL_COMMISSIONS[pkg_name]; wallet = get_setting("wallet")
        await query.edit_message_text(
            f"📦 *باقة {pkg_name}*\n\n💰 السعر: *{pkg['price']}$*\n📋 *{pkg['tasks']} مهام/يوم*\n"
            f"💵 ربح المهمة: *{pkg['per_task']:.2f}$*\n📈 اليومي: *{pkg['daily']:.2f}$*\n\n"
            f"👥 *عمولات الإحالة:*\nL1:{commissions[0]}$ L2:{commissions[1]}$ L3:{commissions[2]}$\n"
            f"L4:{commissions[3]}$ L5:{commissions[4]}$ L6:{commissions[5]}$\n\n"
            f"أرسل *{pkg['price']} USDT TRC20* على:\n`{wallet}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 أرسل وصل الدفع", callback_data=f"send_receipt_{pkg_name}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="packages")]
            ]), parse_mode="Markdown")

    elif data.startswith("send_receipt_"):
        pkg_name = data[13:]
        context.user_data["buying_package"] = pkg_name
        context.user_data["state"] = ST_RECEIPT
        await query.edit_message_text(f"📤 *وصل الدفع — باقة {pkg_name}*\n\nأرسل صورة الوصل الآن 👇", parse_mode="Markdown")

    elif data == "referrals":
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
        text = (f"👥 *إحالاتي*\n\n🔗 رابطك:\n`{ref_link}`\n🎟 كودك: `{ref_code}`\n\n"
                f"👤 مباشر: *{direct}* | 💰 الإجمالي: *{total_earned:.2f}$*\n\n📊 *التفصيل:*\n")
        for lvl in range(1, 7):
            count, earned = levels.get(lvl, (0, 0))
            text += f"L{lvl}: {count} شخص — {earned:.2f}$\n"
        await query.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]),
            parse_mode="Markdown")

    elif data == "withdraw":
        user = get_user(user_id)
        if not user or not user[7]:
            await query.edit_message_text("❌ أضف محفظتك أولاً!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ أضف محفظة", callback_data="add_wallet")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]])); return
        context.user_data["state"] = ST_WITHDRAW
        await query.edit_message_text(
            f"💸 *سحب الأرباح*\n\nالرصيد: *{user[5]:.2f}$*\nالحد الأدنى: *{MIN_WITHDRAW}$*\n"
            f"المحفظة: `{user[7]}`\n\nأرسل المبلغ:", parse_mode="Markdown")

    elif data == "help":
        await query.edit_message_text(
            "ℹ️ *كيفية الاستخدام*\n\n1️⃣ اشترِ باقة وأرسل وصل الدفع\n2️⃣ انتظر التفعيل (24 ساعة)\n"
            "3️⃣ أكمل مهامك اليومية\n4️⃣ ادعُ أصدقاءك واربح من 6 مستويات\n5️⃣ اسحب عبر USDT TRC20\n\n"
            f"💸 الحد الأدنى: {MIN_WITHDRAW}$",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]),
            parse_mode="Markdown")

    elif data == "back_main":
        user = get_user(user_id); balance = user[5]; pkg = user[6]
        today_row = get_today_tasks(user_id)
        done = today_row[3] if today_row else 0
        total = PACKAGES[pkg]["tasks"] if pkg else 0
        await query.edit_message_text(
            f"🏠 *القائمة الرئيسية*\n\n🆔 رقمك: *#{user[1]:04d}*\n💎 باقتك: *{pkg or 'لا توجد'}*\n"
            f"💰 رصيدك: *{balance:.2f}$*\n📋 مهام اليوم: *{done}/{total}*\n\nاختر من القائمة 👇",
            reply_markup=main_keyboard(), parse_mode="Markdown")

    # ══ أدمن ══
    elif data == "adm_stats" and user_id == ADMIN_ID:
        total, pp, wp, tb = get_stats(); wallet = get_setting("wallet")
        await query.edit_message_text(
            f"📊 *الإحصائيات*\n\n👥 المستخدمون: *{total}*\n⏳ شراء معلق: *{pp}*\n"
            f"💸 سحب معلق: *{wp}*\n💰 إجمالي الأرصدة: *{tb:.2f}$*\n\n👛 محفظة الاستلام:\n`{wallet}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]),
            parse_mode="Markdown")

    elif data == "adm_users" and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("SELECT serial_no,full_name,phone,package,balance,user_id FROM users ORDER BY serial_no")
        users = c.fetchall(); conn.close()
        text = f"👥 *المستخدمون ({len(users)})*\n\n"
        for u in users[:25]:
            serial, name, phone, pkg, balance, uid = u
            text += f"*#{serial:04d}* | {name}\n📱{phone or '—'} | 📦{pkg or '—'} | 💰{balance:.2f}$\n\n"
        if len(users) > 25: text += f"... و {len(users)-25} مستخدم آخر"
        await query.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]),
            parse_mode="Markdown")

    elif data == "adm_payments" and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("""SELECT p.id,u.serial_no,u.full_name,u.phone,p.package,p.price,p.user_id
                     FROM packages_history p JOIN users u ON p.user_id=u.user_id
                     WHERE p.status='pending' ORDER BY p.id""")
        payments = c.fetchall(); conn.close()
        if not payments:
            await query.edit_message_text("✅ لا توجد طلبات شراء معلقة",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]])); return
        text = f"⏳ *طلبات الشراء ({len(payments)})*\n\n"; keyboard = []
        for p in payments:
            pid, serial, name, phone, pkg, price, uid = p
            text += f"*#{pid}* | {name} #{serial:04d}\n📱{phone} | 📦{pkg} — {price}$\n\n"
            keyboard.append([
                InlineKeyboardButton(f"✅ قبول #{pid}", callback_data=f"adm_approve_{pid}"),
                InlineKeyboardButton(f"❌ رفض #{pid}", callback_data=f"adm_reject_{pid}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "adm_withdrawals" and user_id == ADMIN_ID:
        conn = db(); c = conn.cursor()
        c.execute("""SELECT w.id,u.serial_no,u.full_name,u.phone,w.amount,w.wallet,w.user_id
                     FROM withdrawals w JOIN users u ON w.user_id=u.user_id
                     WHERE w.status='pending' ORDER BY w.id""")
        withdrawals = c.fetchall(); conn.close()
        if not withdrawals:
            await query.edit_message_text("✅ لا توجد طلبات سحب معلقة",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]])); return
        text = f"💸 *طلبات السحب ({len(withdrawals)})*\n\n"; keyboard = []
        for w in withdrawals:
            wid, serial, name, phone, amount, wallet, uid = w
            text += f"*#{wid}* | {name} #{serial:04d}\n📱{phone}\n💰 *{amount:.2f}$*\n👛 `{wallet}`\n\n"
            keyboard.append([
                InlineKeyboardButton(f"✅ قبول #{wid}", callback_data=f"adm_wapprove_{wid}"),
                InlineKeyboardButton(f"❌ رفض #{wid}", callback_data=f"adm_wreject_{wid}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "adm_wallet" and user_id == ADMIN_ID:
        context.user_data["state"] = ST_SETWALLET; wallet = get_setting("wallet")
        await query.edit_message_text(f"👛 *تغيير محفظة الاستلام*\n\nالحالية: `{wallet}`\n\nأرسل العنوان الجديد:", parse_mode="Markdown")

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
        await query.edit_message_text(
            f"👑 *لوحة الأدمن*\n\n👥 المستخدمون: *{total}*\n⏳ طلبات شراء: *{pp}*\n💸 طلبات سحب: *{wp}*",
            reply_markup=admin_keyboard(), parse_mode="Markdown")

    elif data.startswith("adm_approve_") and user_id == ADMIN_ID:
        request_id = int(data[12:])
        conn = db(); c = conn.cursor()
        c.execute("SELECT user_id,package FROM packages_history WHERE id=? AND status='pending'", (request_id,))
        row = c.fetchone()
        if not row: await query.answer("❌ مُعالَج مسبقاً"); conn.close(); return
        uid, pkg_name = row
        c.execute("UPDATE packages_history SET status='approved' WHERE id=?", (request_id,))
        c.execute("UPDATE users SET package=? WHERE user_id=?", (pkg_name, uid))
        conn.commit(); conn.close()
        distribute_referral_commissions(uid, pkg_name)
        try:
            await context.bot.send_message(uid,
                f"🎉 *تم تفعيل باقتك {pkg_name}!*\n\nابدأ بإكمال مهامك اليومية الآن 💰",
                reply_markup=main_keyboard(), parse_mode="Markdown")
        except: pass
        await query.edit_message_text(f"✅ تم تفعيل {pkg_name} للمستخدم #{request_id}", reply_markup=admin_keyboard())

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
        await query.edit_message_text(f"❌ تم رفض الطلب #{request_id}", reply_markup=admin_keyboard())

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
        await query.edit_message_text(f"✅ تم قبول السحب #{wid} — {amount}$", reply_markup=admin_keyboard())

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
        await query.edit_message_text(f"❌ تم رفض السحب #{wid} وإعادة الرصيد", reply_markup=admin_keyboard())

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total, pp, wp, tb = get_stats()
    await update.message.reply_text(
        f"👑 *لوحة الأدمن*\n\n👥 المستخدمون: *{total}*\n⏳ طلبات شراء: *{pp}*\n💸 طلبات سحب: *{wp}*\n💰 الأرصدة: *{tb:.2f}$*",
        reply_markup=admin_keyboard(), parse_mode="Markdown")

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
