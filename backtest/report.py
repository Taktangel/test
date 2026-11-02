"""Writes reports/: latest.md, trades.csv, summary.json, equity.png, errors.log."""
import json
import math
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

CAVEATS = [
    "Не финансовый совет. Это проверка правил на прошлых данных, а не прогноз.",
    "13F выходит до 45 дней после конца квартала и показывает только длинные позиции в акциях США.",
    "PTR подают до 45 дней после сделки, суммы указаны диапазонами. Учтены только акции, опционы пропущены.",
    "Комиссии, проскальзывание и налоги не учтены.",
    "Ошибка выжившего: по делистингованным тикерам цен часто нет, такие сделки в колонке «Без цены».",
    "Сделки в статусе «Открыто» оценены по последней цене и в доли выигрышных не входят.",
    "Copycat: вес позиций без цены делится между остальными позициями периода, а не держится в кэше.",
    "Конгресс: свободные деньги лежат в кэше под 0 %, поэтому CAGR занижен относительно всегда вложенного SPY.",
]
NAMES = {
    "strategy": "Стратегия", "variant": "Вариант", "source": "Источник",
    "trades": "Закрыто сделок", "win_abs_pct": "Доля в плюсе, %",
    "win_spy_pct": "Доля лучше SPY, %", "mean_ret_pct": "Средняя, %",
    "median_ret_pct": "Медиана, %", "mean_excess_pct": "Избыток над SPY, %",
    "open": "Открыто", "no_price": "Без цены", "start": "С", "end": "По",
    "cagr_pct": "CAGR, %", "spy_cagr_pct": "CAGR SPY, %", "max_dd_pct": "Просадка, %",
    "spy_max_dd_pct": "Просадка SPY, %",
}


def _cell(v):
    if isinstance(v, float):
        return "" if math.isnan(v) else "%.1f" % v
    return str(v)


def md_table(df):
    if df.empty:
        return "_нет данных_\n"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


def _records(df):
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _json_default(o):
    return o.item() if hasattr(o, "item") else str(o)


def _plot(curves, path):
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, eq in sorted(curves.items()):
        ax.plot(eq.index, eq.values, label=name, linewidth=1.2)
    ax.set_yscale("log")
    # Plain tick labels: mathtext (default for log axes) trips pyparsing deprecation warnings.
    plain = FuncFormatter(lambda v, _: "%g" % v)
    ax.yaxis.set_major_formatter(plain)
    ax.yaxis.set_minor_formatter(plain)
    ax.set_ylabel("Капитал (старт = 1.0)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def write_report(out_dir, trades, overall, by_source, books, curves, errors, generated):
    os.makedirs(out_dir, exist_ok=True)
    trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"generated": generated, "overall": _records(overall),
                   "by_source": _records(by_source), "books": _records(books)},
                  fh, ensure_ascii=False, indent=2, default=_json_default)
    with open(os.path.join(out_dir, "errors.log"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(errors) + ("\n" if errors else ""))
    if curves:
        _plot(curves, os.path.join(out_dir, "equity.png"))

    top = overall.merge(books, on=["strategy", "variant"], how="left")
    md = ["# Бэктест: Copycat 13F и сделки Конгресса", "",
          "Обновлено: %s" % generated, ""]
    md += ["> - %s" % c for c in CAVEATS]
    md += ["", "## Итог по стратегиям", "", md_table(top.rename(columns=NAMES))]
    if curves:
        md += ["![Кривая капитала](equity.png)", ""]
    for strategy, title in (("copycat", "Copycat по фондам"), ("congress", "Конгресс по членам Палаты")):
        part = by_source[by_source["strategy"] == strategy].drop(columns=["strategy"])
        part = part.sort_values(["variant", "source"])
        md += ["## %s" % title, "", md_table(part.rename(columns=NAMES))]
    md += ["## Данные", "",
           "Проблем при сборе данных: %d (подробно в `errors.log`)." % len(errors),
           "Все сделки: `trades.csv`. Машиночитаемая сводка: `summary.json`.", ""]
    with open(os.path.join(out_dir, "latest.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
