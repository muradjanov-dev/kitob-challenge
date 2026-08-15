from django.urls import path
from .views import (
    home, telegram, library_view, internal_diag_blocked_users, internal_unblock_false_positives,
    internal_diag_challenge_boom_state, internal_retire_challenge_and_launch_boom,
    internal_diag_challenge_reward_history, internal_broadcast_mystery_box_update,
    internal_broadcast_update_announcement,
    internal_diag_achievements, internal_diag_ai_quiz_trial_backlog, internal_fix_ai_quiz_trial_backlog,
    internal_grant_ai_quiz_bonus_everyone, internal_ai_quiz_bonus_status,
)
from src.settings import WEBHOOK_PATH
from tgbot.views import health_check_celery, health_check_redis
from tgbot.shop_views import shop_index, api_products, api_products_public, api_me, api_buy
from tgbot.library_views import (
    api_comments, api_add_comment, api_delete_comment, api_my_books, api_recent_comments,
    api_get_progress, api_save_progress, api_start_reading, api_premium_access,
    api_top_active_readers,
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
    path('library/', library_view, name='library-alias'),
    path('dokon/', shop_index, name='shop-alias'),
    path('kutubxona/api/comments/', api_comments, name='library-api-comments'),
    path('kutubxona/api/comment/', api_add_comment, name='library-api-add-comment'),
    path('kutubxona/api/comment/delete/', api_delete_comment, name='library-api-delete-comment'),
    path('kutubxona/api/my-books/', api_my_books, name='library-api-my-books'),
    path('kutubxona/api/comments/recent/', api_recent_comments, name='library-api-recent-comments'),
    path('kutubxona/api/top-active/', api_top_active_readers, name='library-api-top-active'),
    path('kutubxona/api/progress/', api_get_progress, name='library-api-get-progress'),
    path('kutubxona/api/progress/save/', api_save_progress, name='library-api-save-progress'),
    path('kutubxona/api/start-reading/', api_start_reading, name='library-api-start-reading'),
    path('kutubxona/api/premium-access/', api_premium_access, name='library-api-premium-access'),
    path(WEBHOOK_PATH, telegram, name='webhook'),
    path("internal/diag/blocked-users/", internal_diag_blocked_users, name="internal-diag-blocked-users"),
    path("internal/diag/achievements/", internal_diag_achievements, name="internal-diag-achievements"),
    path("internal/diag/ai-quiz-trial-backlog/", internal_diag_ai_quiz_trial_backlog, name="internal-diag-ai-quiz-trial-backlog"),
    path("internal/fix/ai-quiz-trial-backlog/", internal_fix_ai_quiz_trial_backlog, name="internal-fix-ai-quiz-trial-backlog"),
    path("internal/grant/ai-quiz-bonus-everyone/", internal_grant_ai_quiz_bonus_everyone, name="internal-grant-ai-quiz-bonus-everyone"),
    path("internal/diag/ai-quiz-bonus-status/", internal_ai_quiz_bonus_status, name="internal-ai-quiz-bonus-status"),
    path("internal/fix/unblock-false-positives/", internal_unblock_false_positives, name="internal-unblock-false-positives"),
    path("internal/diag/challenge-boom-state/", internal_diag_challenge_boom_state, name="internal-diag-challenge-boom-state"),
    path("internal/diag/challenge-reward-history/", internal_diag_challenge_reward_history, name="internal-diag-challenge-reward-history"),
    path("internal/fix/retire-challenge-and-launch-boom/", internal_retire_challenge_and_launch_boom, name="internal-retire-challenge-and-launch-boom"),
    path("internal/broadcast/mystery-box-update/", internal_broadcast_mystery_box_update, name="internal-broadcast-mystery-box-update"),
    path("internal/broadcast/update-announcement/", internal_broadcast_update_announcement, name="internal-broadcast-update-announcement"),
    path("health-check/redis/", health_check_redis, name="health-check-redis"),
    path("health-check/celery/", health_check_celery, name="health-check-celery"),
    path("shop/", shop_index, name="shop"),
    path("shop/api/products/", api_products, name="shop-api-products"),
    path("shop/api/products-public/", api_products_public, name="shop-api-products-public"),
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

    path("kitob-muqovasi/", quiz_index, {"flavor": "cover"}, name="quiz-cover"),
    path("kitob-muqovasi/api/state/", api_quiz_state, {"flavor": "cover"}, name="quiz-cover-api-state"),
    path("kitob-muqovasi/api/submit/", api_quiz_submit, {"flavor": "cover"}, name="quiz-cover-api-submit"),

    # 30 New Games (🧪 Test / Beta)
    path("anagram/", quiz_index, {"flavor": "anagram"}, name="quiz-anagram"),
    path("anagram/api/state/", api_quiz_state, {"flavor": "anagram"}, name="quiz-anagram-api-state"),
    path("anagram/api/submit/", api_quiz_submit, {"flavor": "anagram"}, name="quiz-anagram-api-submit"),

    path("blitz/", quiz_index, {"flavor": "blitz"}, name="quiz-blitz"),
    path("blitz/api/state/", api_quiz_state, {"flavor": "blitz"}, name="quiz-blitz-api-state"),
    path("blitz/api/submit/", api_quiz_submit, {"flavor": "blitz"}, name="quiz-blitz-api-submit"),

    path("crossword/", quiz_index, {"flavor": "crossword"}, name="quiz-crossword"),
    path("crossword/api/state/", api_quiz_state, {"flavor": "crossword"}, name="quiz-crossword-api-state"),
    path("crossword/api/submit/", api_quiz_submit, {"flavor": "crossword"}, name="quiz-crossword-api-submit"),

    path("wordle/", quiz_index, {"flavor": "wordle"}, name="quiz-wordle"),
    path("wordle/api/state/", api_quiz_state, {"flavor": "wordle"}, name="quiz-wordle-api-state"),
    path("wordle/api/submit/", api_quiz_submit, {"flavor": "wordle"}, name="quiz-wordle-api-submit"),

    path("cipher/", quiz_index, {"flavor": "cipher"}, name="quiz-cipher"),
    path("cipher/api/state/", api_quiz_state, {"flavor": "cipher"}, name="quiz-cipher-api-state"),
    path("cipher/api/submit/", api_quiz_submit, {"flavor": "cipher"}, name="quiz-cipher-api-submit"),

    path("acronym/", quiz_index, {"flavor": "acronym"}, name="quiz-acronym"),
    path("acronym/api/state/", api_quiz_state, {"flavor": "acronym"}, name="quiz-acronym-api-state"),
    path("acronym/api/submit/", api_quiz_submit, {"flavor": "acronym"}, name="quiz-acronym-api-submit"),

    path("character/", quiz_index, {"flavor": "character"}, name="quiz-character"),
    path("character/api/state/", api_quiz_state, {"flavor": "character"}, name="quiz-character-api-state"),
    path("character/api/submit/", api_quiz_submit, {"flavor": "character"}, name="quiz-character-api-submit"),

    path("dialogue/", quiz_index, {"flavor": "dialogue"}, name="quiz-dialogue"),
    path("dialogue/api/state/", api_quiz_state, {"flavor": "dialogue"}, name="quiz-dialogue-api-state"),
    path("dialogue/api/submit/", api_quiz_submit, {"flavor": "dialogue"}, name="quiz-dialogue-api-submit"),

    path("plotmap/", quiz_index, {"flavor": "plotmap"}, name="quiz-plotmap"),
    path("plotmap/api/state/", api_quiz_state, {"flavor": "plotmap"}, name="quiz-plotmap-api-state"),
    path("plotmap/api/submit/", api_quiz_submit, {"flavor": "plotmap"}, name="quiz-plotmap-api-submit"),

    path("sequence/", quiz_index, {"flavor": "sequence"}, name="quiz-sequence"),
    path("sequence/api/state/", api_quiz_state, {"flavor": "sequence"}, name="quiz-sequence-api-state"),
    path("sequence/api/submit/", api_quiz_submit, {"flavor": "sequence"}, name="quiz-sequence-api-submit"),

    path("oddone/", quiz_index, {"flavor": "oddone"}, name="quiz-oddone"),
    path("oddone/api/state/", api_quiz_state, {"flavor": "oddone"}, name="quiz-oddone-api-state"),
    path("oddone/api/submit/", api_quiz_submit, {"flavor": "oddone"}, name="quiz-oddone-api-submit"),

    path("ending/", quiz_index, {"flavor": "ending"}, name="quiz-ending"),
    path("ending/api/state/", api_quiz_state, {"flavor": "ending"}, name="quiz-ending-api-state"),
    path("ending/api/submit/", api_quiz_submit, {"flavor": "ending"}, name="quiz-ending-api-submit"),

    path("pixel/", quiz_index, {"flavor": "pixel"}, name="quiz-pixel"),
    path("pixel/api/state/", api_quiz_state, {"flavor": "pixel"}, name="quiz-pixel-api-state"),
    path("pixel/api/submit/", api_quiz_submit, {"flavor": "pixel"}, name="quiz-pixel-api-submit"),

    path("aiart/", quiz_index, {"flavor": "aiart"}, name="quiz-aiart"),
    path("aiart/api/state/", api_quiz_state, {"flavor": "aiart"}, name="quiz-aiart-api-state"),
    path("aiart/api/submit/", api_quiz_submit, {"flavor": "aiart"}, name="quiz-aiart-api-submit"),

    path("scenes/", quiz_index, {"flavor": "scenes"}, name="quiz-scenes"),
    path("scenes/api/state/", api_quiz_state, {"flavor": "scenes"}, name="quiz-scenes-api-state"),
    path("scenes/api/submit/", api_quiz_submit, {"flavor": "scenes"}, name="quiz-scenes-api-submit"),

    path("audioquote/", quiz_index, {"flavor": "audioquote"}, name="quiz-audioquote"),
    path("audioquote/api/state/", api_quiz_state, {"flavor": "audioquote"}, name="quiz-audioquote-api-state"),
    path("audioquote/api/submit/", api_quiz_submit, {"flavor": "audioquote"}, name="quiz-audioquote-api-submit"),

    path("mosaic/", quiz_index, {"flavor": "mosaic"}, name="quiz-mosaic"),
    path("mosaic/api/state/", api_quiz_state, {"flavor": "mosaic"}, name="quiz-mosaic-api-state"),
    path("mosaic/api/submit/", api_quiz_submit, {"flavor": "mosaic"}, name="quiz-mosaic-api-submit"),

    path("hiddendetail/", quiz_index, {"flavor": "hiddendetail"}, name="quiz-hiddendetail"),
    path("hiddendetail/api/state/", api_quiz_state, {"flavor": "hiddendetail"}, name="quiz-hiddendetail-api-state"),
    path("hiddendetail/api/submit/", api_quiz_submit, {"flavor": "hiddendetail"}, name="quiz-hiddendetail-api-submit"),

    path("duel/", quiz_index, {"flavor": "duel"}, name="quiz-duel"),
    path("duel/api/state/", api_quiz_state, {"flavor": "duel"}, name="quiz-duel-api-state"),
    path("duel/api/submit/", api_quiz_submit, {"flavor": "duel"}, name="quiz-duel-api-submit"),

    path("buzzer/", quiz_index, {"flavor": "buzzer"}, name="quiz-buzzer"),
    path("buzzer/api/state/", api_quiz_state, {"flavor": "buzzer"}, name="quiz-buzzer-api-state"),
    path("buzzer/api/submit/", api_quiz_submit, {"flavor": "buzzer"}, name="quiz-buzzer-api-submit"),

    path("bracket/", quiz_index, {"flavor": "bracket"}, name="quiz-bracket"),
    path("bracket/api/state/", api_quiz_state, {"flavor": "bracket"}, name="quiz-bracket-api-state"),
    path("bracket/api/submit/", api_quiz_submit, {"flavor": "bracket"}, name="quiz-bracket-api-submit"),

    path("auction/", quiz_index, {"flavor": "auction"}, name="quiz-auction"),
    path("auction/api/state/", api_quiz_state, {"flavor": "auction"}, name="quiz-auction-api-state"),
    path("auction/api/submit/", api_quiz_submit, {"flavor": "auction"}, name="quiz-auction-api-submit"),

    path("regions/", quiz_index, {"flavor": "regions"}, name="quiz-regions"),
    path("regions/api/state/", api_quiz_state, {"flavor": "regions"}, name="quiz-regions-api-state"),
    path("regions/api/submit/", api_quiz_submit, {"flavor": "regions"}, name="quiz-regions-api-submit"),

    path("king/", quiz_index, {"flavor": "king"}, name="quiz-king"),
    path("king/api/state/", api_quiz_state, {"flavor": "king"}, name="quiz-king-api-state"),
    path("king/api/submit/", api_quiz_submit, {"flavor": "king"}, name="quiz-king-api-submit"),

    path("rhyme/", quiz_index, {"flavor": "rhyme"}, name="quiz-rhyme"),
    path("rhyme/api/state/", api_quiz_state, {"flavor": "rhyme"}, name="quiz-rhyme-api-state"),
    path("rhyme/api/submit/", api_quiz_submit, {"flavor": "rhyme"}, name="quiz-rhyme-api-submit"),

    path("scholars/", quiz_index, {"flavor": "scholars"}, name="quiz-scholars"),
    path("scholars/api/state/", api_quiz_state, {"flavor": "scholars"}, name="quiz-scholars-api-state"),
    path("scholars/api/submit/", api_quiz_submit, {"flavor": "scholars"}, name="quiz-scholars-api-submit"),

    path("genres/", quiz_index, {"flavor": "genres"}, name="quiz-genres"),
    path("genres/api/state/", api_quiz_state, {"flavor": "genres"}, name="quiz-genres-api-state"),
    path("genres/api/submit/", api_quiz_submit, {"flavor": "genres"}, name="quiz-genres-api-submit"),

    path("numbers/", quiz_index, {"flavor": "numbers"}, name="quiz-numbers"),
    path("numbers/api/state/", api_quiz_state, {"flavor": "numbers"}, name="quiz-numbers-api-state"),
    path("numbers/api/submit/", api_quiz_submit, {"flavor": "numbers"}, name="quiz-numbers-api-submit"),

    path("worldlit/", quiz_index, {"flavor": "worldlit"}, name="quiz-worldlit"),
    path("worldlit/api/state/", api_quiz_state, {"flavor": "worldlit"}, name="quiz-worldlit-api-state"),
    path("worldlit/api/submit/", api_quiz_submit, {"flavor": "worldlit"}, name="quiz-worldlit-api-submit"),

    path("mysterybox/", quiz_index, {"flavor": "mysterybox"}, name="quiz-mysterybox"),
    path("mysterybox/api/state/", api_quiz_state, {"flavor": "mysterybox"}, name="quiz-mysterybox-api-state"),
    path("mysterybox/api/submit/", api_quiz_submit, {"flavor": "mysterybox"}, name="quiz-mysterybox-api-submit"),

    path("api/games/status/", api_games_status, name="games-api-status"),

    path("api/track/event/", api_track_event, name="track-event"),
]
