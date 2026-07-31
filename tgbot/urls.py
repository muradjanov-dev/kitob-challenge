from django.urls import path
from .views import (
    home, telegram, library_view, internal_diag_blocked_users, internal_unblock_false_positives,
    internal_diag_challenge_boom_state, internal_retire_challenge_and_launch_boom,
)
from src.settings import WEBHOOK_PATH
from tgbot.views import health_check_celery, health_check_redis
from tgbot.shop_views import shop_index, api_products, api_me, api_buy
from tgbot.library_views import (
    api_comments, api_add_comment, api_delete_comment, api_my_books, api_recent_comments,
    api_get_progress, api_save_progress, api_start_reading, api_premium_access,
)
from tgbot.cabinet_views import cabinet_index, api_cabinet_me
from tgbot.report_views import api_submit_report, api_my_report_books
from tgbot.analytics_views import api_track_event
from tgbot.game_views import (
    chain_index, api_chain_state, api_chain_submit,
    feud_index, api_feud_state, api_feud_submit,
    castle_index, api_castle_state, api_castle_submit,
    emoji_index, api_emoji_state, api_emoji_submit,
    wisdom_index, api_wisdom_state, api_wisdom_submit,
    detective_index, api_detective_state, api_detective_submit,
    survival_index, api_survival_state, api_survival_submit,
    quiz_index, api_quiz_state, api_quiz_submit,
    api_games_status,
)


