"""Kitobcha economy: how much was issued and spent, and where.

Read-only, from KitobchaLedger (every balance change writes a row; earnings
carry the source passed to update_ball(reason=...), spends their own
reasons). Sent to the admins every Monday (tasks.send_economy_report) and
available on demand at internal/ops/kitobcha-economy/.

The owner's rule (2026-10-28): no inflation, no deflation -- this is the
measurement that rule is checked against. From the wallet launch Kitobcha
pays up to 30% of the daily fee, so it is worth real money.
"""
import datetime
from collections import defaultdict

from django.db.models import Sum
from django.utils import timezone

# ledger reason (or its prefix before ":") -> report label
SOURCES = {
    "game_reward": "🎮 Jonli o'yinlar",
    "report_reward": "📚 Hisobot mukofoti",
    "reading": "📖 Mini Appda o'qish",
    "achievement": "🏆 Yutuqlar",
    "viktorina": "🧩 Viktorina",
    "quiz_play": "📝 Quizlar",
    "referral": "🤝 Referal",
    "boom": "🚀 BOOM",
    "challenge": "🎯 Challenge",
    "leaderboard": "🥇 Reyting mukofotlari",
    "survey": "💡 So'rovnoma",
    "admin_grant": "👑 Admin",
}
SINKS = {
    "report_fee": "👛 Hamyon to'lovi",
    "shop_purchase": "🛍 Do'kon",
    "shop_auction_bid": "🏛 Auksion",
    "auction_refund": "🏛 Auksion",
    "market_charge": "🎪 Market",
    "joker_fifty": "🃏 Jokerlar", "joker_shield": "🃏 Jokerlar", "joker_sniper": "🃏 Jokerlar",
    "ai_quiz_creation": "🤖 AI quiz", "ai_quiz_refund": "🤖 AI quiz",
    "manual_quiz_creation": "📝 Quiz tuzish",
    "book_start_fee": "📖 Kitob boshlash",
    "charity": "💚 Xayriya",
    "premium_mixed": "💎 Premium (aralash)",
    "game_entry_fee": "🎮 O'yin kirish",
}


def _label(reason: str, table: dict) -> str:
    key = (reason or "").split(":", 1)[0]
    return table.get(key, "• Boshqa")


def report(days: int = 7) -> dict:
    from tgbot.models import ConfirmationReport, KitobchaLedger, TelegramProfile
    since = timezone.now() - datetime.timedelta(days=days)
    rows = (KitobchaLedger.objects.filter(created_at__gte=since)
            .values("reason").annotate(s=Sum("delta")))
    issued, spent = defaultdict(int), defaultdict(int)
    for r in rows:
        reason, s = r["reason"] or "", int(r["s"] or 0)
        # A spend reason whose refunds outweigh it (auction refunds of an
        # older week) nets inside its own sink line, never as "issued".
        sink = (reason.split(":", 1)[0] in SINKS)
        if sink:
            spent[_label(reason, SINKS)] += -s
        elif s >= 0:
            issued[_label(reason, SOURCES)] += s
        else:
            spent["• Boshqa"] += -s
    total_issued, total_spent = sum(issued.values()), sum(spent.values())
    supply = int(TelegramProfile.objects.aggregate(s=Sum("ball"))["s"] or 0)
    net = total_issued - total_spent
    before = supply - net
    active_ids = set(ConfirmationReport.objects.filter(date__gte=since).values_list("user_id", flat=True))
    balances = sorted(int(b or 0) for b in TelegramProfile.objects.filter(id__in=active_ids)
                      .values_list("ball", flat=True))
    median = balances[len(balances) // 2] if balances else 0
    return {
        "days": days,
        "issued": dict(sorted(issued.items(), key=lambda kv: -kv[1])),
        "spent": dict(sorted(spent.items(), key=lambda kv: -kv[1])),
        "total_issued": total_issued, "total_spent": total_spent, "net": net,
        "supply": supply, "supply_change_pct": round(net * 100 / before, 1) if before > 0 else None,
        "active_readers": len(active_ids), "active_median_balance": median,
        "active_total_balance": sum(balances),
    }


def _n(x) -> str:
    return f"{int(x):,}".replace(",", " ")


def report_text(r: dict) -> str:
    lines = [f"📊 <b>Kitobcha iqtisodiyoti — so'nggi {r['days']} kun</b>\n",
             f"🪙 <b>Chiqarildi: +{_n(r['total_issued'])}</b>"]
    lines += [f"   {k}: {_n(v)}" for k, v in r["issued"].items() if v]
    lines.append(f"\n💸 <b>Sarflandi: −{_n(r['total_spent'])}</b>")
    lines += [f"   {k}: {_n(v)}" for k, v in r["spent"].items() if v]
    pct = r["supply_change_pct"]
    trend = ("⚖️ muvozanatda" if pct is not None and abs(pct) <= 2 else
             "📈 inflyatsiya" if r["net"] > 0 else "📉 deflyatsiya")
    lines.append(f"\n{trend}: sof {'+' if r['net'] >= 0 else '−'}{_n(abs(r['net']))}"
                 + (f" (zaxira {pct:+.1f}%)" if pct is not None else ""))
    lines.append(f"🏦 Jami zaxira: <b>{_n(r['supply'])}</b> Kitobcha")
    lines.append(f"👥 Faol kitobxonlar: {r['active_readers']} · o'rtacha (mediana) balans: {_n(r['active_median_balance'])}")
    lines.append("\n<i>Maqsad: zaxira haftasiga ±2% dan ko'p o'zgarmasin.</i>")
    return "\n".join(lines)
