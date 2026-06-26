import json, os, asyncio
from datetime import date, datetime, timedelta
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, WebAppInfo
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)

TOKEN      = os.environ.get("TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")
PORT       = int(os.environ.get("PORT", 8080))
WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")

# ── Настройки ────────────────────────────────────────────────────────────────
HR_IDS = {
    859413090: "Софья",    # @sonya_trof
    474244647: "Юлия",     # @yulia (второй HR)
}
HR_ID        = 859413090   # основной HR (для совместимости)
COMPANY_NAME = "BECKER (ООО Арт-дизайн)"
COMPANY_ADDR = "Стромынка 18к13, м. Сокольники"
HR_NAME      = "Софья"
HR_PHONE     = "+7 (919) 890-41-15"
HR_TELEGRAM  = "@sonya_trof"
DATA_FILE    = "hr_data.json"

DEFAULT_SLOTS = ["11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "17:30"]

def is_hr(user_id: int) -> bool:
    return user_id in HR_IDS

def hr_name(user_id: int) -> str:
    return HR_IDS.get(user_id, "HR")

# ── Хранилище ─────────────────────────────────────────────────────────────────
# Структура:
#   data["slots"][str(hr_id)][date_str]  = [time_list]   — расписание каждого HR
#   data["candidates"][str(user_id)]     = {..., "hr_id": int}  — к кому записан
def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"slots": {}, "candidates": {}}

def save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _hr_slots(data, hr_id: int) -> dict:
    """Возвращает словарь слотов конкретного HR (по ссылке — изменения сохранятся)."""
    key = str(hr_id)
    if key not in data["slots"]:
        data["slots"][key] = {}
    return data["slots"][key]

def get_free_slots(data, day_str: str, hr_id: int) -> list:
    """Свободные слоты конкретного HR на дату."""
    available = _hr_slots(data, hr_id).get(day_str, [])
    booked = {
        c["interview_time"]
        for c in data["candidates"].values()
        if c.get("interview_date") == day_str
        and c.get("hr_id") == hr_id
        and c.get("status") == "scheduled"
    }
    return [s for s in available if s not in booked]

def get_all_free_slots(data, day_str: str) -> list:
    """
    Возвращает [(time, hr_id), ...] — все свободные слоты на дату по всем HR.
    Если два HR имеют одно время — отдаём оба (Sonya первой, Yulia второй).
    """
    result = []
    for hr_id in HR_IDS:
        for t in get_free_slots(data, day_str, hr_id):
            result.append((t, hr_id))
    # Сортируем по времени, затем по HR
    result.sort(key=lambda x: x[0])
    return result

# ── Шаги диалога ──────────────────────────────────────────────────────────────
NAME, PICK_SPEC, PICK_FORMAT, PICK_DATE, PICK_TIME = range(5)

# HR по направлению: Офис → Софья, Разъезд → Юлия
HR_SONYA = 859413090
HR_YULIA  = 474244647

# ── HR-клавиатура ─────────────────────────────────────────────────────────────
HR_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📅 Расписание"),  KeyboardButton("👥 Кандидаты")],
        [KeyboardButton("📊 Статистика"),  KeyboardButton("❓ Помощь")],
        [KeyboardButton("👁 Превью бота")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие..."
)

# ── /menu ─────────────────────────────────────────────────────────────────────
async def menu_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_hr(uid):
        return
    data = load()
    today_str = date.today().strftime("%Y-%m-%d")

    my_today = sum(
        1 for c in data["candidates"].values()
        if c.get("interview_date") == today_str
        and c.get("hr_id") == uid
        and c.get("status") == "scheduled"
    )
    my_pending = sum(
        1 for c in data["candidates"].values()
        if c.get("hr_id") == uid and c.get("status") == "approved_pending"
    )

    status_lines = []
    if my_today:
        status_lines.append(f"📋 СОБЕСЕДОВАНИЙ сегодня: <b>{my_today}</b>")
    if my_pending:
        status_lines.append(f"✉️ Ждут твоего письма: <b>{my_pending}</b>")
    status_block = "\n".join(status_lines) + "\n\n" if status_lines else ""

    # Кнопка HR-дашборда
    webapp_kb = None
    if WEBAPP_URL:
        webapp_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📱 HR-панель", web_app=WebAppInfo(url=WEBAPP_URL + "/hr"))
        ]])

    await update.message.reply_text(
        f"👩‍💼 <b>Панель HR — BECKER</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Привет, <b>{hr_name(uid)}</b>!\n\n"
        f"{status_block}"
        f"Кнопки меню внизу экрана 👇",
        reply_markup=HR_KEYBOARD,
        parse_mode="HTML"
    )
    if webapp_kb:
        await update.message.reply_text(
            "Посмотреть приложение глазами кандидата:",
            reply_markup=webapp_kb
        )

# ── Обработка кнопок HR ───────────────────────────────────────────────────────
async def hr_keyboard_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_hr(update.effective_user.id):
        return
    text = update.message.text
    if   text == "📅 Расписание": await slots_cmd(update, ctx)
    elif text == "👥 Кандидаты":  await list_cmd(update, ctx)
    elif text == "📊 Статистика":  await stats_cmd(update, ctx)
    elif text == "👁 Превью бота": await preview_cmd(update, ctx)
    elif text == "❓ Помощь":
        await update.message.reply_text(
            "📖 <b>Справка по боту BECKER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📅 <b>Расписание</b>\n"
            "Выстави свои слоты на неделю: нажми на день → отметь время → «Сохранить».\n"
            "Кнопка ⚡ заполняет 11:00–17:30 одним нажатием.\n\n"
            "👥 <b>Кандидаты</b>\n"
            "Твои кандидаты с датой и статусом:\n"
            "📅 записан  ·  ✅ одобрен  ·  ❌ отказ  ·  👻 не пришёл\n\n"
            "🕘 <b>Автоматика</b>\n"
            "09:00 — карточки по твоим СОБЕСЕДОВАНИЯМ на сегодня\n"
            "17:00 — напоминание твоим кандидатам накануне\n"
            "18:00 — список одобренных + авто-отказы\n\n"
            "👁 <b>Превью</b> — все сообщения бота глазами кандидата.\n\n"
            f"Вопросы: 💬 {HR_TELEGRAM}",
            parse_mode="HTML"
        )

# ── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_hr(update.effective_user.id):
        await menu_cmd(update, ctx)
        return ConversationHandler.END
    if WEBAPP_URL:
        # Кандидат использует мини-приложение
        await update.message.reply_photo(
            photo="https://static.tildacdn.com/tild3061-6264-4033-b339-386633363065/Group_9104.png",
            caption=(
                f"Привет! Я <b>Софья</b>, HR кухонной фабрики <b>BECKER</b>.\n\n"
                "Нажми кнопку ниже, чтобы записаться на собеседование 👇\n\n"
                f"Или напиши напрямую: {HR_TELEGRAM}"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📱 Записаться на собеседование", web_app=WebAppInfo(url=WEBAPP_URL))
            ]])
        )
        return ConversationHandler.END

    # Текстовый режим (без WebApp)
    await update.message.reply_photo(
        photo="https://static.tildacdn.com/tild3061-6264-4033-b339-386633363065/Group_9104.png",
        caption=(
            f"Привет! Я <b>Софья</b>, HR кухонной фабрики <b>BECKER</b>.\n\n"
            "Мы делаем кухни премиум-класса — 26 лет опыта, немецкое качество, свой завод в Москве. "
            "Ищем людей в наш дружный и яркий коллектив.\n\n"
            "Через бот можно записаться — всего четыре шага:\n"
            "1. Напиши имя и фамилию\n2. Выбери направление\n"
            "3. Выбери день\n4. Выбери время\n\n"
            f"Или напиши напрямую: {HR_TELEGRAM}"
        ),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        "Как тебя зовут? <i>(Имя и фамилия)</i>",
        parse_mode="HTML"
    )
    return NAME

