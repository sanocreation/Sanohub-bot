import logging
import os
import asyncio
import base64
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from pymongo import MongoClient
from cryptography.fernet import Fernet

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = "8444279342:AAF3asBL-9YcXkMS1RX3AYngr0TN61uvVMw"
MONGO_URI = "mongodb+srv://sanomanjiro369369369_db_user:S15wDBqDsBu2zQGD@cluster0.xjz3qk.mongodb.net/content_bot?retryWrites=true&w=majority"
ADMIN_IDS = [5792484278]
PAYMENT_NUMBER = "+91 7003987024"
LINK_KEY = "SanoHub-Secret-Key-32-Chars-Long!!"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", 10000))

# Pricing
PLANS = {
    "7": {"price": "29", "days": 7, "name": "7 Days"},
    "30": {"price": "99", "days": 30, "name": "30 Days"},
    "lifetime": {"price": "499", "days": 36500, "name": "Lifetime"}
}

# Database
client = MongoClient(MONGO_URI)
db = client['content_bot']
users_col = db.users
movies_col = db.movies
anime_col = db.anime
modapk_col = db.modapk

# Create indexes
movies_col.create_index([("title", "text"), ("keywords", "text")])
anime_col.create_index([("title", "text"), ("keywords", "text")])
modapk_col.create_index([("title", "text"), ("keywords", "text")])

# Encryption
cipher = Fernet(base64.urlsafe_b64encode(LINK_KEY[:32].encode()))

# Flask App
app = Flask(__name__)

# Conversation States
(ADMIN_TITLE, ADMIN_QUALITY, ADMIN_SIZE, ADMIN_LINK, ADMIN_CATEGORY, ADMIN_KEYWORDS, BROADCAST_MSG) = range(7)

# ═══════════════════════════════════════════════════════════

def get_user(user_id):
    return users_col.find_one({"user_id": user_id})

def create_user(user_id, username, first_name):
    user = {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "joined_at": datetime.now(),
        "is_premium": False,
        "premium_until": None,
        "total_downloads": 0,
        "ads_watched": 0,
        "referral_code": f"REF{user_id}",
        "referred_by": None
    }
    users_col.insert_one(user)
    return user

def is_premium(user_id):
    user = get_user(user_id)
    if not user or not user.get("is_premium"):
        return False
    if user.get("premium_until") and user["premium_until"] < datetime.now():
        users_col.update_one({"user_id": user_id}, {"$set": {"is_premium": False}})
        return False
    return True

def add_premium(user_id, days):
    until = datetime.now() + timedelta(days=days)
    users_col.update_one({"user_id": user_id}, {"$set": {"is_premium": True, "premium_until": until}})

def search_content(collection, query, limit=10):
    return list(collection.find({
        "$or": [
            {"title": {"$regex": query, "$options": "i"}},
            {"keywords": {"$regex": query, "$options": "i"}}
        ]
    }).limit(limit))

def get_content_by_id(collection, content_id):
    from bson.objectid import ObjectId
    try:
        return collection.find_one({"_id": ObjectId(content_id)})
    except:
        return None

def add_content(collection, data):
    data["added_at"] = datetime.now()
    return collection.insert_one(data)

def encrypt_link(text):
    return cipher.encrypt(text.encode()).decode()

def decrypt_link(text):
    try:
        return cipher.decrypt(text.encode()).decode()
    except:
        return None

