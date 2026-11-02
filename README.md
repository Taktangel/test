# trader-backtest

Бэктест двух стратегий из [trader-skill](https://github.com/Jakeschincariol/trader-skill):

- **Copycat**: копировать топ-10 позиций 23 известных фондов в день выхода их 13F.
- **Congress**: покупать вслед за раскрытыми покупками акций членов Палаты (Пелоси и ещё 5 из `members.json`).

Каждая сделка сравнивается с SPY за то же окно. Свежий отчёт: [`reports/latest.md`](reports/latest.md).
Обновляется каждое воскресенье в GitHub Actions.

Не финансовый совет. Ничего не торгует.

## Запуск в GitHub

1. Залить репо на GitHub (подойдёт приватный).
2. Settings → Secrets and variables → Actions → New repository secret:
   - `SEC_USER_AGENT` = `Имя Фамилия you@example.com` (обязательно, этого требует SEC);
   - `OPENFIGI_API_KEY` (необязательно, помогает найти тикеры по CUSIP).
3. Actions → backtest → Run workflow. Первый прогон долгий (скачивается вся история), следующие быстрые за счёт кеша.

В публичных репо GitHub отключает расписание после 60 дней без активности. Еженедельные коммиты отчёта считаются активностью.

Если на ветке по умолчанию включена защита (branch protection), пуш бота `github-actions[bot]` будет отклонён: разрешите ему пуш или уберите защиту.

## Запуск локально

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -q
```

```bash
SEC_USER_AGENT="Имя you@example.com" .venv/Scripts/python -m backtest.run
```

Для PTR нужен `pdftotext` (poppler). Без него сделки Конгресса не прочитаются и попадут в `reports/errors.log`.
Повторный расчёт без скачивания: `.venv/Scripts/python -m backtest.run --skip-fetch`.

## Настройки

- `config.json`: период, топ-N, сроки удержания.
- `members.json`: члены Палаты.
- `vendor/filers.json`: фонды.
