import random
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)
from config import TOKEN


async def send_rejection(context: ContextTypes.DEFAULT_TYPE):
    """Отложенный отказ кандидату с опытом в мебели"""
    await context.bot.send_message(
        chat_id=context.job.data["user_id"],
        text=(
            "Здравствуйте, {}! 👋\n\n"
            "Спасибо за интерес к нашей вакансии и время, которое вы уделили анкете.\n\n"
            "К сожалению, на данный момент мы ищем кандидатов без опыта работы "
            "в мебельной отрасли — нам важно обучить специалиста под наши стандарты.\n\n"
            "Желаем вам успехов в поиске работы! 🙏"
        ).format(context.job.data["name"])
    )

# Твой Telegram ID — сюда придут анкеты кандидатов
HR_TELEGRAM_ID = 859413090

# Шаги анкеты
NAME, SALES_EXP, QUIT_REASON, FURNITURE_EXP, SALARY, LOCATION, EMPLOYMENT = range(7)

yes_no = ReplyKeyboardMarkup([["✅ Да", "❌ Нет"]], resize_keyboard=True, one_time_keyboard=True)
employed_kb = ReplyKeyboardMarkup([["💼 Работаю сейчас", "🚪 Уже уволился(ась)"]], resize_keyboard=True, one_time_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Вы откликнулись на нашу вакансию. Я помогу заполнить короткую анкету — "
        "это займёт 2 минуты, и HR-менеджер свяжется с вами.\n\n"
        "Как вас зовут? (Имя и фамилия)",
        reply_markup=ReplyKeyboardRemove()
    )
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text(
        "Есть ли у вас опыт в продажах?\n"
        "Если да — напишите сколько лет и в какой сфере.",
    )
    return SALES_EXP


async def get_sales_exp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sales_exp"] = update.message.text
    await update.message.reply_text(
        "Почему уходите / ушли с последнего места работы?"
    )
    return QUIT_REASON


async def get_quit_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["quit_reason"] = update.message.text
    await update.message.reply_text(
        "Был ли у вас опыт работы в мебельных компаниях?",
        reply_markup=yes_no
    )
    return FURNITURE_EXP


async def get_furniture_exp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["furniture_exp"] = update.message.text
    await update.message.reply_text(
        "Какой уровень зарплаты вас интересует? (укажите желаемую сумму или вилку)",
        reply_markup=ReplyKeyboardRemove()
    )
    return SALARY


async def get_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["salary"] = update.message.text
    await update.message.reply_text(
        "Наш офис находится у метро Сокольники. Это удобно для вас?",
        reply_markup=yes_no
    )
    return LOCATION


async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["location"] = update.message.text
    await update.message.reply_text(
        "Вы сейчас работаете или уже свободны?",
        reply_markup=employed_kb
    )
    return EMPLOYMENT


async def get_employment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["employment"] = update.message.text
    data = context.user_data
    user = update.effective_user

    # Сообщение кандидату
    await update.message.reply_text(
        "Спасибо! 🙌 Анкета принята.\n\n"
        "Мы рассмотрим ваш профиль и свяжемся с вами, если вы нам подойдёте.",
        reply_markup=ReplyKeyboardRemove()
    )

    # Сводка для Сони
    furniture = data.get("furniture_exp", "")
    flag = " ⚠️ ЕСТЬ ОПЫТ В МЕБЕЛИ — отказ запланирован" if furniture == "✅ Да" else ""

    summary = (
        f"📋 <b>Новая анкета кандидата</b>\n"
        f"{'─' * 30}\n"
        f"👤 <b>Имя:</b> {data.get('name')}\n"
        f"📱 <b>Telegram:</b> @{user.username or '—'} (ID: {user.id})\n\n"
        f"💼 <b>Опыт в продажах:</b>\n{data.get('sales_exp')}\n\n"
        f"🚪 <b>Причина ухода:</b>\n{data.get('quit_reason')}\n\n"
        f"🪑 <b>Опыт в мебели:</b> {furniture}{flag}\n\n"
        f"💰 <b>Желаемая зарплата:</b> {data.get('salary')}\n\n"
        f"🚇 <b>Сокольники удобно:</b> {data.get('location')}\n\n"
        f"📌 <b>Статус занятости:</b> {data.get('employment')}\n"
        f"{'─' * 30}"
    )

    await context.bot.send_message(
        chat_id=HR_TELEGRAM_ID,
        text=summary,
        parse_mode="HTML"
    )

    # Если был опыт в мебели — запланировать отказ через 30–40 минут
    if furniture == "✅ Да":
        delay = random.randint(30, 40) * 60
        context.job_queue.run_once(
            send_rejection,
            when=delay,
            data={"user_id": user.id, "name": data.get("name", "")},
            name=f"rejection_{user.id}"
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Анкета отменена. Если хотите начать заново — напишите /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


if __name__ == "__main__":
    print("✅ Бот для кандидатов запущен!")
    app = ApplicationBuilder().token(TOKEN).connect_timeout(30).read_timeout(30).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME:          [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            SALES_EXP:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sales_exp)],
            QUIT_REASON:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quit_reason)],
            FURNITURE_EXP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_furniture_exp)],
            SALARY:        [MessageHandler(filters.TEXT & ~filters.COMMAND, get_salary)],
            LOCATION:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)],
            EMPLOYMENT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_employment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.run_polling()