async def get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = update.message.text
    first = update.message.text.split()[0]
    await update.message.reply_text(
        f"<b>{first}</b>, приятно познакомиться! 👋\n\n"
        f"На какую роль рассматриваешь себя?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💼  Продажи",  callback_data="spec_Продажи")],
            [InlineKeyboardButton("🔧  Другое",   callback_data="spec_Другое")],
        ]),
        parse_mode="HTML"
    )
    return PICK_SPEC

async def pick_spec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    spec = q.data.replace("spec_", "")
    ctx.user_data["spec"] = spec
    first = ctx.user_data.get("name", "").split()[0]

    if spec == "Продажи":
        # Уточняем формат — от него зависит к кому попадёт кандидат
        await q.edit_message_text(
            f"<b>Продажи</b> — отлично, {first}! Какой формат работы тебе подходит?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏢  В офисе",    callback_data="format_офис")],
                [InlineKeyboardButton("🚗  Разъездной", callback_data="format_разъезд")],
            ]),
            parse_mode="HTML"
        )
        return PICK_FORMAT

    # «Другое» (администраторы, конструкторы и т.д.) — общие слоты обоих HR
    ctx.user_data["forced_hr"] = None
    data = load()
    today = date.today()
    buttons = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        all_free = get_all_free_slots(data, d_str)
        if all_free:
            label = d.strftime("%d %b, %a") + f"  ({len(all_free)} мест)"
            buttons.append([InlineKeyboardButton(label, callback_data=f"date_{d_str}")])

    if not buttons:
        await q.edit_message_text(
            f"<b>{first}</b>, записал направление: <b>{spec}</b>.\n\n"
            f"Сейчас свободных слотов нет — напиши напрямую:\n"
            f"{HR_PHONE}  ·  {HR_TELEGRAM}",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await q.edit_message_text(
        f"<b>Другое</b> — отлично! Выбери удобный день для СОБЕСЕДОВАНИЯ:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )
    return PICK_DATE


async def pick_format(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Выбор формата Продажи: Офис → Софья, Разъезд → Юлия."""
    q = update.callback_query
    await q.answer()
    fmt = q.data.replace("format_", "")
    first = ctx.user_data.get("name", "").split()[0]

    if fmt == "офис":
        forced_hr = HR_SONYA
        ctx.user_data["spec"] = "Продажи · Офис"
        fmt_label = "в офисе"
    else:
        forced_hr = HR_YULIA
        ctx.user_data["spec"] = "Продажи · Разъезд"
        fmt_label = "разъездной"
    ctx.user_data["forced_hr"] = forced_hr

    data = load()
    today = date.today()
    buttons = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        free = get_free_slots(data, d_str, forced_hr)
        if free:
            label = d.strftime("%d %b, %a") + f"  ({len(free)} мест)"
            buttons.append([InlineKeyboardButton(label, callback_data=f"date_{d_str}")])

    if not buttons:
        await q.edit_message_text(
            f"<b>{first}</b>, записал: <b>Продажи · {fmt_label}</b>.\n\n"
            f"Сейчас свободных слотов нет — напиши напрямую:\n"
            f"{HR_PHONE}  ·  {HR_TELEGRAM}",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await q.edit_message_text(
        f"Формат: <b>{fmt_label}</b>. Выбери удобный день для СОБЕСЕДОВАНИЯ:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )
    return PICK_DATE

async def pick_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chosen_date = q.data.replace("date_", "")
    ctx.user_data["interview_date"] = chosen_date

    data = load()
    forced_hr = ctx.user_data.get("forced_hr")

    if forced_hr:
        # Продажи: только слоты назначенного HR
        times = get_free_slots(data, chosen_date, forced_hr)
        buttons = [[InlineKeyboardButton(t, callback_data=f"time_{t}_{forced_hr}")] for t in times]
    else:
        # Другое: объединённые слоты обоих HR, дедупликация по времени
        all_free = get_all_free_slots(data, chosen_date)
        seen_times = set()
        buttons = []
        for (t, hr_id) in all_free:
            if t not in seen_times:
                seen_times.add(t)
                buttons.append([InlineKeyboardButton(t, callback_data=f"time_{t}_{hr_id}")])

    d = datetime.strptime(chosen_date, "%Y-%m-%d")
    await q.edit_message_text(
        f"Выбери удобное <b>время</b> — {d.strftime('%-d %B')}:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )
    return PICK_TIME

async def pick_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # callback_data = "time_{time}_{hr_id}"
    parts = q.data.split("_", 2)   # ["time", "14:00", "859413090"]
    chosen_time = parts[1]
    booked_hr_id = int(parts[2]) if len(parts) > 2 else HR_ID
    ctx.user_data["interview_time"] = chosen_time
    user = q.from_user
    d = ctx.user_data

    data = load()
    spec = d.get("spec", "—")
    # «Другое» — общие кандидаты, видны обоим HR
    is_shared = (spec == "Другое")

    data["candidates"][str(user.id)] = {
        "name":           d["name"],
        "spec":           spec,
        "telegram_id":    user.id,
        "username":       user.username or "",
        "interview_date": d["interview_date"],
        "interview_time": chosen_time,
        "hr_id":          booked_hr_id,   # чей слот физически занят
        "shared":         is_shared,      # True → видят оба HR
        "status":         "scheduled",
        "created_at":     datetime.now().isoformat()
    }
    save(data)

    interview_dt = datetime.strptime(d["interview_date"], "%Y-%m-%d")
    date_str = interview_dt.strftime("%-d %B")

    await q.edit_message_text(
        f"Отлично, записали!\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>{date_str}  ·  {chosen_time}</b>\n"
        f"Направление: {spec}\n"
        f"{COMPANY_ADDR}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"В день СОБЕСЕДОВАНИЯ придёт напоминание. Если нужно что-то изменить — кнопки ниже.\n"
        f"Или напиши напрямую: {HR_TELEGRAM}",
        parse_mode="HTML"
    )
    await q.message.reply_text(
        "Управление записью:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Перенести время",   callback_data="resch_start")],
            [InlineKeyboardButton("Изменились планы",  callback_data="changed_plans")],
        ])
    )

    # Уведомление: «Другое» → обоим HR; «Продажи» → только тому, чей слот
    shared_tag = "  <i>(общий кандидат)</i>" if is_shared else ""
    summary = (
        f"🆕 <b>Новая запись на СОБЕСЕДОВАНИЕ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤  <b>{d['name']}</b>\n"
        f"💼  {spec}{shared_tag}\n"
        f"📱  @{user.username or '—'}  (ID: {user.id})\n"
        f"📅  <b>{date_str}  ·  {chosen_time}</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    if is_shared:
        for hid in HR_IDS:
            await ctx.bot.send_message(chat_id=hid, text=summary, parse_mode="HTML")
    else:
        await ctx.bot.send_message(chat_id=booked_hr_id, text=summary, parse_mode="HTML")

    # Если запись на СЕГОДНЯ — ставим напоминание кандидату за 2 часа до
    today_str = date.today().strftime("%Y-%m-%d")
    if d["interview_date"] == today_str:
        interview_full_dt = datetime.strptime(f"{d['interview_date']} {chosen_time}", "%Y-%m-%d %H:%M")
        remind_dt = interview_full_dt - timedelta(hours=2)
        now = datetime.now()
        if remind_dt > now:
            delay = int((remind_dt - now).total_seconds())
            ctx.job_queue.run_once(
                send_2h_reminder,
                when=delay,
                data={
                    "user_id":  user.id,
                    "name":     d["name"],
                    "time":     chosen_time,
                }
            )

    return ConversationHandler.END

# ── Напоминание за 2 часа (для записей на сегодня) ───────────────────────────
async def send_2h_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    job_data = ctx.job.data
    first = job_data["name"].split()[0]
    await ctx.bot.send_message(
        chat_id=job_data["user_id"],
        text=f"{first}, напоминаем!\n"
             f"━━━━━━━━━━━━━━━━━━\n"
             f"Через 2 часа — в <b>{job_data['time']}</b> — ждём тебя в BECKER.\n"
             f"{COMPANY_ADDR}\n"
             f"━━━━━━━━━━━━━━━━━━\n"
             f"Всё в силе?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Да, приду",  callback_data=f"cand_confirm_{job_data['user_id']}"),
            InlineKeyboardButton("Не смогу",   callback_data=f"cand_decline_{job_data['user_id']}")
        ]]),
        parse_mode="HTML"
    )

# ── 9:00 — карточки HR + утреннее напоминание кандидатам ─────────────────────
async def daily_check(ctx: ContextTypes.DEFAULT_TYPE):
    today_str = date.today().strftime("%Y-%m-%d")
    data = load()

    # Утреннее напоминание кандидатам с СОБЕСЕДОВАНИЕМ сегодня
    # (только тем, кто записался заранее — не сегодня, иначе будет 2h-reminder)
    all_today = [
        c for c in data["candidates"].values()
        if c.get("interview_date") == today_str and c.get("status") == "scheduled"
    ]
    for c in all_today:
        # Если запись создана сегодня — её покроет 2h-reminder, пропускаем
        created = c.get("created_at", "")
        created_date = created[:10] if created else ""
        if created_date == today_str:
            continue
        first = c["name"].split()[0]
        await ctx.bot.send_message(
            chat_id=c["telegram_id"],
            text=f"{first}, доброе утро!\n"
                 f"━━━━━━━━━━━━━━━━━━\n"
                 f"Сегодня в <b>{c['interview_time']}</b> ждём тебя в BECKER.\n"
                 f"{COMPANY_ADDR}\n"
                 f"━━━━━━━━━━━━━━━━━━\n"
                 f"Всё в силе?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Да, приду",  callback_data=f"cand_confirm_{c['telegram_id']}"),
                InlineKeyboardButton("Не смогу",   callback_data=f"cand_decline_{c['telegram_id']}")
            ]]),
            parse_mode="HTML"
        )

    # Карточки HR — только свои кандидаты
    for hr_id in HR_IDS:
        my_today = [
            c for c in data["candidates"].values()
            if c.get("interview_date") == today_str
            and c.get("hr_id") == hr_id
            and c.get("status") == "scheduled"
        ]
        for c in my_today:
            confirmed = c.get("confirmed")
            confirm_label = "✅ Подтвердил(а)" if confirmed is True else ("❌ Отказал(ась) вчера" if confirmed is False else "❓ Не отвечал(а)")
            spec_line = f"💼  {c['spec']}\n" if c.get("spec") and c["spec"] != "—" else ""
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ СОБЕСЕДОВАНИЕ было",  callback_data=f"hr_met_{c['telegram_id']}"),
                 InlineKeyboardButton("👻 Не пришёл(а)",        callback_data=f"hr_noshow_{c['telegram_id']}")],
            ])
            await ctx.bot.send_message(
                chat_id=hr_id,
                text=f"📋 <b>СОБЕСЕДОВАНИЕ в {c['interview_time']}</b>\n"
                     f"━━━━━━━━━━━━━━━━━━\n"
                     f"👤  <b>{c['name']}</b>  |  @{c.get('username') or '—'}\n"
                     f"{spec_line}"
                     f"Подтверждение: {confirm_label}\n"
                     f"━━━━━━━━━━━━━━━━━━\n"
                     f"Как прошло?",
                reply_markup=kb,
                parse_mode="HTML"
            )

# ── Кнопки HR (после СОБЕСЕДОВАНИЯ) ──────────────────────────────────────────
async def hr_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_hr(q.from_user.id):
        return

    parts = q.data.split("_")
    action = parts[1]
    cand_id = parts[2] if len(parts) > 2 else None

    data = load()
    cand = data["candidates"].get(str(cand_id)) if cand_id else None

    if action == "met" and cand:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Берём",  callback_data=f"hr_approved_{cand_id}"),
            InlineKeyboardButton("👎 Отказ",  callback_data=f"hr_rejected_{cand_id}")
        ]])
        await q.edit_message_text(
            f"👤 <b>{cand['name']}</b> — СОБЕСЕДОВАНИЕ прошло.\n\nКакой результат?",
            reply_markup=kb, parse_mode="HTML"
        )

    elif action == "noshow" and cand:
        cand["status"] = "no_show"
        save(data)
        await q.edit_message_text(
            f"👻 <b>{cand['name']}</b> — отмечен(а) как не пришедший(ая).",
            parse_mode="HTML"
        )
        first = cand["name"].split()[0]
        await ctx.bot.send_message(
            chat_id=int(cand_id),
            text=f"{first}, сегодня ждали тебя на СОБЕСЕДОВАНИЕ — что-то пошло не так?\n\n"
                 f"Вакансия открыта — можем перенести:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Да, перенесём",  callback_data="reschedule_yes"),
                InlineKeyboardButton("Нет, спасибо",   callback_data="reschedule_no")
            ]]),
            parse_mode="HTML"
        )

    elif action == "approved" and cand:
        cand["status"] = "approved_pending"
        save(data)
        await q.edit_message_text(
            f"✅ <b>{cand['name']}</b> — одобрен(а)!\nВ 18:00 придёт напоминание написать кандидату.",
            parse_mode="HTML"
        )
        first = cand["name"].split()[0]
        await ctx.bot.send_message(
            chat_id=int(cand_id),
            text=f"{first}, спасибо, что нашёл(ла) время!\n\n"
                 f"Рады были познакомиться. Наш HR напишет тебе <b>завтра до обеда</b>.\n\n"
                 f"Если есть вопросы — {HR_TELEGRAM}",
            parse_mode="HTML"
        )

    elif action == "rejected" and cand:
        cand["status"] = "rejected_pending"
        save(data)
        await q.edit_message_text(
            f"👎 <b>{cand['name']}</b> — отказ уйдёт кандидату автоматически в 18:00.",
            parse_mode="HTML"
        )
        first = cand["name"].split()[0]
        await ctx.bot.send_message(
            chat_id=int(cand_id),
            text=f"{first}, спасибо, что нашёл(ла) время!\n\n"
                 f"Рады были познакомиться. Наш HR напишет тебе <b>завтра до обеда</b>.\n\n"
                 f"Если есть вопросы — {HR_TELEGRAM}",
            parse_mode="HTML"
        )
        ctx.job_queue.run_once(
            send_final_rejection,
            when=_delay_to_18(),
            data={"user_id": int(cand_id), "name": cand["name"]}
        )

# ── Ответ кандидата на «хотите перенести?» ────────────────────────────────────
async def reschedule_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = load()
    cand = data["candidates"].get(str(q.from_user.id))
    booked_hr = cand.get("hr_id", HR_ID) if cand else HR_ID

    if q.data == "reschedule_yes":
        await q.edit_message_text(
            f"Хорошо! Свяжись с нами — подберём удобное время:\n"
            f"📱 {HR_PHONE}\n💬 {HR_TELEGRAM}"
        )
        cand_username = q.from_user.username or str(q.from_user.id)
        await ctx.bot.send_message(
            chat_id=booked_hr,
            text=f"🔄 @{cand_username} хочет перенести СОБЕСЕДОВАНИЕ."
        )
    else:
        await q.edit_message_text("Понятно, спасибо за ответ! Удачи в поиске работы 🙏")

# ── Время ─────────────────────────────────────────────────────────────────────
def _delay_to_18() -> int:
    now = datetime.now()
    target = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return int((target - now).total_seconds())

# ── 18:00 — напоминание HR написать одобренным ───────────────────────────────
async def daily_18_check(ctx: ContextTypes.DEFAULT_TYPE):
    data = load()
    # Каждый HR получает только своих
    for hr_id in HR_IDS:
        approved = [
            c for c in data["candidates"].values()
            if c.get("status") == "approved_pending" and c.get("hr_id") == hr_id
        ]
        if not approved:
            continue
        lines = [
            f"⏰ <b>Напоминание — написать кандидатам</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Прошли СОБЕСЕДОВАНИЕ и ждут приглашения:\n"
        ]
        for c in approved:
            username = f"@{c['username']}" if c.get("username") else f"tg://user?id={c['telegram_id']}"
            spec_tag = f" · {c['spec']}" if c.get("spec") and c["spec"] != "—" else ""
            lines.append(f"✅  <b>{c['name']}</b>{spec_tag}\n     {username}")
        lines.append(
            f"\n━━━━━━━━━━━━━━━━━━\n"
            f"📅 Первый день обучения — ближайший <b>понедельник в 10:00</b>\n"
            f"📍 {COMPANY_ADDR}"
        )
        await ctx.bot.send_message(chat_id=hr_id, text="\n".join(lines), parse_mode="HTML")

async def send_final_rejection(ctx: ContextTypes.DEFAULT_TYPE):
    d = ctx.job.data
    first = d["name"].split()[0]
    await ctx.bot.send_message(
        chat_id=d["user_id"],
        text=f"{first}, спасибо, что пришёл(ла) и уделил(а) нам время.\n\n"
             f"По итогам встречи мы пока не готовы сделать предложение — "
             f"но если ситуация изменится, обязательно напишем.\n\n"
             f"Удачи в поиске!\n\n"
             f"<b>Софья, HR BECKER</b>  ·  {HR_TELEGRAM}",
        parse_mode="HTML"
    )

# ── 17:00 — напоминание кандидатам накануне ──────────────────────────────────
async def evening_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    tomorrow_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    data = load()
    for c in data["candidates"].values():
        if c.get("interview_date") == tomorrow_str and c.get("status") == "scheduled":
            first = c["name"].split()[0]
            await ctx.bot.send_message(
                chat_id=c["telegram_id"],
                text=f"{first}, напоминаем!\n"
                     f"━━━━━━━━━━━━━━━━━━\n"
                     f"Завтра в <b>{c['interview_time']}</b> ждём тебя в BECKER.\n"
                     f"{COMPANY_ADDR}\n"
                     f"━━━━━━━━━━━━━━━━━━\n"
                     f"Всё в силе?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Да, приду", callback_data=f"cand_confirm_{c['telegram_id']}"),
                    InlineKeyboardButton("Не смогу",  callback_data=f"cand_decline_{c['telegram_id']}")
                ]]),
                parse_mode="HTML"
            )

# ── Ответ кандидата на напоминание ────────────────────────────────────────────
async def candidate_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    action = parts[1]
    cand_id = parts[2]
    data = load()
    cand = data["candidates"].get(cand_id)
    if not cand:
        await q.edit_message_text("Не нашла твою запись. Свяжись с HR напрямую.")
        return
    first = cand["name"].split()[0]
    booked_hr = cand.get("hr_id", HR_ID)

    if action == "confirm":
        cand["confirmed"] = True
        save(data)
        await q.edit_message_text(
            f"Отлично, ждём!\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Завтра в <b>{cand['interview_time']}</b>\n"
            f"{COMPANY_ADDR}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Если что-то изменится — {HR_TELEGRAM}",
            parse_mode="HTML"
        )
        await ctx.bot.send_message(
            chat_id=booked_hr,
            text=f"✅ <b>{cand['name']}</b> подтвердил(а) визит\nЗавтра в {cand['interview_time']}",
            parse_mode="HTML"
        )
    else:
        cand["confirmed"] = False
        save(data)
        await q.edit_message_text(
            f"Понятно, {first}. Если захочешь перенести — пиши:\n{HR_PHONE}  ·  {HR_TELEGRAM}"
        )
        await ctx.bot.send_message(
            chat_id=booked_hr,
            text=f"⚠️ <b>{cand['name']}</b> не придёт\n"
                 f"📅 {cand['interview_date']} в {cand['interview_time']}\n"
                 f"@{cand.get('username') or '—'}",
            parse_mode="HTML"
        )

# ── Изменились планы у кандидата ──────────────────────────────────────────────
async def changed_plans_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "Понятно! Что случилось?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Хочу перенести", callback_data="cp_reschedule")],
            [InlineKeyboardButton("🤔 Передумал(а)",   callback_data="cp_changed_mind")],
        ])
    )

async def changed_plans_choice_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    data = load()
    cand = data["candidates"].get(str(user.id))
    first = cand["name"].split()[0] if cand else ""
    username = f"@{cand.get('username')}" if cand and cand.get("username") else str(user.id)
    booked_hr = cand.get("hr_id", HR_ID) if cand else HR_ID

    if q.data == "cp_reschedule":
        today = date.today()
        buttons = []
        for i in range(1, 8):
            d = today + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            all_free = get_all_free_slots(data, d_str)
            # Убираем текущий слот если это тот же день/время
            if cand and cand.get("interview_date") == d_str:
                all_free = [(t, h) for (t, h) in all_free if not (t == cand["interview_time"] and h == cand.get("hr_id"))]
            if all_free:
                label = d.strftime("%-d %b, %A") + f"  ({len(all_free)} мест)"
                buttons.append([InlineKeyboardButton(label, callback_data=f"resch_date_{d_str}")])
        if not buttons:
            await q.edit_message_text(
                f"Сейчас нет свободных слотов 😔\n\nСвяжись напрямую:\n📱 {HR_PHONE} | 💬 {HR_TELEGRAM}"
            )
            return
        old_dt = datetime.strptime(cand["interview_date"], "%Y-%m-%d") if cand else None
        header = f"Текущая запись: <b>{old_dt.strftime('%-d %B')} в {cand['interview_time']}</b>\n\n" if old_dt else ""
        await q.edit_message_text(
            f"{header}Выбери новый день:",
            reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML"
        )

    elif q.data == "cp_changed_mind":
        await q.edit_message_text(
            f"Окей, {first}, понятно! 🙏\n\nЕсли передумаешь — пиши:\n📱 {HR_PHONE}  |  💬 {HR_TELEGRAM}"
        )
        if cand:
            await ctx.bot.send_message(
                chat_id=booked_hr,
                text=f"🤔 <b>{cand['name']}</b> передумал(а)\n"
                     f"📅 Была запись: {cand['interview_date']} в {cand['interview_time']}\n{username}",
                parse_mode="HTML"
            )

    elif q.data == "cp_not_relevant":
        await q.edit_message_text(
            f"Понятно, {first}! Удачи в поиске 🙏\n\nЕсли что изменится:\n📱 {HR_PHONE} | 💬 {HR_TELEGRAM}"
        )
        if cand:
            await ctx.bot.send_message(
                chat_id=booked_hr,
                text=f"❌ <b>{cand['name']} — вакансия не актуальна</b>\n"
                     f"📅 Была запись: {cand['interview_date']} в {cand['interview_time']}\n{username}",
                parse_mode="HTML"
            )

# ── /week ─────────────────────────────────────────────────────────────────────
async def week_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_hr(update.effective_user.id):
        return
    uid = update.effective_user.id
    data = load()
    today = date.today()

    lines = [f"📅 <b>Расписание {hr_name(uid)} на 7 дней:</b>\n"]
    day_buttons = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        slots = _hr_slots(data, uid).get(d_str, [])
        day_label = d.strftime("%-d %B, %A")
        if slots:
            lines.append(f"✅ <b>{day_label}</b>: {', '.join(slots)}")
            mark = "✅"
        else:
            lines.append(f"◻️ {day_label}: не задано")
            mark = "◻️"
        day_buttons.append([InlineKeyboardButton(
            f"{mark} {d.strftime('%-d %b')} — изменить",
            callback_data=f"editday_{d_str}"
        )])

    lines.append("\nНажми кнопку ниже чтобы быстро заполнить всё:")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Заполнить всю неделю (11:00–17:00)", callback_data="week_fill_all")],
        [InlineKeyboardButton("🗑 Очистить всю неделю",                callback_data="week_clear_all")],
    ] + day_buttons)

    await update.message.reply_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")

async def week_action_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not is_hr(uid):
        return
    data = load()
    today = date.today()
    hr_s = _hr_slots(data, uid)

    if q.data == "week_fill_all":
        for i in range(1, 8):
            d_str = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            hr_s[d_str] = DEFAULT_SLOTS.copy()
        save(data)
        lines = ["✅ <b>Стандартное расписание на всю неделю:</b>\n"]
        for i in range(1, 8):
            d = today + timedelta(days=i)
            lines.append(f"📅 {d.strftime('%-d %B, %A')}: {', '.join(DEFAULT_SLOTS)}")
        await q.edit_message_text("\n".join(lines), parse_mode="HTML")
    elif q.data == "week_clear_all":
        for i in range(1, 8):
            d_str = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            hr_s[d_str] = []
        save(data)
        await q.edit_message_text("🗑 Расписание на неделю очищено.")

# ── Перенос кандидата ─────────────────────────────────────────────────────────
async def resch_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    data = load()
    cand = data["candidates"].get(str(user.id))
    if not cand:
        await q.edit_message_text(f"Не нашла запись 😔\n📱 {HR_PHONE} | 💬 {HR_TELEGRAM}")
        return

    today = date.today()
    buttons = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        all_free = get_all_free_slots(data, d_str)
        if cand.get("interview_date") == d_str:
            all_free = [(t, h) for (t, h) in all_free if not (t == cand["interview_time"] and h == cand.get("hr_id"))]
        if all_free:
            label = d.strftime("%-d %b, %A") + f"  ({len(all_free)} мест)"
            buttons.append([InlineKeyboardButton(label, callback_data=f"resch_date_{d_str}")])

    if not buttons:
        await q.edit_message_text(f"Нет свободных слотов 😔\n📱 {HR_PHONE} | 💬 {HR_TELEGRAM}")
        return

    old_dt = datetime.strptime(cand["interview_date"], "%Y-%m-%d")
    await q.edit_message_text(
        f"Текущая запись: <b>{old_dt.strftime('%-d %B')} в {cand['interview_time']}</b>\n\nВыбери новый день:",
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML"
    )

async def resch_date_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    day_str = q.data.replace("resch_date_", "")
    data = load()
    user = q.from_user
    cand = data["candidates"].get(str(user.id))

    all_free = get_all_free_slots(data, day_str)
    if cand and cand.get("interview_date") == day_str:
        all_free = [(t, h) for (t, h) in all_free if not (t == cand["interview_time"] and h == cand.get("hr_id"))]

    seen_times = set()
    buttons = []
    for (t, hr_id) in all_free:
        if t not in seen_times:
            seen_times.add(t)
            buttons.append([InlineKeyboardButton(t, callback_data=f"resch_time_{day_str}_{t}_{hr_id}")])

    d = datetime.strptime(day_str, "%Y-%m-%d")
    await q.edit_message_text(
        f"Выбери время — <b>{d.strftime('%-d %B')}</b>:",
        reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML"
    )

async def resch_time_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # callback_data = "resch_time_{day_str}_{time}_{hr_id}"
    parts = q.data.split("_", 4)   # ["resch", "time", date, time, hr_id]
    day_str  = parts[2]
    new_time = parts[3]
    new_hr   = int(parts[4]) if len(parts) > 4 else HR_ID

    user = q.from_user
    data = load()
    cand = data["candidates"].get(str(user.id))
    if not cand:
        await q.edit_message_text("Запись не найдена.")
        return

    old_date = cand["interview_date"]
    old_time = cand["interview_time"]
    old_hr   = cand.get("hr_id", HR_ID)

    cand["interview_date"] = day_str
    cand["interview_time"] = new_time
    cand["hr_id"]          = new_hr
    cand["confirmed"]      = None
    save(data)

    new_dt = datetime.strptime(day_str, "%Y-%m-%d")
    old_dt = datetime.strptime(old_date, "%Y-%m-%d")
    first  = cand["name"].split()[0]

    await q.edit_message_text(
        f"✅ <b>Перенос оформлен, {first}!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅  <b>{new_dt.strftime('%-d %B')}  ·  {new_time}</b>\n"
        f"📍  {COMPANY_ADDR}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📱 {HR_PHONE}  |  💬 {HR_TELEGRAM}",
        parse_mode="HTML"
    )
    notify_text = (
        f"🔄 <b>Перенос СОБЕСЕДОВАНИЯ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤  <b>{cand['name']}</b>  |  @{cand.get('username') or user.id}\n"
        f"Было:   {old_dt.strftime('%-d %B')}  ·  {old_time}\n"
        f"Стало:  <b>{new_dt.strftime('%-d %B')}  ·  {new_time}</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    # Уведомить обоих HR если HR поменялся, иначе только нового
    await ctx.bot.send_message(chat_id=new_hr, text=notify_text, parse_mode="HTML")
    if old_hr != new_hr:
        await ctx.bot.send_message(chat_id=old_hr, text=notify_text, parse_mode="HTML")

# ── /slots — расписание конкретного HR ───────────────────────────────────────
def _slots_week_keyboard(data, hr_id: int):
    today = date.today()
    hr_s = _hr_slots(data, hr_id)
    buttons = []
    for i in range(0, 7):
        d = today + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        slots = hr_s.get(d_str, [])
        mark = "✅" if slots else "◻️"
        label = f"{mark} {d.strftime('%-d %b, %A')}  ({len(slots)} сл.)" if slots else f"{mark} {d.strftime('%-d %b, %A')}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"editday_{d_str}")])
    return InlineKeyboardMarkup(buttons)

def _day_slots_keyboard(data, day_str, hr_id: int):
    current = _hr_slots(data, hr_id).get(day_str, [])
    buttons = []
    row = []
    for t in DEFAULT_SLOTS:
        mark = "✅" if t in current else "◻️"
        row.append(InlineKeyboardButton(f"{mark} {t}", callback_data=f"toggleslot_{day_str}_{t}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⚡ Стандартное (11:00–17:30)", callback_data=f"fillday_{day_str}"),
        InlineKeyboardButton("🗑 Очистить",                  callback_data=f"clearday_{day_str}"),
    ])
    buttons.append([InlineKeyboardButton("💾 Сохранить и вернуться", callback_data=f"saveslots_{day_str}")])
    return InlineKeyboardMarkup(buttons)

async def slots_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_hr(uid):
        return
    data = load()
    await update.message.reply_text(
        f"📅 <b>Моё расписание на неделю</b>\n\n"
        f"Нажми на день чтобы выбрать время.\n✅ — есть слоты  ◻️ — пусто",
        reply_markup=_slots_week_keyboard(data, uid),
        parse_mode="HTML"
    )

async def edit_day_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    day_str = q.data.replace("editday_", "")
    data = load()
    d = datetime.strptime(day_str, "%Y-%m-%d")
    slots = _hr_slots(data, uid).get(day_str, [])
    selected = ', '.join(slots) if slots else "нет"
    await q.edit_message_text(
        f"⏰ <b>{d.strftime('%-d %B, %A')}</b>\n\nОтмечено: {selected}\n\nНажми на время чтобы включить / выключить:",
        reply_markup=_day_slots_keyboard(data, day_str, uid), parse_mode="HTML"
    )

async def toggle_slot_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, day_str, t = q.data.split("_", 2)
    data = load()
    hr_s = _hr_slots(data, uid)
    slots = hr_s.get(day_str, [])
    if t in slots:
        slots.remove(t)
    else:
        slots.append(t)
        slots.sort()
    hr_s[day_str] = slots
    save(data)
    d = datetime.strptime(day_str, "%Y-%m-%d")
    selected = ', '.join(slots) if slots else "нет"
    await q.edit_message_text(
        f"⏰ <b>{d.strftime('%-d %B, %A')}</b>\n\nОтмечено: {selected}\n\nНажми на время чтобы включить / выключить:",
        reply_markup=_day_slots_keyboard(data, day_str, uid), parse_mode="HTML"
    )

async def fillday_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    day_str = q.data.replace("fillday_", "")
    data = load()
    _hr_slots(data, uid)[day_str] = DEFAULT_SLOTS.copy()
    save(data)
    d = datetime.strptime(day_str, "%Y-%m-%d")
    await q.edit_message_text(
        f"⏰ <b>{d.strftime('%-d %B, %A')}</b>\n\nОтмечено: {', '.join(DEFAULT_SLOTS)}\n\nНажми на время чтобы включить / выключить:",
        reply_markup=_day_slots_keyboard(data, day_str, uid), parse_mode="HTML"
    )

async def clearday_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    day_str = q.data.replace("clearday_", "")
    data = load()
    _hr_slots(data, uid)[day_str] = []
    save(data)
    d = datetime.strptime(day_str, "%Y-%m-%d")
    await q.edit_message_text(
        f"⏰ <b>{d.strftime('%-d %B, %A')}</b>\n\nОтмечено: нет\n\nНажми на время чтобы включить / выключить:",
        reply_markup=_day_slots_keyboard(data, day_str, uid), parse_mode="HTML"
    )

async def save_slots_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    day_str = q.data.replace("saveslots_", "")
    data = load()
    slots = _hr_slots(data, uid).get(day_str, [])
    d = datetime.strptime(day_str, "%Y-%m-%d")
    await q.edit_message_text(
        f"✅ <b>{d.strftime('%-d %B')}</b> сохранено: {', '.join(slots) if slots else 'нет'}\n\n"
        f"📅 <b>Расписание на неделю</b>\nВыбери следующий день или закрой:",
        reply_markup=_slots_week_keyboard(data, uid), parse_mode="HTML"
    )

# ── /preview ──────────────────────────────────────────────────────────────────
async def preview_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_hr(update.effective_user.id):
        return
    bot = ctx.bot
    cid = update.effective_chat.id

    async def sep(title=""):
        txt = f"<b>— {title} —</b>" if title else "<b>—————————————</b>"
        await bot.send_message(cid, txt, parse_mode="HTML")

    async def hr(text):
        await bot.send_message(cid, f"👩‍💼 <b>ВЫ (HR) видите:</b>\n\n{text}", parse_mode="HTML")

    async def cand(text, kb=None):
        await bot.send_message(cid, f"🧑 <b>Кандидат видит:</b>\n\n{text}", reply_markup=kb, parse_mode="HTML")

    await sep("ПРЕВЬЮ БОТА — BECKER")
    await sep("Шаг 1 — приветствие")
    await cand(
        f"Привет! Я <b>Софья</b>, HR кухонной фабрики <b>BECKER</b>.\n\n"
        f"Мы делаем кухни премиум-класса — 26 лет опыта, немецкое качество, свой завод в Москве. "
        f"Ищем людей в наш дружный и яркий коллектив.\n\n"
        f"Через этот бот можно записаться на СОБЕСЕДОВАНИЕ — всего четыре шага:\n"
        f"1. Напиши имя и фамилию\n2. Выбери направление\n3. Выбери день\n4. Выбери время\n\n"
        f"Или напиши мне напрямую: {HR_TELEGRAM}"
    )
    await sep("Шаг 2 — выбор специализации")
    await cand(
        f"<b>Иван</b>, приятно познакомиться! 👋\n\nНа какую роль рассматриваешь себя?",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("💼  Продажи",  callback_data="preview_noop")],
            [InlineKeyboardButton("🔧  Другое",   callback_data="preview_noop")],
        ])
    )
    await sep("Нет слотов")
    await cand(f"<b>Иван</b>, записал направление: <b>Продажи</b>.\n\nСейчас свободных слотов нет — напиши напрямую:\n{HR_PHONE}  ·  {HR_TELEGRAM}")
    await sep("Успешная запись")
    await cand(
        f"Отлично, записали!\n━━━━━━━━━━━━━━━━━━\n"
        f"<b>28 июня  ·  14:00</b>\nНаправление: Продажи\n{COMPANY_ADDR}\n━━━━━━━━━━━━━━━━━━\n"
        f"Накануне придёт напоминание.\nИли напиши напрямую: {HR_TELEGRAM}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("Перенести время",   callback_data="preview_noop")],
            [InlineKeyboardButton("Изменились планы",  callback_data="preview_noop")],
        ])
    )
    await hr(
        f"🆕 <b>Новая запись на СОБЕСЕДОВАНИЕ</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"👤  <b>Иван Иванов</b>\n💼  Продажи\n📱  @test_user  (ID: 123456)\n"
        f"📅  <b>28 июня  ·  14:00</b>\n━━━━━━━━━━━━━━━━━━"
    )
    await sep("Накануне (17:00)")
    await cand(
        f"Иван, напоминаем!\n━━━━━━━━━━━━━━━━━━\n"
        f"Завтра в <b>14:00</b> ждём тебя в BECKER.\n{COMPANY_ADDR}\n━━━━━━━━━━━━━━━━━━\nВсё в силе?",
        InlineKeyboardMarkup([[
            InlineKeyboardButton("Да, приду",  callback_data="preview_noop"),
            InlineKeyboardButton("Не смогу",   callback_data="preview_noop")
        ]])
    )
    await hr("✅ <b>Иван Иванов</b> подтвердил(а) визит\nЗавтра в 14:00")
    await sep("День СОБЕСЕДОВАНИЯ (9:00)")
    await hr(
        f"📋 <b>СОБЕСЕДОВАНИЕ в 14:00</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"👤  <b>Иван Иванов</b>  |  @test_user\n💼  Продажи\n"
        f"Подтверждение: ✅ Подтвердил(а)\n━━━━━━━━━━━━━━━━━━\nКак прошло?"
    )
    await sep("После СОБЕСЕДОВАНИЯ — ожидание")
    await cand(
        f"Иван, спасибо, что нашёл(ла) время!\n\n"
        f"Рады были познакомиться. Наш HR напишет тебе <b>завтра до обеда</b>.\n\nЕсли есть вопросы — {HR_TELEGRAM}"
    )
    await sep("18:00 — HR (если одобрен)")
    await hr(
        f"⏰ <b>Напоминание — написать кандидатам</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Прошли СОБЕСЕДОВАНИЕ и ждут приглашения:\n\n✅  <b>Иван Иванов</b> · Продажи\n     @test_user\n\n"
        f"━━━━━━━━━━━━━━━━━━\n📅 Первый день обучения — ближайший <b>понедельник в 10:00</b>\n📍 {COMPANY_ADDR}"
    )
    await sep("18:00 — кандидату (отказ, автоматически)")
    await cand(
        f"Иван, спасибо, что пришёл(ла) и уделил(а) нам время.\n\n"
        f"По итогам встречи мы пока не готовы сделать предложение — "
        f"но если ситуация изменится, обязательно напишем.\n\nУдачи в поиске!\n\n"
        f"<b>Софья, HR BECKER</b>  ·  {HR_TELEGRAM}"
    )
    await sep("ПРЕВЬЮ ЗАКОНЧЕНО ✅")

# ── 📊 Статистика (только свои кандидаты) ────────────────────────────────────
async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_hr(update.effective_user.id):
        return
    await update.message.reply_text(
        "📊 <b>Статистика СОБЕСЕДОВАНИЙ</b>\n\nВыбери период:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Сегодня",    callback_data="stats_today")],
            [InlineKeyboardButton("Эта неделя", callback_data="stats_week")],
            [InlineKeyboardButton("Этот месяц", callback_data="stats_month")],
            [InlineKeyboardButton("Всё время",  callback_data="stats_all")],
        ]),
        parse_mode="HTML"
    )

async def stats_period_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not is_hr(uid):
        return

    period = q.data.replace("stats_", "")
    data = load()
    today = date.today()

    if period == "today":
        label = "Сегодня"; from_date = today
    elif period == "week":
        label = "Эта неделя"; from_date = today - timedelta(days=today.weekday())
    elif period == "month":
        label = "Этот месяц"; from_date = today.replace(day=1)
    else:
        label = "Всё время"; from_date = date(2000, 1, 1)

    candidates = [
        c for c in data["candidates"].values()
        if c.get("interview_date")
        and date.fromisoformat(c["interview_date"]) >= from_date
        and (c.get("hr_id") == uid or c.get("shared"))
    ]
    candidates.sort(key=lambda x: x.get("interview_date", ""))

    STATUS_LABEL = {
        "scheduled":        "📅 Записан",
        "approved":         "✅ Принят",
        "approved_pending": "✅ Принят (ждёт письма)",
        "rejected":         "❌ Отказ",
        "rejected_pending": "❌ Отказ (авто)",
        "no_show":          "👻 Не пришёл",
    }
    total      = len(candidates)
    came       = sum(1 for c in candidates if c.get("status") in ("approved", "approved_pending", "rejected", "rejected_pending"))
    approved   = sum(1 for c in candidates if c.get("status") in ("approved", "approved_pending"))
    rejected   = sum(1 for c in candidates if c.get("status") in ("rejected", "rejected_pending"))
    no_show    = sum(1 for c in candidates if c.get("status") == "no_show")
    scheduled  = sum(1 for c in candidates if c.get("status") == "scheduled")
    conversion = f"{round(approved / came * 100)}%" if came else "—"

    lines = [
        f"📊 <b>Статистика СОБЕСЕДОВАНИЙ — {label}</b>",
        f"━━━━━━━━━━━━━━━━━━",
        f"Всего записей:   <b>{total}</b>",
        f"Пришли:          <b>{came}</b>",
        f"Приняты:         <b>{approved}</b>",
        f"Отказы:          <b>{rejected}</b>",
        f"Не пришли:       <b>{no_show}</b>",
        f"Ещё впереди:     <b>{scheduled}</b>",
        f"Конверсия:       <b>{conversion}</b>",
        f"━━━━━━━━━━━━━━━━━━",
    ]
    if not candidates:
        lines.append("За этот период у тебя записей нет.")
    else:
        for c in candidates:
            d_label = datetime.strptime(c["interview_date"], "%Y-%m-%d").strftime("%-d %b")
            status  = STATUS_LABEL.get(c.get("status", ""), "❓")
            contact = f"@{c['username']}" if c.get("username") else f"tg://user?id={c['telegram_id']}"
            spec_tag = f" · {c['spec']}" if c.get("spec") and c["spec"] != "—" else ""
            lines.append(f"\n<b>{c['name']}</b>{spec_tag}  ·  {d_label} {c.get('interview_time','')}\n{status}  ·  {contact}")

    await q.edit_message_text("\n".join(lines), parse_mode="HTML")

# ── /list — только свои кандидаты ────────────────────────────────────────────
async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_hr(uid):
        return
    data = load()
    # «Другое» — общие кандидаты, видны обоим HR
    my_cands = [c for c in data["candidates"].values()
                if c.get("hr_id") == uid or c.get("shared")]
    if not my_cands:
        await update.message.reply_text("Твоих кандидатов пока нет.")
        return
    status_emoji = {
        "scheduled": "📅", "approved": "✅", "rejected": "❌",
        "no_show": "👻", "approved_pending": "🔄", "rejected_pending": "🔄"
    }
    lines = []
    for c in sorted(my_cands, key=lambda x: x.get("interview_date", "")):
        e = status_emoji.get(c.get("status", ""), "❓")
        conf_tag = " ✔️" if c.get("confirmed") is True else (" ✖️" if c.get("confirmed") is False else "")
        spec_tag = f" [{c['spec']}]" if c.get("spec") and c["spec"] != "—" else ""
        lines.append(f"{e} {c['name']}{spec_tag} — {c.get('interview_date','?')} {c.get('interview_time','')}{conf_tag}")
    await update.message.reply_text("📋 <b>Мои кандидаты:</b>\n" + "\n".join(lines), parse_mode="HTML")

# ── Заглушка для кнопок превью ────────────────────────────────────────────────
async def noop_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Это превью — кнопки не активны", show_alert=False)

# ── Обработчик данных из мини-приложения ──────────────────────────────────────
async def webapp_data_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Кандидат отправил форму через мини-приложение."""
    raw = update.effective_message.web_app_data.data
    try:
        booking = json.loads(raw)
    except Exception:
        await update.message.reply_text("Ошибка обработки данных. Попробуй ещё раз.")
        return

    user       = update.effective_user
    name       = booking.get("name", "—")
    spec       = booking.get("spec", "—")
    day_str    = booking.get("date", "")
    time_str   = booking.get("time", "")
    hr_id_raw  = booking.get("hr_id")
    booked_hr  = int(hr_id_raw) if hr_id_raw else HR_ID
    is_shared  = (spec == "Другое")

    data = load()
    data["candidates"][str(user.id)] = {
        "name":           name,
        "spec":           spec,
        "telegram_id":    user.id,
        "username":       user.username or "",
        "interview_date": day_str,
        "interview_time": time_str,
        "hr_id":          booked_hr,
        "shared":         is_shared,
        "status":         "scheduled",
        "created_at":     datetime.now().isoformat()
    }
    save(data)

    try:
        interview_dt = datetime.strptime(day_str, "%Y-%m-%d")
        date_label   = interview_dt.strftime("%-d %B")
    except Exception:
        date_label = day_str

    await update.message.reply_text(
        f"✅ <b>Записали!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>{date_label}  ·  {time_str}</b>\n"
        f"Направление: {spec}\n"
        f"{COMPANY_ADDR}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Напоминание придёт накануне.\n{HR_TELEGRAM}",
        parse_mode="HTML"
    )

    summary = (
        f"🆕 <b>Новая запись (мини-приложение)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤  <b>{name}</b>\n"
        f"💼  {spec}\n"
        f"📱  @{user.username or '—'}  (ID: {user.id})\n"
        f"📅  <b>{date_label}  ·  {time_str}</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    if is_shared:
        for hid in HR_IDS:
            await ctx.bot.send_message(chat_id=hid, text=summary, parse_mode="HTML")
    else:
        await ctx.bot.send_message(chat_id=booked_hr, text=summary, parse_mode="HTML")

# ── Aiohttp web-сервер ─────────────────────────────────────────────────────────
CORS = {"Access-Control-Allow-Origin": "*"}

async def serve_index(request):
    return web.FileResponse(os.path.join(WEBAPP_DIR, "index.html"))

async def serve_hr_app(request):
    return web.FileResponse(os.path.join(WEBAPP_DIR, "hr.html"))

async def serve_slots(request):
    """Свободные слоты кандидату (следующие 7 дней)."""
    data  = load()
    today = date.today()
    result = {}
    for i in range(1, 8):
        d     = today + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        slots = get_all_free_slots(data, d_str)
        if slots:
            result[d_str] = [{"time": t, "hr_id": h} for (t, h) in slots]
    return web.Response(text=json.dumps(result, ensure_ascii=False),
                        content_type="application/json", headers=CORS)

async def serve_candidates_api(request):
    """Список кандидатов для HR."""
    hr_id = int(request.rel_url.query.get("hr_id", 0))
    data  = load()
    cands = [c for c in data["candidates"].values()
             if c.get("hr_id") == hr_id or c.get("shared")]
    return web.Response(text=json.dumps(cands, ensure_ascii=False),
                        content_type="application/json", headers=CORS)

async def serve_my_slots_get(request):
    """Слоты конкретного HR."""
    hr_id = int(request.rel_url.query.get("hr_id", 0))
    data  = load()
    slots = _hr_slots(data, hr_id)
    return web.Response(text=json.dumps(slots, ensure_ascii=False),
                        content_type="application/json", headers=CORS)

async def serve_my_slots_post(request):
    """Сохранить слоты от HR-дашборда."""
    try:
        body  = await request.json()
        hr_id = int(body.get("hr_id", 0))
        slots = body.get("slots", {})
        data  = load()
        _hr_slots(data, hr_id).update(slots)
        save(data)
        return web.Response(text='{"ok":true}',
                            content_type="application/json", headers=CORS)
    except Exception as e:
        return web.Response(text=json.dumps({"ok": False, "error": str(e)}),
                            content_type="application/json", headers=CORS)

async def serve_static(request):
    filename = request.match_info["filename"]
    filepath = os.path.join(WEBAPP_DIR, filename)
    if os.path.isfile(filepath):
        return web.FileResponse(filepath)
    raise web.HTTPNotFound()

async def run_webserver():
    app_web = web.Application()
    app_web.router.add_get("/",                serve_index)
    app_web.router.add_get("/hr",              serve_hr_app)
    app_web.router.add_get("/slots",           serve_slots)
    app_web.router.add_get("/api/candidates",  serve_candidates_api)
    app_web.router.add_get("/api/my-slots",    serve_my_slots_get)
    app_web.router.add_post("/api/my-slots",   serve_my_slots_post)
    app_web.router.add_get("/{filename}",      serve_static)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Web-сервер запущен на порту {PORT}")

# ── Запуск ────────────────────────────────────────────────────────────────────
def build_app():
    app = ApplicationBuilder().token(TOKEN).connect_timeout(30).read_timeout(30).build()

    app.job_queue.run_daily(daily_check,      time=datetime.strptime("09:00", "%H:%M").time())
    app.job_queue.run_daily(evening_reminder, time=datetime.strptime("17:00", "%H:%M").time())
    app.job_queue.run_daily(daily_18_check,   time=datetime.strptime("18:00", "%H:%M").time())

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PICK_SPEC:   [CallbackQueryHandler(pick_spec,   pattern="^spec_")],
            PICK_FORMAT: [CallbackQueryHandler(pick_format, pattern="^format_")],
            PICK_DATE:   [CallbackQueryHandler(pick_date,   pattern="^date_")],
            PICK_TIME:   [CallbackQueryHandler(pick_time,   pattern="^time_")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("menu",    menu_cmd))
    app.add_handler(CommandHandler("slots",   slots_cmd))
    app.add_handler(CommandHandler("week",    week_cmd))
    app.add_handler(CommandHandler("list",    list_cmd))
    app.add_handler(CommandHandler("preview", preview_cmd))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(list(HR_IDS.keys())),
        hr_keyboard_handler
    ))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data_handler))
    app.add_handler(CallbackQueryHandler(week_action_callback,           pattern="^week_"))
    app.add_handler(CallbackQueryHandler(edit_day_callback,              pattern="^editday_"))
    app.add_handler(CallbackQueryHandler(toggle_slot_callback,           pattern="^toggleslot_"))
    app.add_handler(CallbackQueryHandler(fillday_callback,               pattern="^fillday_"))
    app.add_handler(CallbackQueryHandler(clearday_callback,              pattern="^clearday_"))
    app.add_handler(CallbackQueryHandler(save_slots_callback,            pattern="^saveslots_"))
    app.add_handler(CallbackQueryHandler(hr_callback,                    pattern="^hr_"))
    app.add_handler(CallbackQueryHandler(reschedule_callback,            pattern="^reschedule_"))
    app.add_handler(CallbackQueryHandler(candidate_confirm_callback,     pattern="^cand_"))
    app.add_handler(CallbackQueryHandler(changed_plans_callback,         pattern="^changed_plans$"))
    app.add_handler(CallbackQueryHandler(changed_plans_choice_callback,  pattern="^cp_"))
    app.add_handler(CallbackQueryHandler(resch_start_callback,           pattern="^resch_start$"))
    app.add_handler(CallbackQueryHandler(resch_date_callback,            pattern="^resch_date_"))
    app.add_handler(CallbackQueryHandler(resch_time_callback,            pattern="^resch_time_"))
    app.add_handler(CallbackQueryHandler(stats_period_callback,          pattern="^stats_"))
    app.add_handler(CallbackQueryHandler(noop_callback,                  pattern="^preview_noop$"))
    return app

if __name__ == "__main__":
    async def main():
        print("✅ HR-система BECKER запущена!")
        for uid, name in HR_IDS.items():
            print(f"   HR: {name} (ID: {uid})")
        if WEBAPP_URL:
            print(f"   WebApp URL: {WEBAPP_URL}")

        await run_webserver()

        app = build_app()
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print("🤖 Бот запущен, жду сообщений...")
        await asyncio.Event().wait()   # работаем вечно

    asyncio.run(main())
