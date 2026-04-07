from datetime import datetime, timedelta
import io

COST_PRICE = 189

def format_price(n):
    return f"{n:,}".replace(",", " ")
    
async def generate_stats(get_cursor, bot, period_days=30):
    cur = get_cursor()

    cur.execute("""
        SELECT user_id, username, amount, price, status, date
        FROM orders
    """)
    rows = cur.fetchall()

    from datetime import datetime, timedelta

    now = datetime.now()
    start_date = now - timedelta(days=period_days)

    daily_income = {}
    total_income = 0  # оборот (деньги от клиентов)
    total_cost = 0    # затраты (твоя закупка)
    success_orders = 0
    failed_orders = 0
    users = {}

    for r in rows:
        user_id, username, amount, price, status, date_str = r
        order_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")

        if order_date < start_date:
            continue

        day = order_date.strftime("%Y-%m-%d")

        if status == "success":
            total_income += price
            total_cost += amount * 189
            success_orders += 1

            daily_income[day] = daily_income.get(day, 0) + price

            # 👤 сохраняем username
            users[user_id] = {
                "spent": users.get(user_id, {}).get("spent", 0) + price
            }
        else:
            failed_orders += 1

    profit = total_income - total_cost
    total_orders = success_orders + failed_orders

    # --- ТОП ---
    top_users = sorted(users.items(), key=lambda x: x[1]["spent"], reverse=True)[:5]

    # --- ASCII ГРАФИК ---
    days = [(now - timedelta(days=i)).strftime("%m-%d") for i in range(period_days-1, -1, -1)]
    values = [daily_income.get((now - timedelta(days=i)).strftime("%Y-%m-%d"), 0)
              for i in range(period_days-1, -1, -1)]

    max_val = max(values) if values else 1

    graph_lines = []
    for i, val in enumerate(values):
        bars = int((val / max_val) * 10) if max_val else 0
        line = "▇" * bars if bars > 0 else "."
        graph_lines.append(f"{days[i]} {line}")

    graph_text = "\n".join(graph_lines[-10:])

    # --- ТЕКСТ ---
    text = (
        f"📊 Статистика за {period_days} дней\n\n"
        f"💰 Оборот: {format_price(total_income)} UZS\n"
        f"💸 Затраты: {format_price(total_cost)} UZS\n"
        f"📈 Прибыль: {format_price(profit)} UZS\n\n"
        f"📦 Заказы: {total_orders}\n"
        f"✅ Успешные: {success_orders}\n"
        f"❌ Ошибки: {failed_orders}\n\n"
        f"📉 График:\n{graph_text}\n\n"
        f"🏆 Топ клиентов:\n"
    )

    for i, (uid, data) in enumerate(top_users, 1):
        try:
            user = await bot.get_chat(uid)
            username = f"@{user.username}" if user.username else f"id:{uid}"
        except:
            username = f"id:{uid}"

        text += f"{i}. {username} — {format_price(data['spent'])} UZS\n"
    
    return text
