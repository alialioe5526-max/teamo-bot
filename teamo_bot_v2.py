import logging
import sqlite3
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ===================== إعدادات =====================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"   # ← توكن البوت
ADMIN_ID  = 123456789               # ← ID الأدمن
WALLET_TRC20 = "TXyz1234...YOUR_WALLET"  # ← محفظة USDT TRC20 للاستلام

# مستويات الإحالة والعمولات (بالدولار)
REFERRAL_COMMISSIONS = {
    "A1": [35, 17, 8,  4,  2,  1],
    "A2": [60, 30, 15, 7,  3,  1],
    "A3": [90, 45, 22, 11, 5,  2],
    "B1": [140,70, 35, 17, 8,  4],
    "B2": [220,110,55, 27, 13, 6],
    "B3": [350,175,87, 43, 21, 10],
}

# الباقات
PACKAGES = {
    "A1": {"price": 200,  "tasks": 3, "per_task": 1.11,  "daily": 3.33},
    "A2": {"price": 400,  "tasks": 3, "per_task": 2.22,  "daily": 6.66},
    "A3": {"price": 600,  "tasks": 3, "per_task": 3.33,  "daily": 10.00},
    "B1": {"price": 1200, "tasks": 4, "per_task": 5.00,  "daily": 20.00},
    "B2": {"price": 1800, "tasks": 4, "per_task": 7.50,  "daily": 30.00},
    "B3": {"price": 2500, "tasks": 4, "per_task": 10.41, "daily": 41.66},
}

MIN_WITHDRAW = 10  # الحد الأدنى للسحب

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# حالات المحادثة
WAITING_RECEIPT   = 1
WAITING_WALLET    = 2
WAITING_WITHDRAW  = 3
WAITING_TASK_LINK = 4

