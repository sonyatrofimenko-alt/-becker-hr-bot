from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from config import TOKEN, HR_PHONE, HR_EMAIL, HR_NAME

# --- Главное меню ---
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Частые вопросы", callback_data="faq")],
        [InlineKeyboardButton("📝 Подать заявку", callback_data="request")],
        [InlineKeyboardButton("📞 Контакты HR", callback_data="contacts")],
    ])

# --- FAQ ---
faq_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("🏖 Как взять отпуск?", callback_data="faq_vacation")],
    [InlineKeyboardButton("📄 Как получить справку?", callback_data="faq_cert")],
    [InlineKeyboardButton("🤒 Больничный", callback_data="faq_sick")],
    [InlineKeyboardButton("💰 Зарплата и выплаты", callback_data="faq_salary")],
    [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
])

# --- Заявки ---
request_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("📑 Справка с места работы", callback_data="req_cert_work")],
    [InlineKeyboardButton("📊 Справка 2-НДФЛ", callback_data="req_cert_ndfl")],
    [InlineKeyboardButton("🗓 Отгул / отпуск за свой счёт", callback_data="req_dayoff")],
    [InlineKeyboardButton("✏️ Другое", callback_data="req_other")],
    [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
])

# --- Ответы на FAQ ---
FAQ_ANSWERS = {
    "faq_vacation": (
        "🏖 <b>Как взять отпуск?</b>\n\n"
        "1. Подайте заявление на имя руководителя за <b>2 недели</b> до начала отпуска\n"
        "2. Руководитель подписывает и передаёт в HR\n"
        "3. HR оформляет приказ в течение 3 рабочих дней\n"
        "4. Отпускные выплачиваются за <b>3 дня</b> до начала отпуска\n\n"
        "📌 Ежегодный оплачиваемый отпуск — <b>28 календарных дней</b>"
    ),
    "faq_cert": (
        "📄 <b>Как получить справку?</b>\n\n"
        "Подайте заявку через этого бота (кнопка «Подать заявку»)\n\n"
        "⏱ Сроки изготовления:\n"
        "• Справка с места работы — <b>3 рабочих дня</b>\n"
        "• Справка 2-НДФЛ — <b>5 рабочих дней</b>\n\n"
        "📌 Справки выдаются в отделе кадров лично или по email"
    ),
    "faq_sick": (
        "🤒 <b>Больничный лист</b>\n\n"
        "1. В первый день болезни — предупредите руководителя\n"
        "2. Оформите электронный больничный у врача\n"
        "3. После выздоровления — сообщите номер больничного в HR\n\n"
        "📌 Электронный больничный HR получает автоматически через СФР\n"
        "📌 Оплата — в ближайший день выплаты зарплаты"
    ),
    "faq_salary": (
        "💰 <b>Зарплата и выплаты</b>\n\n"
        "• Аванс: <b>25 числа</b> каждого месяца\n"
        "• Зарплата: <b>10 числа</b> следующего месяца\n\n"
        "По вопросам расчётного листка обращайтесь в бухгалтерию\n"
        f"или в HR: {HR_EMAIL}"
    ),
}

# --- Тексты заявок ---
REQUEST_TEXTS = {
    "req_cert_work": "📑 <b>Заявка принята: Справка с места работы</b>\n\nСотрудник HR свяжется с вами в течение 1 рабочего дня для уточнения деталей.\n\n⏱ Срок изготовления: 3 рабочих дня",
    "req_cert_ndfl": "📊 <b>Заявка принята: Справка 2-НДФЛ</b>\n\nСотрудник HR свяжется с вами в течение 1 рабочего дня.\n\n⏱ Срок изготовления: 5 рабочих дней",
    "req_dayoff": "🗓 <b>Заявка на отгул/отпуск за свой счёт</b>\n\nПожалуйста, напишите в следующем сообщении:\n• Желаемую дату\n• Причину (по желанию)\n\nHR рассмотрит заявку в течение 1 рабочего дня.",
    "req_other": f"✏️ <b>Другой вопрос</b>\n\nОпишите ваш вопрос в следующем сообщении, и HR-менеджер ответит вам в течение рабочего дня.\n\nИли свяжитесь напрямую:\n📞 {HR_PHONE}\n✉️ {HR_EMAIL}",
}


# === ХЭНДЛЕРЫ ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"Привет, {name}! 👋\n\n"
        "Я HR-помощник вашей компании.\n"
        "Помогу ответить на вопросы и принять заявки.\n\n"
        "Выберите, что вас интересует:",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Главное меню
    if data == "back_main":
        await query.edit_message_text(
            "Выберите, что вас интересует:",
            reply_markup=main_menu_keyboard()
        )

    # FAQ
    elif data == "faq":
        await query.edit_message_text(
            "📋 <b>Частые вопросы</b>\n\nВыберите тему:",
            reply_markup=faq_keyboard,
            parse_mode="HTML"
        )
    elif data in FAQ_ANSWERS:
        back_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К вопросам", callback_data="faq")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
        ])
        await query.edit_message_text(
            FAQ_ANSWERS[data],
            reply_markup=back_btn,
            parse_mode="HTML"
        )

    # Заявки
    elif data == "request":
        await query.edit_message_text(
            "📝 <b>Подать заявку</b>\n\nВыберите тип заявки:",
            reply_markup=request_keyboard,
            parse_mode="HTML"
        )
    elif data in REQUEST_TEXTS:
        back_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Другая заявка", callback_data="request")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
        ])
        await query.edit_message_text(
            REQUEST_TEXTS[data],
            reply_markup=back_btn,
            parse_mode="HTML"
        )

    # Контакты
    elif data == "contacts":
        back_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]
        ])
        await query.edit_message_text(
            f"📞 <b>Контакты HR</b>\n\n"
            f"🏢 {HR_NAME}\n"
            f"📱 {HR_PHONE}\n"
            f"✉️ {HR_EMAIL}\n\n"
            f"⏰ Режим работы: Пн–Пт, 9:00–18:00",
            reply_markup=back_btn,
            parse_mode="HTML"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отвечаем на любое текстовое сообщение"""
    await update.message.reply_text(
        "Воспользуйтесь меню для навигации 👇",
        reply_markup=main_menu_keyboard()
    )


# === ЗАПУСК ===
if __name__ == "__main__":
    print("✅ HR-бот запущен! Нажми Ctrl+C для остановки.")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
