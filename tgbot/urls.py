from django.urls import path
from .views import (
    home, telegram, library_view, internal_diag_blocked_users, internal_unblock_false_positives,
    internal_diag_challenge_boom_state, internal_retire_challenge_and_launch_boom,
    internal_diag_challenge_reward_history, internal_broadcast_mystery_box_update,
    internal_broadcast_update_announcement,
    internal_broadcast_auction_announcement,
    internal_diag_achievements, internal_diag_ai_quiz_trial_backlog, internal_fix_ai_quiz_trial_backlog,
    internal_grant_ai_quiz_bonus_everyone, internal_ai_quiz_bonus_status,
)
from src.settings import WEBHOOK_PATH
from tgbot.views import health_check_celery, health_check_redis
from tgbot.shop_views import (
    shop_index, api_products, api_products_public, api_me, api_buy,
    api_auction_details, api_bid,
)
from tgbot.library_views import (
    api_comments, api_add_comment, api_delete_comment, api_my_books, api_recent_comments,
    api_get_progress, api_save_progress, api_start_reading, api_premium_access,
    api_top_active_readers,
)
from tgbot.cabinet_views import cabinet_index, api_cabinet_me, api_set_theme
from tgbot.report_views import api_submit_report, api_my_report_books
from tgbot.analytics_views import api_track_event
from tgbot.game_views import (
    chain_index, api_chain_state, api_chain_submit,
    feud_index, api_feud_state, api_feud_submit,
    castle_index, api_castle_state, api_castle_submit,
    emoji_index, api_emoji_state, api_emoji_submit,
    wisdom_index, api_wisdom_state, api_wisdom_submit,
    detective_index, api_detective_state, api_detective_submit,
    survival_index, api_survival_state, api_survival_submit, api_survival_joker,
    quiz_index, api_quiz_state, api_quiz_submit, api_quiz_joker,
    api_games_status,
)