# ===================== قاعدة البيانات =====================
def init_db():
    conn = sqlite3.connect("teamo.db")
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id    INTEGER PRIMARY KEY,
        username   TEXT,
        full_name  TEXT,
        phone      TEXT,
        password   TEXT,
        balance    REAL DEFAULT 0,
        package    TEXT DEFAULT NULL,
        wallet     TEXT DEFAULT NULL,
        ref_code   TEXT UNIQUE,
        referred_by INTEGER DEFAULT NULL,
        joined_at  TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS packages_history (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        package    TEXT,
        price      REAL,
        status     TEXT DEFAULT 'pending',
        receipt    TEXT,
        created_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS daily_tasks (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        task_date  TEXT,
        tasks_done INTEGER DEFAULT 0,
        earned     REAL DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS task_links (
        id    INTEGER PRIMARY KEY AUTOINCREMENT,
        url   TEXT,
        active INTEGER DEFAULT 1
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        amount     REAL,
        wallet     TEXT,
        status     TEXT DEFAULT 'pending',
        created_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS referral_earnings (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        from_user  INTEGER,
        level      INTEGER,
        amount     REAL,
        package    TEXT,
        created_at TEXT
    )""")

    # إضافة روابط مهام افتراضية
    c.execute("SELECT COUNT(*) FROM task_links")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO task_links (url) VALUES (?)", ("https://youtube.com/watch?v=dQw4w9WgXcQ",))

    conn.commit()
    conn.close()

def db():
    return sqlite3.connect("teamo.db")

def get_user(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    u = c.fetchone()
    conn.close()
    return u

def gen_ref_code(user_id):
    return f"TMO{user_id:06d}"

def register_user(user_id, username, full_name, referred_by=None):
    conn = db()
    c = conn.cursor()
    ref_code = gen_ref_code(user_id)
    c.execute("""INSERT OR IGNORE INTO users
        (user_id, username, full_name, ref_code, referred_by, joined_at)
        VALUES (?,?,?,?,?,?)""",
        (user_id, username, full_name, ref_code, referred_by, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user_by_refcode(ref_code):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE ref_code=?", (ref_code,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

def get_ancestors(user_id, levels=6):
    """الحصول على المحيلين من المستوى 1 إلى 6"""
    ancestors = []
    conn = db()
    c = conn.cursor()
    current = user_id
    for _ in range(levels):
        c.execute("SELECT referred_by FROM users WHERE user_id=?", (current,))
        row = c.fetchone()
        if not row or not row[0]:
            break
        ancestors.append(row[0])
        current = row[0]
    conn.close()
    return ancestors

def distribute_referral_commissions(new_user_id, package_name):
    """توزيع عمولات الإحالة على 6 مستويات"""
    commissions = REFERRAL_COMMISSIONS.get(package_name, [])
    ancestors = get_ancestors(new_user_id)
    conn = db()
    c = conn.cursor()
    for level, ancestor_id in enumerate(ancestors):
        if level >= len(commissions):
            break
        amount = commissions[level]
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, ancestor_id))
        c.execute("""INSERT INTO referral_earnings (user_id, from_user, level, amount, package, created_at)
                     VALUES (?,?,?,?,?,?)""",
                  (ancestor_id, new_user_id, level+1, amount, package_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_today_tasks(user_id):
    today = date.today().isoformat()
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM daily_tasks WHERE user_id=? AND task_date=?", (user_id, today))
    row = c.fetchone()
    conn.close()
    return row

def get_task_link():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT url FROM task_links WHERE active=1 ORDER BY RANDOM() LIMIT 1")
    r = c.fetchone()
    conn.close()
    return r[0] if r else "https://youtube.com"

def complete_task(user_id):
    """إكمال مهمة واحدة"""
    today = date.today().isoformat()
    user = get_user(user_id)
    if not user or not user[6]:  # لا باقة
        return False, "no_package"

    package = PACKAGES[user[6]]
    max_tasks = package["tasks"]
    per_task  = package["per_task"]

    conn = db()
    c = conn.cursor()
    c.execute("SELECT tasks_done, earned FROM daily_tasks WHERE user_id=? AND task_date=?", (user_id, today))
    row = c.fetchone()

    if row:
        done, earned = row
        if done >= max_tasks:
            conn.close()
            return False, "max_reached"
        done += 1
        earned += per_task
        c.execute("UPDATE daily_tasks SET tasks_done=?, earned=? WHERE user_id=? AND task_date=?",
                  (done, earned, user_id, today))
    else:
        done, earned = 1, per_task
        c.execute("INSERT INTO daily_tasks (user_id, task_date, tasks_done, earned) VALUES (?,?,?,?)",
                  (user_id, today, 1, per_task))

    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (per_task, user_id))
    conn.commit()
    conn.close()
    return True, (done, max_tasks, per_task, earned)

def get_referral_tree(user_id):
    conn = db()
    c = conn.cursor()

    def get_level(parent_id, depth):
        if depth > 6:
            return []
        c.execute("SELECT user_id, full_name, package FROM users WHERE referred_by=?", (parent_id,))
        children = c.fetchall()
        result = []
        for child in children:
            result.append((child[0], child[1], child[2], depth))
            result.extend(get_level(child[0], depth + 1))
        return result

    tree = get_level(user_id, 1)
    conn.close()
    return tree

def get_stats():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM packages_history WHERE status='pending'")
    pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    withdraw_pending = c.fetchone()[0]
    conn.close()
    return total, pending, withdraw_pending

# ===================== لوحة رئيسية =====================
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 مهامي اليومية", callback_data="daily_tasks"),
         InlineKeyboardButton("💰 محفظتي", callback_data="wallet")],
        [InlineKeyboardButton("📦 الباقات", callback_data="packages"),
         InlineKeyboardButton("👥 إحالاتي", callback_data="referrals")],
        [InlineKeyboardButton("💸 سحب الأرباح", callback_data="withdraw"),
         InlineKeyboardButton("ℹ️ مساعدة", callback_data="help")]
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
        register_user(user.id, user.username or "", user.full_name, referred_by)

    db_user = get_user(user.id)
    package_name = db_user[6] if db_user else None
    balance = db_user[5] if db_user else 0

    today_row = get_today_tasks(user.id)
    if today_row and package_name:
        pkg = PACKAGES[package_name]
        done = today_row[3]
        total = pkg["tasks"]
        today_earned = today_row[4]
    else:
        done, total, today_earned = 0, 0, 0.0

    text = (
        f"👋 أهلاً {user.first_name}!\n\n"
        f"🤖 **TEAMO** — منصة المهمات اليومية\n\n"
        f"💎 باقتك: **{package_name or 'لا توجد باقة'}**\n"
        f"💰 رصيدك: **{balance:.2f}$**\n"
        f"📋 مهام اليوم: **{done}/{total}**\n"
        f"💵 ربح اليوم: **{today_earned:.2f}$**\n\n"
        f"اختر من القائمة 👇"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard(), parse_mode="Markdown")

# ===================== المهام اليومية =====================
async def show_daily_tasks(query, user_id):
    user = get_user(user_id)
    if not user or not user[6]:
        await query.edit_message_text(
            "❌ **ليس لديك باقة مفعّلة**\n\nاشترِ باقة لتبدأ بكسب المال يومياً!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 اشترِ باقة", callback_data="packages")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
            ]),
            parse_mode="Markdown"
        )
        return

    pkg = PACKAGES[user[6]]
    today_row = get_today_tasks(user_id)
    done = today_row[3] if today_row else 0
    total = pkg["tasks"]

    text = (
        f"📋 **مهامك اليومية**\n\n"
        f"باقتك: **{user[6]}**\n"
        f"التقدم: **{done}/{total}** ✦\n"
        f"ربح كل مهمة: **{pkg['per_task']:.2f}$**\n"
        f"إجمالي اليوم: **{pkg['daily']:.2f}$**\n\n"
    )

    keyboard = []
    if done >= total:
        text += "🎉 أنجزت جميع مهامك! عد غداً."
    else:
        text += "اضغط لإكمال مهمتك التالية 👇"
        keyboard.append([InlineKeyboardButton(f"▶️ ابدأ المهمة {done+1}", callback_data="start_task")])

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def start_task(query, user_id):
    link = get_task_link()
    keyboard = [
        [InlineKeyboardButton("🎬 شاهد الفيديو", url=link)],
        [InlineKeyboardButton("🔔 اشترك بالقناة", url=link)],
        [InlineKeyboardButton("❤️ أعجب بالفيديو", url=link)],
        [InlineKeyboardButton("✅ تأكيد إكمال المهمة", callback_data="confirm_task")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="daily_tasks")]
    ]
    await query.edit_message_text(
        "📌 **مهمتك اليومية**\n\n"
        "أكمل الخطوات الثلاث:\n\n"
        "1️⃣ شاهد الفيديو 30 ثانية على الأقل\n"
        "2️⃣ اشترك بالقناة\n"
        "3️⃣ أعجب بالفيديو\n\n"
        "ثم اضغط **تأكيد إكمال المهمة** 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def confirm_task(query, user_id):
    success, result = complete_task(user_id)
    if success:
        done, total, per_task, earned = result
        await query.edit_message_text(
            f"✅ **مبروك! أكملت المهمة**\n\n"
            f"💰 ربحت: **{per_task:.2f}$**\n"
            f"📋 التقدم: **{done}/{total}**\n"
            f"💵 ربح اليوم: **{earned:.2f}$**\n\n"
            f"{'🎉 أنجزت جميع مهامك اليوم!' if done >= total else 'استمر وأكمل باقي المهمات!'}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 المهمة التالية", callback_data="daily_tasks")] if done < total else [],
                [InlineKeyboardButton("💰 رصيدي", callback_data="wallet")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="back_main")]
            ]),
            parse_mode="Markdown"
        )
    elif result == "max_reached":
        await query.edit_message_text(
            "⚠️ أكملت جميع مهماتك لهذا اليوم!\nعد غداً لمهام جديدة 🌟",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]])
        )
    else:
        await query.edit_message_text(
            "❌ ليس لديك باقة مفعّلة!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 الباقات", callback_data="packages")]])
        )

# ===================== الباقات =====================
async def show_packages(query, user_id):
    text = "📦 **اختر باقتك**\n\nمهام يومية وربح ثابت\n\n"
    keyboard = []
    for name, pkg in PACKAGES.items():
        keyboard.append([InlineKeyboardButton(
            f"{'⭐ ' if name == 'B1' else ''}{name} — {pkg['price']}$ ({pkg['daily']:.2f}$/يوم)",
            callback_data=f"buy_{name}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_package_detail(query, user_id, pkg_name):
    pkg = PACKAGES[pkg_name]
    commissions = REFERRAL_COMMISSIONS[pkg_name]
    text = (
        f"📦 **باقة {pkg_name}**\n\n"
        f"💰 السعر: **{pkg['price']}$**\n"
        f"📋 المهام اليومية: **{pkg['tasks']} مهام**\n"
        f"💵 ربح المهمة: **{pkg['per_task']:.2f}$**\n"
        f"📈 الربح اليومي: **{pkg['daily']:.2f}$**\n\n"
        f"👥 **عمولات الإحالة:**\n"
        f"L1: {commissions[0]}$ | L2: {commissions[1]}$ | L3: {commissions[2]}$\n"
        f"L4: {commissions[3]}$ | L5: {commissions[4]}$ | L6: {commissions[5]}$\n\n"
        f"للشراء أرسل **{pkg['price']} USDT** على المحفظة التالية:\n\n"
        f"`{WALLET_TRC20}`\n\n"
        f"⚠️ شبكة TRC20 فقط!"
    )
    keyboard = [
        [InlineKeyboardButton("📤 أرسل وصل الدفع", callback_data=f"send_receipt_{pkg_name}")],
        [InlineKeyboardButton("🔙 رجوع للباقات", callback_data="packages")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def request_receipt(query, user_id, pkg_name, context):
    context.user_data["buying_package"] = pkg_name
    await query.edit_message_text(
        f"📤 **إرسال وصل الدفع — باقة {pkg_name}**\n\n"
        f"أرسل صورة وصل التحويل الآن 👇\n\n"
        f"سيتم مراجعته وتفعيل باقتك خلال 24 ساعة ⏳",
        parse_mode="Markdown"
    )
    return WAITING_RECEIPT

async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pkg_name = context.user_data.get("buying_package")
    if not pkg_name:
        return ConversationHandler.END

    # حفظ الطلب في قاعدة البيانات
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id

    conn = db()
    c = conn.cursor()
    c.execute("""INSERT INTO packages_history (user_id, package, price, receipt, created_at)
                 VALUES (?,?,?,?,?)""",
              (user_id, pkg_name, PACKAGES[pkg_name]["price"], file_id, datetime.now().isoformat()))
    request_id = c.lastrowid
    conn.commit()
    conn.close()

    # إشعار الأدمن
    try:
        user = get_user(user_id)
        name = user[2] if user else str(user_id)
        if update.message.photo:
            await context.bot.send_photo(
                ADMIN_ID,
                file_id,
                caption=(
                    f"🧾 **طلب شراء جديد**\n\n"
                    f"المستخدم: {name} (ID: {user_id})\n"
                    f"الباقة: {pkg_name} — {PACKAGES[pkg_name]['price']}$\n"
                    f"رقم الطلب: #{request_id}\n\n"
                    f"للقبول: `/approve {request_id}`\n"
                    f"للرفض: `/reject {request_id}`"
                ),
                parse_mode="Markdown"
            )
        elif update.message.document:
            await context.bot.send_document(
                ADMIN_ID,
                file_id,
                caption=(
                    f"🧾 طلب شراء #{request_id}\n{name} — {pkg_name}\n"
                    f"`/approve {request_id}` | `/reject {request_id}`"
                ),
                parse_mode="Markdown"
            )
    except:
        pass

    await update.message.reply_text(
        "✅ **تم استلام الوصل!**\n\n"
        "⏳ سيتم مراجعته وتفعيل باقتك خلال 24 ساعة\n"
        "📩 ستصلك إشعار فور التفعيل",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

# ===================== المحفظة =====================
async def show_wallet(query, user_id):
    user = get_user(user_id)
    balance = user[5] if user else 0
    wallet  = user[7] if user else None
    ref_code = user[8] if user else ""

    # أرباح الإحالات
    conn = db()
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM referral_earnings WHERE user_id=?", (user_id,))
    ref_earned = c.fetchone()[0] or 0
    conn.close()

    text = (
        f"💰 **محفظتي**\n\n"
        f"💎 الرصيد الكلي: **{balance:.2f}$**\n"
        f"👥 أرباح الإحالات: **{ref_earned:.2f}$**\n\n"
        f"👛 محفظة TRC20:\n"
        f"`{wallet or 'لم تُضف بعد'}`\n"
    )
    keyboard = []
    if not wallet:
        keyboard.append([InlineKeyboardButton("➕ أضف محفظتك", callback_data="add_wallet")])
    keyboard.append([InlineKeyboardButton("💸 سحب الأرباح", callback_data="withdraw")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def request_wallet(query, context):
    await query.edit_message_text(
        "👛 **إضافة محفظة TRC20**\n\n"
        "أرسل عنوان محفظتك USDT TRC20 الآن:\n\n"
        "⚠️ تأكد من صحة العنوان — لا يمكن استرداد مبالغ أُرسلت لعنوان خاطئ"
    )
    return WAITING_WALLET

async def save_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = update.message.text.strip()

    if len(wallet) < 30:
        await update.message.reply_text("❌ عنوان غير صحيح. أعد المحاولة:")
        return WAITING_WALLET

    conn = db()
    c = conn.cursor()
    c.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ **تم حفظ محفظتك بنجاح!**\n\n"
        f"العنوان: `{wallet}`",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ===================== السحب =====================
async def show_withdraw(query, user_id):
    user = get_user(user_id)
    balance = user[5] if user else 0
    wallet  = user[7] if user else None

    if not wallet:
        await query.edit_message_text(
            "❌ **أضف محفظتك أولاً لتتمكن من السحب**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ أضف محفظة", callback_data="add_wallet")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
            ]),
            parse_mode="Markdown"
        )
        return

    await query.edit_message_text(
        f"💸 **سحب الأرباح**\n\n"
        f"الرصيد المتاح: **{balance:.2f}$**\n"
        f"الحد الأدنى: **{MIN_WITHDRAW}$**\n\n"
        f"المحفظة: `{wallet}`\n\n"
        f"أرسل المبلغ الذي تريد سحبه:"
    )
    return WAITING_WITHDRAW

async def process_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    balance = user[5] if user else 0
    wallet  = user[7] if user else None

    try:
        amount = float(update.message.text.strip())
    except:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً.")
        return WAITING_WITHDRAW

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ الحد الأدنى للسحب {MIN_WITHDRAW}$")
        return WAITING_WITHDRAW

    if amount > balance:
        await update.message.reply_text(f"❌ رصيدك غير كافٍ ({balance:.2f}$)")
        return WAITING_WITHDRAW

    conn = db()
    c = conn.cursor()
    c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id))
    c.execute("""INSERT INTO withdrawals (user_id, amount, wallet, created_at)
                 VALUES (?,?,?,?)""",
              (user_id, amount, wallet, datetime.now().isoformat()))
    request_id = c.lastrowid
    conn.commit()
    conn.close()

    # إشعار الأدمن
    try:
        u = get_user(user_id)
        await context.bot.send_message(
            ADMIN_ID,
            f"💸 **طلب سحب جديد #{request_id}**\n\n"
            f"المستخدم: {u[2]} (ID: {user_id})\n"
            f"المبلغ: **{amount:.2f}$**\n"
            f"المحفظة: `{wallet}`\n\n"
            f"للقبول: `/withdraw_approve {request_id}`\n"
            f"للرفض: `/withdraw_reject {request_id}`",
            parse_mode="Markdown"
        )
    except:
        pass

    await update.message.reply_text(
        f"✅ **تم إرسال طلب السحب!**\n\n"
        f"المبلغ: **{amount:.2f}$**\n"
        f"سيتم المعالجة خلال 24-48 ساعة ⏳",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ===================== الإحالات =====================
async def show_referrals(query, user_id, context):
    bot_username = (await context.bot.get_me()).username
    user = get_user(user_id)
    ref_code = user[8] if user else ""
    ref_link = f"https://t.me/{bot_username}?start={ref_code}"

    tree = get_referral_tree(user_id)

    # إحصائيات كل مستوى
    level_counts = {}
    level_earnings = {}
    for uid, name, pkg, level in tree:
        level_counts[level] = level_counts.get(level, 0) + 1

    conn = db()
    c = conn.cursor()
    c.execute("SELECT level, SUM(amount) FROM referral_earnings WHERE user_id=? GROUP BY level", (user_id,))
    for row in c.fetchall():
        level_earnings[row[0]] = row[1] or 0
    total_ref_earned = sum(level_earnings.values())
    conn.close()

    text = (
        f"👥 **إحالاتي**\n\n"
        f"🔗 رابط الدعوة:\n`{ref_link}`\n\n"
        f"🎟 كود الإحالة: `{ref_code}`\n\n"
        f"💰 أرباح الإحالات: **{total_ref_earned:.2f}$**\n"
        f"👤 إجمالي شبكتك: **{len(tree)} شخص**\n\n"
        f"📊 **تفصيل المستويات:**\n"
    )
    for lvl in range(1, 7):
        count = level_counts.get(lvl, 0)
        earned = level_earnings.get(lvl, 0)
        text += f"L{lvl}: {count} شخص — {earned:.2f}$\n"

    keyboard = [
        [InlineKeyboardButton("📋 نسخ الرابط", callback_data="copy_ref")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ===================== المساعدة =====================
async def show_help(query):
    text = (
        "ℹ️ **كيفية الاستخدام**\n\n"
        "1️⃣ اشترِ باقة من قائمة الباقات\n"
        "2️⃣ أرسل وصل الدفع وانتظر التفعيل (24h)\n"
        "3️⃣ أكمل مهامك اليومية واربح يومياً\n"
        "4️⃣ ادعُ أصدقاءك واربح عمولات 6 مستويات\n"
        "5️⃣ اسحب أرباحك عبر USDT TRC20\n\n"
        "💳 **الباقات:**\n"
        "A1: 200$ → 3.33$/يوم\n"
        "A2: 400$ → 6.66$/يوم\n"
        "A3: 600$ → 10$/يوم\n"
        "B1: 1200$ → 20$/يوم\n"
        "B2: 1800$ → 30$/يوم\n"
        "B3: 2500$ → 41.66$/يوم\n\n"
        f"💸 الحد الأدنى للسحب: {MIN_WITHDRAW}$"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]),
        parse_mode="Markdown"
    )

# ===================== زر الرجوع =====================
async def back_to_main(query, user_id):
    user = get_user(user_id)
    balance = user[5] if user else 0
    pkg = user[6] if user else None
    today_row = get_today_tasks(user_id)
    done = today_row[3] if today_row else 0
    total = PACKAGES[pkg]["tasks"] if pkg else 0

    await query.edit_message_text(
        f"🏠 **القائمة الرئيسية**\n\n"
        f"💎 باقتك: **{pkg or 'لا توجد'}**\n"
        f"💰 رصيدك: **{balance:.2f}$**\n"
        f"📋 مهام اليوم: **{done}/{total}**\n\n"
        f"اختر من القائمة 👇",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

# ===================== معالج الأزرار =====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "daily_tasks":
        await show_daily_tasks(query, user_id)
    elif data == "start_task":
        await start_task(query, user_id)
    elif data == "confirm_task":
        await confirm_task(query, user_id)
    elif data == "wallet":
        await show_wallet(query, user_id)
    elif data == "packages":
        await show_packages(query, user_id)
    elif data.startswith("buy_"):
        await show_package_detail(query, user_id, data[4:])
    elif data.startswith("send_receipt_"):
        pkg_name = data[13:]
        result = await request_receipt(query, user_id, pkg_name, context)
        context.user_data["state"] = WAITING_RECEIPT
    elif data == "referrals":
        await show_referrals(query, user_id, context)
    elif data == "copy_ref":
        u = get_user(user_id)
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={u[8]}"
        await query.answer(f"رابطك: {link}", show_alert=True)
    elif data == "withdraw":
        await show_withdraw(query, user_id)
    elif data == "add_wallet":
        await request_wallet(query, context)
        context.user_data["state"] = WAITING_WALLET
    elif data == "help":
        await show_help(query)
    elif data == "back_main":
        await back_to_main(query, user_id)

# ===================== أوامر الأدمن =====================
async def approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        request_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ الصيغة: /approve رقم_الطلب")
        return

    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, package FROM packages_history WHERE id=? AND status='pending'", (request_id,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("❌ الطلب غير موجود أو مُعالَج مسبقاً.")
        conn.close()
        return

    user_id, pkg_name = row
    c.execute("UPDATE packages_history SET status='approved' WHERE id=?", (request_id,))
    c.execute("UPDATE users SET package=? WHERE user_id=?", (pkg_name, user_id))
    conn.commit()
    conn.close()

    # توزيع عمولات الإحالة
    distribute_referral_commissions(user_id, pkg_name)

    # إشعار المستخدم
    try:
        await context.bot.send_message(
            user_id,
            f"🎉 **تم تفعيل باقتك!**\n\n"
            f"باقة **{pkg_name}** مفعّلة الآن\n"
            f"ابدأ بإكمال مهامك اليومية وربح يومياً 💰",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
    except:
        pass

    await update.message.reply_text(f"✅ تم تفعيل الباقة للمستخدم {user_id} — طلب #{request_id}")

async def reject_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        request_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ الصيغة: /reject رقم_الطلب")
        return

    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM packages_history WHERE id=?", (request_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("❌ الطلب غير موجود.")
        return
    user_id = row[0]
    c.execute("UPDATE packages_history SET status='rejected' WHERE id=?", (request_id,))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(user_id, "❌ تم رفض وصل الدفع. يرجى التواصل مع الدعم.")
    except:
        pass
    await update.message.reply_text(f"❌ تم رفض الطلب #{request_id}")

async def approve_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        request_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ الصيغة: /withdraw_approve رقم_الطلب")
        return

    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, amount, wallet FROM withdrawals WHERE id=? AND status='pending'", (request_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("❌ الطلب غير موجود.")
        return
    user_id, amount, wallet = row
    c.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (request_id,))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(user_id,
            f"✅ **تم إرسال سحبك!**\n\n"
            f"المبلغ: **{amount:.2f}$**\n"
            f"المحفظة: `{wallet}`\n"
            f"تحقق من محفظتك خلال 24-48 ساعة",
            parse_mode="Markdown"
        )
    except:
        pass
    await update.message.reply_text(f"✅ تم قبول طلب السحب #{request_id} — {amount}$ → {wallet}")

async def reject_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        request_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ الصيغة: /withdraw_reject رقم_الطلب")
        return

    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, amount FROM withdrawals WHERE id=? AND status='pending'", (request_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("❌ الطلب غير موجود.")
        return
    user_id, amount = row
    c.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (request_id,))
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(user_id, f"❌ تم رفض طلب السحب. تمت إعادة {amount:.2f}$ لرصيدك.")
    except:
        pass
    await update.message.reply_text(f"❌ تم رفض الطلب #{request_id} وإعادة الرصيد")

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total, pending_pay, pending_withdraw = get_stats()
    await update.message.reply_text(
        f"👑 **لوحة الأدمن**\n\n"
        f"👥 إجمالي المستخدمين: {total}\n"
        f"⏳ طلبات دفع معلقة: {pending_pay}\n"
        f"💸 طلبات سحب معلقة: {pending_withdraw}\n\n"
        f"**أوامر الدفع:**\n"
        f"`/approve رقم` — قبول طلب شراء\n"
        f"`/reject رقم` — رفض طلب شراء\n\n"
        f"**أوامر السحب:**\n"
        f"`/withdraw_approve رقم`\n"
        f"`/withdraw_reject رقم`\n\n"
        f"**أوامر أخرى:**\n"
        f"`/addtasklink رابط` — إضافة رابط يوتيوب\n"
        f"`/broadcast رسالة` — إرسال للجميع\n"
        f"`/addbal user_id مبلغ` — إضافة رصيد",
        parse_mode="Markdown"
    )

async def add_task_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ الصيغة: /addtasklink رابط_يوتيوب")
        return
    link = context.args[0]
    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO task_links (url) VALUES (?)", (link,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ تمت إضافة الرابط: {link}")

async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0])
        amount = float(context.args[1])
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تمت إضافة {amount}$ للمستخدم {uid}")
    except:
        await update.message.reply_text("❌ الصيغة: /addbal user_id مبلغ")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("❌ أدخل الرسالة!")
        return
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    sent, failed = 0, 0
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, msg)
            sent += 1
        except:
            failed += 1
    await update.message.reply_text(f"✅ أُرسلت لـ {sent} | ❌ فشل مع {failed}")

# معالج الرسائل العامة (للمحادثات)
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state == WAITING_WALLET:
        result = await save_wallet(update, context)
        if result == ConversationHandler.END:
            context.user_data.clear()
    elif state == WAITING_RECEIPT:
        result = await receive_receipt(update, context)
        if result == ConversationHandler.END:
            context.user_data.clear()
    elif state == WAITING_WITHDRAW:
        result = await process_withdraw(update, context)
        if result == ConversationHandler.END:
            context.user_data.clear()

# ===================== تشغيل البوت =====================
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("approve", approve_payment))
    app.add_handler(CommandHandler("reject", reject_payment))
    app.add_handler(CommandHandler("withdraw_approve", approve_withdraw))
    app.add_handler(CommandHandler("withdraw_reject", reject_withdraw))
    app.add_handler(CommandHandler("addtasklink", add_task_link))
    app.add_handler(CommandHandler("addbal", add_balance_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))

    print("🤖 TEAMO Bot يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
