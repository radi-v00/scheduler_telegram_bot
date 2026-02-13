import os
import asyncio
from datetime import datetime, timedelta
import pytz
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
import asyncpg

TOKEN = os.environ['BOT_TOKEN']
DATABASE_URL = os.environ['NEON_DATABASE_URL']

# ---------- Flask app ----------
app = Flask(__name__)

# ---------- Telegram Application (global, no background tasks) ----------
telegram_app = Application.builder().token(TOKEN).build()

# ---------- Database connection pool ----------
db_pool = None

async def init_db_pool():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)

@app.before_first_request
def before_first_request():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db_pool())

# ---------- Command Handlers (all async) ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I'm your scheduler bot.\n"
        "Commands:\n"
        "/addtask YYYY-MM-DD HH:MM description\n"
        "/mytasks - list your upcoming tasks\n"
        "/deletetask <task_id>\n"
        "/changetime <task_id> YYYY-MM-DD HH:MM\n"
        "/setroutine <task_id> daily/weekly/monthly\n"
        "/help"
    )

async def addtask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a one-time task. Usage: /addtask 2025-03-20 15:30 Buy milk"""
    try:
        args = context.args
        if len(args) < 3:
            await update.message.reply_text("Usage: /addtask YYYY-MM-DD HH:MM description")
            return
        date_str = args[0]
        time_str = args[1]
        description = ' '.join(args[2:])
        dt_str = f"{date_str} {time_str}"
        scheduled = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        scheduled = pytz.UTC.localize(scheduled)
        user_id = update.effective_user.id

        async with db_pool.acquire() as conn:
            task_id = await conn.fetchval(
                "INSERT INTO tasks (user_id, description, scheduled_time) VALUES ($1, $2, $3) RETURNING id",
                user_id, description, scheduled
            )
        await update.message.reply_text(f"Task added with ID {task_id}")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def mytasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List upcoming tasks"""
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, description, scheduled_time FROM tasks WHERE user_id = $1 AND scheduled_time > NOW() ORDER BY scheduled_time LIMIT 20",
            user_id
        )
    if not rows:
        await update.message.reply_text("No upcoming tasks.")
        return
    lines = [f"{row['id']}: {row['description']} at {row['scheduled_time'].strftime('%Y-%m-%d %H:%M UTC')}" for row in rows]
    await update.message.reply_text("Your upcoming tasks:\n" + "\n".join(lines))

async def deletetask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a task by ID"""
    try:
        task_id = int(context.args[0])
        user_id = update.effective_user.id
        async with db_pool.acquire() as conn:
            result = await conn.execute("DELETE FROM tasks WHERE id = $1 AND user_id = $2", task_id, user_id)
        if result == "DELETE 0":
            await update.message.reply_text("Task not found or not yours.")
        else:
            await update.message.reply_text("Task deleted.")
    except:
        await update.message.reply_text("Usage: /deletetask <task_id>")

async def changetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change scheduled time of a task"""
    try:
        task_id = int(context.args[0])
        date_str = context.args[1]
        time_str = context.args[2]
        dt_str = f"{date_str} {time_str}"
        new_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        new_time = pytz.UTC.localize(new_time)
        user_id = update.effective_user.id
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE tasks SET scheduled_time = $1 WHERE id = $2 AND user_id = $3",
                new_time, task_id, user_id
            )
        if result == "UPDATE 0":
            await update.message.reply_text("Task not found or not yours.")
        else:
            await update.message.reply_text("Task time updated.")
    except:
        await update.message.reply_text("Usage: /changetime <task_id> YYYY-MM-DD HH:MM")

async def setroutine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set recurrence for a task"""
    try:
        task_id = int(context.args[0])
        recurrence = context.args[1].lower()
        if recurrence not in ['daily', 'weekly', 'monthly']:
            await update.message.reply_text("Recurrence must be daily, weekly, or monthly.")
            return
        user_id = update.effective_user.id
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE tasks SET recurrence = $1 WHERE id = $2 AND user_id = $3",
                recurrence, task_id, user_id
            )
        if result == "UPDATE 0":
            await update.message.reply_text("Task not found or not yours.")
        else:
            await update.message.reply_text(f"Task recurrence set to {recurrence}.")
    except:
        await update.message.reply_text("Usage: /setroutine <task_id> daily|weekly|monthly")

# ---------- Register handlers with the Application ----------
telegram_app.add_handler(CommandHandler('start', start))
telegram_app.add_handler(CommandHandler('addtask', addtask))
telegram_app.add_handler(CommandHandler('mytasks', mytasks))
telegram_app.add_handler(CommandHandler('deletetask', deletetask))
telegram_app.add_handler(CommandHandler('changetime', changetime))
telegram_app.add_handler(CommandHandler('setroutine', setroutine))
# Optional: catch-all for unknown commands
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sorry, I didn't understand that command.")
telegram_app.add_handler(CommandHandler(None, unknown))  # This might need a different approach; better use MessageHandler with Filters.command

# For unknown commands, you can use:
from telegram.ext import MessageHandler, filters
telegram_app.add_handler(MessageHandler(filters.COMMAND, unknown))

# ---------- Webhook Endpoint ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    """Receive Telegram update and process it."""
    # Convert JSON to Update object
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    # Process the update asynchronously
    asyncio.run(telegram_app.process_update(update))
    return 'ok'

# ---------- Task Checking Endpoint (for cron) ----------
async def check_due_tasks():
    """Find tasks due now and send reminders, then reschedule recurring tasks."""
    async with db_pool.acquire() as conn:
        now = datetime.now(pytz.UTC)
        due_tasks = await conn.fetch(
            "SELECT * FROM tasks WHERE scheduled_time <= $1",
            now
        )
        for task in due_tasks:
            # Send reminder
            await telegram_app.bot.send_message(
                chat_id=task['user_id'],
                text=f"⏰ Reminder: {task['description']}"
            )
            # Handle recurrence
            if task['recurrence']:
                next_time = task['scheduled_time']
                if task['recurrence'] == 'daily':
                    next_time = next_time + timedelta(days=1)
                elif task['recurrence'] == 'weekly':
                    next_time = next_time + timedelta(weeks=1)
                elif task['recurrence'] == 'monthly':
                    next_time = next_time + timedelta(days=30)
                await conn.execute(
                    "UPDATE tasks SET scheduled_time = $1 WHERE id = $2",
                    next_time, task['id']
                )
            else:
                # One-time task: delete it
                await conn.execute("DELETE FROM tasks WHERE id = $1", task['id'])

@app.route('/check-tasks', methods=['GET'])
def check_tasks():
    """Endpoint called by external cron service."""
    asyncio.run(check_due_tasks())
    return 'Checked'