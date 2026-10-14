"""Agg PNG charts whose figures close after sending, including on failure."""

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
from tempfile import gettempdir

# Keep font caches writable on a restricted host without changing HOME.
os.environ.setdefault("MPLCONFIGDIR", str(Path(gettempdir()) / "jeti-nur-matplotlib"))

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.ticker import FuncFormatter

from bot.i18n import format_money, t
from bot.services.stats import ChartSeries, period_label


@contextmanager
def chart_png(series: ChartSeries, period_key: str, lang: str):
    if not series.buckets:
        raise ValueError("Cannot render an empty chart")
    figure, axis = plt.subplots(figsize=(9, 5), dpi=200, facecolor="white")
    try:
        axis.set_facecolor("white")
        with BytesIO() as buffer:
            positions = list(range(len(series.buckets)))
            axis.bar(positions, [bucket.total for bucket in series.buckets], color="#2F7EAD", width=0.75)
            axis.set_title(t("chart_title", lang, period=period_label(period_key, lang)), fontfamily="DejaVu Sans", color="#1F1F1F")
            axis.set_xlabel(t("chart_weeks" if series.weekly else "chart_days", lang), fontfamily="DejaVu Sans", color="#1F1F1F")
            axis.set_ylabel(t("chart_amount", lang), fontfamily="DejaVu Sans", color="#1F1F1F")
            axis.tick_params(colors="#1F1F1F")
            for spine in axis.spines.values():
                spine.set_color("#1F1F1F")
            step = max(1, (len(positions) + 9) // 10)
            ticks = positions[::step]
            if positions[-1] not in ticks:
                ticks.append(positions[-1])
            axis.set_xticks(ticks, [series.buckets[index].day.strftime("%d.%m.%y") for index in ticks], rotation=35, ha="right")
            axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: format_money(value, lang).removesuffix(" " + t("currency", lang))))
            axis.set_ylim(bottom=0)
            axis.grid(axis="y", alpha=0.25, color="#D0D7DE")
            axis.set_axisbelow(True)
            figure.tight_layout()
            figure.savefig(buffer, format="png", dpi=200, facecolor="white", transparent=False)
            yield buffer.getvalue()
    finally:
        plt.close(figure)
