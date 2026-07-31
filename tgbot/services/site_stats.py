"""Aggregation for the Sayt Statistikasi dashboard — shared by the Django
admin's SiteEventAdmin.changelist_view and the bot's /admin panel button, so
both surfaces report identical numbers."""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from tgbot.models import SiteEvent

SECTION_LABELS = {
    "site": "Bosh sahifa", "library": "Kutubxona", "shop": "Do'kon",
    "cabinet": "Kabinet", "chain": "Zanjiri (o'yin)", "feud": "Ko'pchilik (o'yin)",
    "castle": "Qal'a (o'yin)", "emoji": "Emoji (o'yin)", "wisdom": "Hikmat (o'yin)",
    "detective": "Detektiv (o'yin)", "survival": "Omon qolish (o'yin)",
    "quiz-twofacts": "Ikki haqiqat", "quiz-impostor": "Kim yolg'onchi",
    "quiz-connection": "Bog'lanish", "quiz-teams": "Jamoa jangi",
    "quiz-timeline": "Vaqt mashinasi", "quiz-matchbook": "Muallif-asar",
    "quiz-reverse": "Teskari viktorina",
}

RANGE_CHOICES = {
    "today": ("Bugun", 1),
    "7d": ("So'nggi 7 kun", 7),
    "30d": ("So'nggi 30 kun", 30),
    "all": ("Hammasi", None),
}


def compute_site_stats(range_key: str = "7d", top_n: int = 20) -> dict:
    """Returns totals + top sections/buttons for the given RANGE_CHOICES key."""
    if range_key not in RANGE_CHOICES:
        range_key = "7d"
    _, days = RANGE_CHOICES[range_key]

    qs = SiteEvent.objects.all()
    if days is not None:
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))

    top_sections = list(
        qs.values("section")
          .annotate(
              views=Count("id", filter=Q(event_type=SiteEvent.TYPE_PAGEVIEW)),
              click_count=Count("id", filter=Q(event_type=SiteEvent.TYPE_CLICK)),
              users=Count("user", distinct=True),
          )
          .order_by("-views", "-click_count")[:top_n]
    )
    for row in top_sections:
        row["display"] = SECTION_LABELS.get(row["section"], row["section"])

    top_buttons = list(
        qs.filter(event_type=SiteEvent.TYPE_CLICK)
          .exclude(label="")
          .values("section", "label")
          .annotate(clicks=Count("id"))
          .order_by("-clicks")[:top_n]
    )
    for row in top_buttons:
        row["display"] = SECTION_LABELS.get(row["section"], row["section"])

    return {
        "range_key": range_key,
        "total_pageviews": qs.filter(event_type=SiteEvent.TYPE_PAGEVIEW).count(),
        "total_clicks": qs.filter(event_type=SiteEvent.TYPE_CLICK).count(),
        "total_users": qs.exclude(user__isnull=True).values("user").distinct().count(),
        "top_sections": top_sections,
        "top_buttons": top_buttons,
    }