# ═══════════════════════════════════════════════════════════
# BOT HANDLERS
# ═══════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    
    # Referral handling
    if args and args[0].startswith("REF"):
        referrer_id = args[0].replace("REF", "")
        if referrer_id != str(user.id):
            if not get_user(user.id):
                create_user(user.id, user.username, user.first_name)
            users_col.update_one({"user_id": user.id}, {"$set": {"referred_by": int(referrer_id)}})
            users_col.update_one({"user_id": int(referrer_id)}, {"$inc": {"balance": 5}})
            await context.bot.send_message(
                chat_id=int(referrer_id),
                text=f"🎉 New referral! You earned ৳5. User: {user.first_name}"
            )
    else:
        if not get_user(user.id):
            create_user(user.id, user.username, user.first_name)
    
    is_prem = is_premium(user.id)
    user_data = get_user(user.id)
    
    welcome_text = f"""
🎯 <b>Welcome to SanoHub BD</b>

┌──────────────────────────────┐
│  👤 User: {user.first_name[:15]}         
│  💎 Status: {'🟢 PREMIUM' if is_prem else '🔴 FREE'}     
│  📥 Downloads: {user_data.get('total_downloads', 0)}        
└──────────────────────────────┘

<i>Choose your content type:</i>
"""
    
    keyboard = [
        [InlineKeyboardButton("🎬 Movies & Webseries", callback_data="cat_movies")],
        [InlineKeyboardButton("🎌 Anime Series", callback_data="cat_anime")],
        [InlineKeyboardButton("📱 Mod APK & Games", callback_data="cat_modapk")],
        [InlineKeyboardButton("💎 Upgrade to Premium", callback_data="menu_premium")],
        [InlineKeyboardButton("👤 My Account", callback_data="menu_account")],
        [InlineKeyboardButton("🎁 Earn Money", callback_data="menu_earn")]
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
    
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.replace("cat_", "")
    context.user_data['search_category'] = data
    
    text = f"""
{'🎬 Movies & Webseries' if data == 'movies' else '🎌 Anime Series' if data == 'anime' else '📱 Mod APK'}

🔍 <b>Send me content name to search</b>

<i>Example: Avengers, Naruto, Minecraft</i>
"""
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    search_query = update.message.text
    category = context.user_data.get('search_category', 'movies')
    
    collections = {'movies': movies_col, 'anime': anime_col, 'modapk': modapk_col}
    collection = collections.get(category, movies_col)
    
    results = search_content(collection, search_query)
    
    if not results:
        await update.message.reply_text(
            "❌ <b>No results found!</b>\nTry different keywords.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"cat_{category}")]])
        )
        return
    
    text = f"🎯 <b>Found {len(results)} results:</b>\n\n"
    for idx, item in enumerate(results[:10], 1):
        text += f"{idx}. <b>{item.get('title', 'Unknown')}</b>\n   📊 {item.get('quality', 'N/A')} | 💾 {item.get('size', 'N/A')}\n\n"
    
    keyboard = []
    for item in results[:10]:
        title = item.get('title', 'Unknown')[:30] + "..." if len(item.get('title', '')) > 30 else item.get('title', 'Unknown')
        keyboard.append([InlineKeyboardButton(f"📥 {title}", callback_data=f"dl_{category}_{str(item['_id'])}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"cat_{category}")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def download_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    data = query.data.split("_")
    
    if len(data) < 3:
        await query.edit_message_text("❌ Invalid request!")
        return
    
    category, content_id = data[1], data[2]
    collections = {'movies': movies_col, 'anime': anime_col, 'modapk': modapk_col}
    content = get_content_by_id(collections.get(category), content_id)
    
    if not content:
        await query.edit_message_text("❌ Content not found!")
        return
    
    is_prem = is_premium(user.id)
    users_col.update_one({"user_id": user.id}, {"$inc": {"total_downloads": 1}})
    
    title = content.get('title', 'Unknown')
    quality = content.get('quality', 'N/A')
    size = content.get('size', 'N/A')
    
    if is_prem:
        link = content.get('download_link')
        text = f"""
✨ <b>PREMIUM ACCESS</b> ✨

🎬 <b>{title}</b>
📊 {quality} | 💾 {size}

🔗 <b>Direct Link:</b>
<code>{link}</code>

⚡ <i>Fast & Ad-Free!</i>
"""
        keyboard = [[InlineKeyboardButton("🚀 Download", url=link)], [InlineKeyboardButton("🔙 Back", callback_data=f"cat_{category}")]]
    else:
        encrypted = encrypt_link(f"{category}:{content_id}")
        bot_username = "SanoHub_Bot"
        ad_link = f"https://www.google.com/search?q=watch+ad+then+go+to+https://t.me/{bot_username}?start=DL{encrypted.replace('/', '_')}"
        
        text = f"""
🎬 <b>{title}</b>
📊 {quality} | 💾 {size}

💎 <b>Get Premium for instant access!</b>

🆓 <b>Free Method:</b>
1️⃣ Click "Watch Ad" 
2️⃣ Wait 10 seconds
3️⃣ Return to bot

⏱️ <i>~15 seconds</i>
"""
        keyboard = [
            [InlineKeyboardButton("🎯 Watch Ad (15s)", url=ad_link)],
            [InlineKeyboardButton("💎 Buy Premium", callback_data="menu_premium")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"cat_{category}")]
        ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML', disable_web_page_preview=True)

async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = f"""
💎 <b>UPGRADE TO PREMIUM</b> 💎

✅ Instant Downloads
✅ No Ads
✅ Direct Links
✅ 4K Quality

┌─────────────────────────────────┐
│  📅 7 Days    - ৳{PLANS['7']['price']}             │
│  📅 30 Days   - ৳{PLANS['30']['price']}             │
│  ♾️ Lifetime  - ৳{PLANS['lifetime']['price']}            │
└─────────────────────────────────┘

💳 Payment: <code>{PAYMENT_NUMBER}</code>
"""
    keyboard = [
        [InlineKeyboardButton("7 Days - ৳29", callback_data="pay_7"), InlineKeyboardButton("30 Days - ৳99", callback_data="pay_30")],
        [InlineKeyboardButton("♾️ Lifetime - ৳499", callback_data="pay_lifetime")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    plan = query.data.replace("pay_", "")
    plan_data = PLANS.get(plan)
    
    if not plan_data:
        return
    
    text = f"""
💳 <b>PAYMENT - {plan_data['name']}</b>

Amount: <b>৳{plan_data['price']}</b>

┌─────────────────────────────────┐
│  📲 <b>bKash/Nagad:</b> {PAYMENT_NUMBER} │
│  (Send Money)                   │
│                                 │
│  ✅ After payment, contact:     │
│     @SanoHub_Support            │
│                                 │
│  Send: Transaction ID + Screenshot│
└─────────────────────────────────┘

⏳ Verification: 5-30 minutes
"""
    keyboard = [
        [InlineKeyboardButton("✅ I've Paid", url="https://t.me/SanoHub_Support")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_premium")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_data = get_user(user.id)
    is_prem = is_premium(user.id)
    
    status = "🟢 Active" if is_prem else "🔴 Inactive"
    if is_prem and user_data.get('premium_until'):
        days_left = (user_data['premium_until'] - datetime.now()).days
        status += f" ({days_left}d)"
    
    text = f"""
👤 <b>MY ACCOUNT</b>

🆔 <code>{user.id}</code>
💎 Premium: {status}
📥 Downloads: {user_data.get('total_downloads', 0)}
👥 Referrals: {user_data.get('balance', 0)//5}

<i>Refer friends to earn ৳5 each!</i>
"""
    keyboard = [
        [InlineKeyboardButton("💎 Upgrade", callback_data="menu_premium")],
        [InlineKeyboardButton("🔗 Referral Link", callback_data="get_ref")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def earn_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    bot_username = "SanoHub_Bot"
    ref_link = f"https://t.me/{bot_username}?start=REF{user.id}"
    
    text = f"""
🎁 <b>EARN FREE PREMIUM</b>

<b>Referral Program:</b>
👥 Invite friends = ৳5 each
🎁 10 referrals = 7 days FREE premium!

<b>Your Link:</b>
<code>{ref_link}</code>
"""
    keyboard = [
        [InlineKeyboardButton("📤 Share", url=f"https://t.me/share/url?url={ref_link}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await query.answer("❌ Unauthorized!", show_alert=True)
        return
    
    await query.answer()
    
    stats = {
        "users": users_col.count_documents({}),
        "premium": users_col.count_documents({"is_premium": True}),
        "movies": movies_col.count_documents({}),
        "anime": anime_col.count_documents({}),
        "modapk": modapk_col.count_documents({})
    }
    
    text = f"""
🔐 <b>ADMIN PANEL</b>

👥 Users: {stats['users']}
💎 Premium: {stats['premium']}
🎬 Movies: {stats['movies']}
🎌 Anime: {stats['anime']}
📱 Mod APK: {stats['modapk']}
"""
    keyboard = [
        [InlineKeyboardButton("➕ Add Movie", callback_data="admin_add_movies"), InlineKeyboardButton("➕ Add Anime", callback_data="admin_add_anime")],
        [InlineKeyboardButton("➕ Add Mod APK", callback_data="admin_add_modapk")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    category = query.data.replace("admin_add_", "")
    context.user_data['admin_category'] = category
    
    await query.edit_message_text(f"📝 <b>Add {category.title()}</b>\n\nSend title:", parse_mode='HTML')
    return ADMIN_TITLE

async def admin_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['content_title'] = update.message.text
    await update.message.reply_text("✅ Title saved! Send quality (1080p/720p):")
    return ADMIN_QUALITY

async def admin_get_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['content_quality'] = update.message.text
    await update.message.reply_text("✅ Quality saved! Send size (1.5GB):")
    return ADMIN_SIZE

async def admin_get_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['content_size'] = update.message.text
    await update.message.reply_text("✅ Size saved! Send Google Drive link:")
    return ADMIN_LINK

async def admin_get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['content_link'] = update.message.text
    await update.message.reply_text("✅ Link saved! Send category (Hollywood/Bollywood):")
    return ADMIN_CATEGORY

async def admin_get_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['content_category'] = update.message.text
    await update.message.reply_text("✅ Category saved! Send keywords (comma separated):")
    return ADMIN_KEYWORDS

async def admin_get_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['content_keywords'] = update.message.text
    
    category = context.user_data['admin_category']
    collections = {'movies': movies_col, 'anime': anime_col, 'modapk': modapk_col}
    
    data = {
        "title": context.user_data['content_title'],
        "quality": context.user_data['content_quality'],
        "size": context.user_data['content_size'],
        "download_link": context.user_data['content_link'],
        "category": context.user_data['content_category'],
        "keywords": context.user_data['content_keywords'],
        "rating": "⭐⭐⭐⭐"
    }
    
    add_content(collections.get(category, movies_col), data)
    
    await update.message.reply_text(
        f"✅ <b>Added Successfully!</b>\n\n🎬 {data['title']}",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")]])
    )
    return ConversationHandler.END

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📢 Send broadcast message:", parse_mode='HTML')
    return BROADCAST_MSG

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    users = list(users_col.find({}))
    
    sent, failed = 0, 0
    status = await update.message.reply_text(f"Broadcasting... 0/{len(users)}")
    
    for user in users:
        try:
            await message.copy(chat_id=user['user_id'])
            sent += 1
        except:
            failed += 1
        
        if sent % 20 == 0:
            await status.edit_text(f"Broadcasting... {sent}/{len(users)} (Failed: {failed})")
        await asyncio.sleep(0.1)
    
    await status.edit_text(f"✅ Done! Sent: {sent}, Failed: {failed}")
    return ConversationHandler.END

async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_main":
        await start(update, context)
    elif query.data.startswith("cat_"):
        await category_handler(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════

@app.route('/')
def home():
    return "✅ SanoHub Bot is running!"

@app.route('/health')
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_add_start, pattern="^admin_add_"),
            CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")
        ],
        states={
            ADMIN_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_title)],
            ADMIN_QUALITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_quality)],
            ADMIN_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_size)],
            ADMIN_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_link)],
            ADMIN_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_category)],
            ADMIN_KEYWORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_keywords)],
            BROADCAST_MSG: [MessageHandler(filters.ALL, admin_broadcast_send)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(category_handler, pattern="^cat_"))
    application.add_handler(CallbackQueryHandler(download_handler, pattern="^dl_"))
    application.add_handler(CallbackQueryHandler(premium_menu, pattern="^menu_premium$"))
    application.add_handler(CallbackQueryHandler(payment_handler, pattern="^pay_"))
    application.add_handler(CallbackQueryHandler(my_account, pattern="^menu_account$"))
    application.add_handler(CallbackQueryHandler(earn_money, pattern="^menu_earn$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(back_handler, pattern="^back_"))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    
    # Webhook setup
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            url_path="/webhook"
        )
    else:
        application.run_polling()

if __name__ == "__main__":
    main()