urlpatterns = [
    path('', home, name='home'),
    path('kutubxona/', library_view, name='library'),
    path('kutubxona/api/comments/', api_comments, name='library-api-comments'),
    path('kutubxona/api/comment/', api_add_comment, name='library-api-add-comment'),
    path('kutubxona/api/comment/delete/', api_delete_comment, name='library-api-delete-comment'),
    path('kutubxona/api/my-books/', api_my_books, name='library-api-my-books'),
    path('kutubxona/api/comments/recent/', api_recent_comments, name='library-api-recent-comments'),
    path('kutubxona/api/progress/', api_get_progress, name='library-api-get-progress'),
    path('kutubxona/api/progress/save/', api_save_progress, name='library-api-save-progress'),
    path('kutubxona/api/start-reading/', api_start_reading, name='library-api-start-reading'),
    path('kutubxona/api/premium-access/', api_premium_access, name='library-api-premium-access'),
    path(WEBHOOK_PATH, telegram, name='webhook'),
    path("internal/diag/blocked-users/", internal_diag_blocked_users, name="internal-diag-blocked-users"),
    path("internal/fix/unblock-false-positives/", internal_unblock_false_positives, name="internal-unblock-false-positives"),
    path("internal/diag/challenge-boom-state/", internal_diag_challenge_boom_state, name="internal-diag-challenge-boom-state"),
    path("health-check/redis/", health_check_redis, name="health-check-redis"),
    path("health-check/celery/", health_check_celery, name="health-check-celery"),
    path("shop/", shop_index, name="shop"),
    path("shop/api/products/", api_products, name="shop-api-products"),
    path("shop/api/me/", api_me, name="shop-api-me"),
    path("shop/api/buy/", api_buy, name="shop-api-buy"),
    path("kabinet/", cabinet_index, name="cabinet"),
    path("kabinet/api/me/", api_cabinet_me, name="cabinet-api-me"),
    path("kabinet/api/report/", api_submit_report, name="cabinet-api-submit-report"),
    path("kabinet/api/report/books/", api_my_report_books, name="cabinet-api-report-books"),
    path("zanjir/", chain_index, name="chain"),
    path("zanjir/api/state/", api_chain_state, name="chain-api-state"),
    path("zanjir/api/submit/", api_chain_submit, name="chain-api-submit"),
    path("kopchilik/", feud_index, name="feud"),
    path("kopchilik/api/state/", api_feud_state, name="feud-api-state"),
    path("kopchilik/api/submit/", api_feud_submit, name="feud-api-submit"),
    path("qala/", castle_index, name="castle"),
    path("qala/api/state/", api_castle_state, name="castle-api-state"),
    path("qala/api/submit/", api_castle_submit, name="castle-api-submit"),
    path("emoji/", emoji_index, name="emoji"),
    path("emoji/api/state/", api_emoji_state, name="emoji-api-state"),
    path("emoji/api/submit/", api_emoji_submit, name="emoji-api-submit"),

    path("hikmat/", wisdom_index, name="wisdom"),
    path("hikmat/api/state/", api_wisdom_state, name="wisdom-api-state"),
    path("hikmat/api/submit/", api_wisdom_submit, name="wisdom-api-submit"),

    path("detektiv/", detective_index, name="detective"),
    path("detektiv/api/state/", api_detective_state, name="detective-api-state"),
    path("detektiv/api/submit/", api_detective_submit, name="detective-api-submit"),

    path("omon-qolish/", survival_index, name="survival"),
    path("omon-qolish/api/state/", api_survival_state, name="survival-api-state"),
    path("omon-qolish/api/submit/", api_survival_submit, name="survival-api-submit"),

    # Bilim O'yini — 4 flavors sharing one engine/template, distinct URLs.
    path("ikki-haqiqat/", quiz_index, {"flavor": "twofacts"}, name="quiz-twofacts"),
    path("ikki-haqiqat/api/state/", api_quiz_state, {"flavor": "twofacts"}, name="quiz-twofacts-api-state"),
    path("ikki-haqiqat/api/submit/", api_quiz_submit, {"flavor": "twofacts"}, name="quiz-twofacts-api-submit"),

    path("kim-yolgonchi/", quiz_index, {"flavor": "impostor"}, name="quiz-impostor"),
    path("kim-yolgonchi/api/state/", api_quiz_state, {"flavor": "impostor"}, name="quiz-impostor-api-state"),
    path("kim-yolgonchi/api/submit/", api_quiz_submit, {"flavor": "impostor"}, name="quiz-impostor-api-submit"),

    path("bog-lanish/", quiz_index, {"flavor": "connection"}, name="quiz-connection"),
    path("bog-lanish/api/state/", api_quiz_state, {"flavor": "connection"}, name="quiz-connection-api-state"),
    path("bog-lanish/api/submit/", api_quiz_submit, {"flavor": "connection"}, name="quiz-connection-api-submit"),

    path("jamoa-jangi/", quiz_index, {"flavor": "teams"}, name="quiz-teams"),
    path("jamoa-jangi/api/state/", api_quiz_state, {"flavor": "teams"}, name="quiz-teams-api-state"),
    path("jamoa-jangi/api/submit/", api_quiz_submit, {"flavor": "teams"}, name="quiz-teams-api-submit"),

    path("vaqt-mashinasi/", quiz_index, {"flavor": "timeline"}, name="quiz-timeline"),
    path("vaqt-mashinasi/api/state/", api_quiz_state, {"flavor": "timeline"}, name="quiz-timeline-api-state"),
    path("vaqt-mashinasi/api/submit/", api_quiz_submit, {"flavor": "timeline"}, name="quiz-timeline-api-submit"),

    path("muallif-asar/", quiz_index, {"flavor": "matchbook"}, name="quiz-matchbook"),
    path("muallif-asar/api/state/", api_quiz_state, {"flavor": "matchbook"}, name="quiz-matchbook-api-state"),
    path("muallif-asar/api/submit/", api_quiz_submit, {"flavor": "matchbook"}, name="quiz-matchbook-api-submit"),

    path("teskari-viktorina/", quiz_index, {"flavor": "reverse"}, name="quiz-reverse"),
    path("teskari-viktorina/api/state/", api_quiz_state, {"flavor": "reverse"}, name="quiz-reverse-api-state"),
    path("teskari-viktorina/api/submit/", api_quiz_submit, {"flavor": "reverse"}, name="quiz-reverse-api-submit"),

    path("api/games/status/", api_games_status, name="games-api-status"),

    path("api/track/event/", api_track_event, name="track-event"),
]
