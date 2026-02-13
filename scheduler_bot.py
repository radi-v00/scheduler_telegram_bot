import telebot
import os


bot_token = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(bot_token)
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "hello world ::: our feature /add /delete /list /next_task commands")
    print ("Received /start command from user: ", message.from_user.id)

print ("Bot is running...")
bot.polling(non_stop=True)