urlpatterns = [
    path('', home, name='home'),
    path('kutubxona/', library_view, name='library'),
    path('library/', library_view, name='library-alias'),
    path('shop/', shop_index, name='shop'),
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
    path("internal/broadcast/auction-announcement/", internal_broadcast_auction_announcement, name="internal-broadcast-auction-announcement"),
    path("health-check/redis/", health_check_redis, name="health-check-redis"),
    path("health-check/celery/", health_check_celery, name="health-check-celery"),
    path('api/cabinet/me/', api_cabinet_me, name='api-cabinet-me'),
    path('api/shop/products/', api_products, name='api-products'),
    path("shop/api/products-public/", api_products_public, name="shop-api-products-public"),
    path("shop/api/me/", api_me, name="shop-api-me"),
    path("shop/api/buy/", api_buy, name="shop-api-buy"),
    path("shop/api/auction-details/", api_auction_details, name="shop-api-auction-details"),
    path("shop/api/bid/", api_bid, name="shop-api-bid"),
    path("kabinet/", cabinet_index, name="cabinet"),
    path("kabinet/api/me/", api_cabinet_me, name="cabinet-api-me"),
    path("kabinet/api/report/", api_submit_report, name="cabinet-api-submit-report"),
    path("kabinet/api/report/books/", api_my_report_books, name="cabinet-api-report-books"),
    path("kabinet/api/set-theme/", api_set_theme, name="cabinet-api-set-theme"),
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
    path("omon-qolish/api/joker/", api_survival_joker, name="survival-api-joker"),

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

    # 10 Mind, Logic, and Conscious Living Games (🧠 Ongli Hayot)
    path("mindtrap/", quiz_index, {"flavor": "mindtrap"}, name="quiz-mindtrap"),
    path("mindtrap/api/state/", api_quiz_state, {"flavor": "mindtrap"}, name="quiz-mindtrap-api-state"),
    path("mindtrap/api/submit/", api_quiz_submit, {"flavor": "mindtrap"}, name="quiz-mindtrap-api-submit"),

    path("stoic/", quiz_index, {"flavor": "stoic"}, name="quiz-stoic"),
    path("stoic/api/state/", api_quiz_state, {"flavor": "stoic"}, name="quiz-stoic-api-state"),
    path("stoic/api/submit/", api_quiz_submit, {"flavor": "stoic"}, name="quiz-stoic-api-submit"),

    path("antiherd/", quiz_index, {"flavor": "antiherd"}, name="quiz-antiherd"),
    path("antiherd/api/state/", api_quiz_state, {"flavor": "antiherd"}, name="quiz-antiherd-api-state"),
    path("antiherd/api/submit/", api_quiz_submit, {"flavor": "antiherd"}, name="quiz-antiherd-api-submit"),

    path("dilemma/", quiz_index, {"flavor": "dilemma"}, name="quiz-dilemma"),
    path("dilemma/api/state/", api_quiz_state, {"flavor": "dilemma"}, name="quiz-dilemma-api-state"),
    path("dilemma/api/submit/", api_quiz_submit, {"flavor": "dilemma"}, name="quiz-dilemma-api-submit"),

    path("causeeffect/", quiz_index, {"flavor": "causeeffect"}, name="quiz-causeeffect"),
    path("causeeffect/api/state/", api_quiz_state, {"flavor": "causeeffect"}, name="quiz-causeeffect-api-state"),
    path("causeeffect/api/submit/", api_quiz_submit, {"flavor": "causeeffect"}, name="quiz-causeeffect-api-submit"),

    path("masks/", quiz_index, {"flavor": "masks"}, name="quiz-masks"),
    path("masks/api/state/", api_quiz_state, {"flavor": "masks"}, name="quiz-masks-api-state"),
    path("masks/api/submit/", api_quiz_submit, {"flavor": "masks"}, name="quiz-masks-api-submit"),

    path("socrates/", quiz_index, {"flavor": "socrates"}, name="quiz-socrates"),
    path("socrates/api/state/", api_quiz_state, {"flavor": "socrates"}, name="quiz-socrates-api-state"),
    path("socrates/api/submit/", api_quiz_submit, {"flavor": "socrates"}, name="quiz-socrates-api-submit"),

    path("memento/", quiz_index, {"flavor": "memento"}, name="quiz-memento"),
    path("memento/api/state/", api_quiz_state, {"flavor": "memento"}, name="quiz-memento-api-state"),
    path("memento/api/submit/", api_quiz_submit, {"flavor": "memento"}, name="quiz-memento-api-submit"),

    path("strategy/", quiz_index, {"flavor": "strategy"}, name="quiz-strategy"),
    path("strategy/api/state/", api_quiz_state, {"flavor": "strategy"}, name="quiz-strategy-api-state"),
    path("strategy/api/submit/", api_quiz_submit, {"flavor": "strategy"}, name="quiz-strategy-api-submit"),

    path("paradox/", quiz_index, {"flavor": "paradox"}, name="quiz-paradox"),
    path("paradox/api/state/", api_quiz_state, {"flavor": "paradox"}, name="quiz-paradox-api-state"),
    path("paradox/api/submit/", api_quiz_submit, {"flavor": "paradox"}, name="quiz-paradox-api-submit"),

    # 10 Sufism, Nafs Purification, and Divine Love Games (✨ Tasavvuf & Ishqulloh)
    path("simurgh/", quiz_index, {"flavor": "simurgh"}, name="quiz-simurgh"),
    path("simurgh/api/state/", api_quiz_state, {"flavor": "simurgh"}, name="quiz-simurgh-api-state"),
    path("simurgh/api/submit/", api_quiz_submit, {"flavor": "simurgh"}, name="quiz-simurgh-api-submit"),

    path("ishq/", quiz_index, {"flavor": "ishq"}, name="quiz-ishq"),
    path("ishq/api/state/", api_quiz_state, {"flavor": "ishq"}, name="quiz-ishq-api-state"),
    path("ishq/api/submit/", api_quiz_submit, {"flavor": "ishq"}, name="quiz-ishq-api-submit"),

    path("nafs/", quiz_index, {"flavor": "nafs"}, name="quiz-nafs"),
    path("nafs/api/state/", api_quiz_state, {"flavor": "nafs"}, name="quiz-nafs-api-state"),
    path("nafs/api/submit/", api_quiz_submit, {"flavor": "nafs"}, name="quiz-nafs-api-submit"),

    path("qalb/", quiz_index, {"flavor": "qalb"}, name="quiz-qalb"),
    path("qalb/api/state/", api_quiz_state, {"flavor": "qalb"}, name="quiz-qalb-api-state"),
    path("qalb/api/submit/", api_quiz_submit, {"flavor": "qalb"}, name="quiz-qalb-api-submit"),

    path("naqshband/", quiz_index, {"flavor": "naqshband"}, name="quiz-naqshband"),
    path("naqshband/api/state/", api_quiz_state, {"flavor": "naqshband"}, name="quiz-naqshband-api-state"),
    path("naqshband/api/submit/", api_quiz_submit, {"flavor": "naqshband"}, name="quiz-naqshband-api-submit"),

    path("yassaviy/", quiz_index, {"flavor": "yassaviy"}, name="quiz-yassaviy"),
    path("yassaviy/api/state/", api_quiz_state, {"flavor": "yassaviy"}, name="quiz-yassaviy-api-state"),
    path("yassaviy/api/submit/", api_quiz_submit, {"flavor": "yassaviy"}, name="quiz-yassaviy-api-submit"),

    path("masnaviy/", quiz_index, {"flavor": "masnaviy"}, name="quiz-masnaviy"),
    path("masnaviy/api/state/", api_quiz_state, {"flavor": "masnaviy"}, name="quiz-masnaviy-api-state"),
    path("masnaviy/api/submit/", api_quiz_submit, {"flavor": "masnaviy"}, name="quiz-masnaviy-api-submit"),

    path("gazzoliy/", quiz_index, {"flavor": "gazzoliy"}, name="quiz-gazzoliy"),
    path("gazzoliy/api/state/", api_quiz_state, {"flavor": "gazzoliy"}, name="quiz-gazzoliy-api-state"),
    path("gazzoliy/api/submit/", api_quiz_submit, {"flavor": "gazzoliy"}, name="quiz-gazzoliy-api-submit"),

    path("fano/", quiz_index, {"flavor": "fano"}, name="quiz-fano"),
    path("fano/api/state/", api_quiz_state, {"flavor": "fano"}, name="quiz-fano-api-state"),
    path("fano/api/submit/", api_quiz_submit, {"flavor": "fano"}, name="quiz-fano-api-submit"),

    path("marifat/", quiz_index, {"flavor": "marifat"}, name="quiz-marifat"),
    path("marifat/api/state/", api_quiz_state, {"flavor": "marifat"}, name="quiz-marifat-api-state"),
    path("marifat/api/submit/", api_quiz_submit, {"flavor": "marifat"}, name="quiz-marifat-api-submit"),

    # 10 New Non-Test Interactive Games
    path("wordlock/", quiz_index, {"flavor": "wordlock"}, name="quiz-wordlock"),
    path("wordlock/api/state/", api_quiz_state, {"flavor": "wordlock"}, name="quiz-wordlock-api-state"),
    path("wordlock/api/submit/", api_quiz_submit, {"flavor": "wordlock"}, name="quiz-wordlock-api-submit"),

    path("speedtype/", quiz_index, {"flavor": "speedtype"}, name="quiz-speedtype"),
    path("speedtype/api/state/", api_quiz_state, {"flavor": "speedtype"}, name="quiz-speedtype-api-state"),
    path("speedtype/api/submit/", api_quiz_submit, {"flavor": "speedtype"}, name="quiz-speedtype-api-submit"),

    path("tilepuzzle/", quiz_index, {"flavor": "tilepuzzle"}, name="quiz-tilepuzzle"),
    path("tilepuzzle/api/state/", api_quiz_state, {"flavor": "tilepuzzle"}, name="quiz-tilepuzzle-api-state"),
    path("tilepuzzle/api/submit/", api_quiz_submit, {"flavor": "tilepuzzle"}, name="quiz-tilepuzzle-api-submit"),

    path("association/", quiz_index, {"flavor": "association"}, name="quiz-association"),
    path("association/api/state/", api_quiz_state, {"flavor": "association"}, name="quiz-association-api-state"),
    path("association/api/submit/", api_quiz_submit, {"flavor": "association"}, name="quiz-association-api-submit"),

    path("hangman/", quiz_index, {"flavor": "hangman"}, name="quiz-hangman"),
    path("hangman/api/state/", api_quiz_state, {"flavor": "hangman"}, name="quiz-hangman-api-state"),
    path("hangman/api/submit/", api_quiz_submit, {"flavor": "hangman"}, name="quiz-hangman-api-submit"),

    path("bookmemory/", quiz_index, {"flavor": "bookmemory"}, name="quiz-bookmemory"),
    path("bookmemory/api/state/", api_quiz_state, {"flavor": "bookmemory"}, name="quiz-bookmemory-api-state"),
    path("bookmemory/api/submit/", api_quiz_submit, {"flavor": "bookmemory"}, name="quiz-bookmemory-api-submit"),

    path("spellcheck/", quiz_index, {"flavor": "spellcheck"}, name="quiz-spellcheck"),
    path("spellcheck/api/state/", api_quiz_state, {"flavor": "spellcheck"}, name="quiz-spellcheck-api-state"),
    path("spellcheck/api/submit/", api_quiz_submit, {"flavor": "spellcheck"}, name="quiz-spellcheck-api-submit"),

    path("labyrinth/", quiz_index, {"flavor": "labyrinth"}, name="quiz-labyrinth"),
    path("labyrinth/api/state/", api_quiz_state, {"flavor": "labyrinth"}, name="quiz-labyrinth-api-state"),
    path("labyrinth/api/submit/", api_quiz_submit, {"flavor": "labyrinth"}, name="quiz-labyrinth-api-submit"),

    path("bookbidding/", quiz_index, {"flavor": "bookbidding"}, name="quiz-bookbidding"),
    path("bookbidding/api/state/", api_quiz_state, {"flavor": "bookbidding"}, name="quiz-bookbidding-api-state"),
    path("bookbidding/api/submit/", api_quiz_submit, {"flavor": "bookbidding"}, name="quiz-bookbidding-api-submit"),

    path("characterclash/", quiz_index, {"flavor": "characterclash"}, name="quiz-characterclash"),
    path("characterclash/api/state/", api_quiz_state, {"flavor": "characterclash"}, name="quiz-characterclash-api-state"),
    path("characterclash/api/submit/", api_quiz_submit, {"flavor": "characterclash"}, name="quiz-characterclash-api-submit"),

    path("riddlebox/", quiz_index, {"flavor": "riddlebox"}, name="quiz-riddlebox"),
    path("riddlebox/api/state/", api_quiz_state, {"flavor": "riddlebox"}, name="quiz-riddlebox-api-state"),
    path("riddlebox/api/submit/", api_quiz_submit, {"flavor": "riddlebox"}, name="quiz-riddlebox-api-submit"),

    path("quotechain/", quiz_index, {"flavor": "quotechain"}, name="quiz-quotechain"),
    path("quotechain/api/state/", api_quiz_state, {"flavor": "quotechain"}, name="quiz-quotechain-api-state"),
    path("quotechain/api/submit/", api_quiz_submit, {"flavor": "quotechain"}, name="quiz-quotechain-api-submit"),

    path("timetraveler/", quiz_index, {"flavor": "timetraveler"}, name="quiz-timetraveler"),
    path("timetraveler/api/state/", api_quiz_state, {"flavor": "timetraveler"}, name="quiz-timetraveler-api-state"),
    path("timetraveler/api/submit/", api_quiz_submit, {"flavor": "timetraveler"}, name="quiz-timetraveler-api-submit"),

    path("bluffmaster/", quiz_index, {"flavor": "bluffmaster"}, name="quiz-bluffmaster"),
    path("bluffmaster/api/state/", api_quiz_state, {"flavor": "bluffmaster"}, name="quiz-bluffmaster-api-state"),
    path("bluffmaster/api/submit/", api_quiz_submit, {"flavor": "bluffmaster"}, name="quiz-bluffmaster-api-submit"),

    path("symbolmatch/", quiz_index, {"flavor": "symbolmatch"}, name="quiz-symbolmatch"),
    path("symbolmatch/api/state/", api_quiz_state, {"flavor": "symbolmatch"}, name="quiz-symbolmatch-api-state"),
    path("symbolmatch/api/submit/", api_quiz_submit, {"flavor": "symbolmatch"}, name="quiz-symbolmatch-api-submit"),

    # Bilim O'yinining har bir flavori uchun alohida yo'l ochilmaydi — joker
    # endpointi bitta, flavor manzilning o'zidan olinadi.
    path("api/quiz/<str:flavor>/joker/", api_quiz_joker, name="quiz-api-joker"),

    path("api/games/status/", api_games_status, name="games-api-status"),

    path("api/track/event/", api_track_event, name="track-event"),
]
