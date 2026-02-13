import telebot
import os
from dotenv import load_dotenv
load_dotenv()

bot_token = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(bot_token)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "hello world XD for testing our feature use /add /delete /list /next_task commands")
    print ("Received /start command from user: ", message.from_user.id)


print ("Bot is running...")
bot.polling(non_stop=True)