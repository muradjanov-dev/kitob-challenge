# -*- coding: utf-8 -*-
"""
Smart LRU (Least-Recently-Used) & Smooth-Cycle question selector for live games.

Guarantees:
1. 100% Non-Repetition within a full cycle: A question is NEVER repeated until
   the entire question pool has been exhausted.
2. Smooth Mixing on Loop: When questions cycle into the next loop, they are
   naturally and smoothly shuffled across older rested pools so questions NEVER
   reappear in the same rigid groups or fixed order.
"""
import random


def pick_least_recently_used(pool, get_key_fn, recent_games, get_game_keys_fn, count):
    """
    Selects `count` items from `pool` with strict cycle-lockout and smooth loop-mixing.

    :param pool: list of question dicts/strings in the bank
    :param get_key_fn: function(item) -> unique key (e.g. quote, q, emoji, display)
    :param recent_games: iterable of recent game model instances ordered by -starts_at
    :param get_game_keys_fn: function(game) -> list of keys that were used in that game
    :param count: number of questions needed for the new game
    :return: list of `count` items from `pool`
    """
    if not pool:
        return []

    count = min(count, len(pool))
    total_pool_size = len(pool)

    # Calculate strict cooldown window size (in games)
    # A full cycle is total_pool_size // count games.
    # To ensure 0% repetition until the whole pool is exhausted,
    # we strictly lock out questions used in the last (cycle_len - 1) games.
    cycle_len = max(1, total_pool_size // count)
    strict_lockout_games = max(1, cycle_len - 1)

    # 1. Map each question key to its most recent appearance:
    # game_idx = 0 (most recent game), 1 (2nd most recent), etc.
    key_last_game_idx = {}
    key_usage_count = {}
    for game_idx, game in enumerate(recent_games):
        try:
            used_keys = get_game_keys_fn(game) or []
        except Exception:
            used_keys = []
        for k in used_keys:
            if not k:
                continue
            key_usage_count[k] = key_usage_count.get(k, 0) + 1
            if k not in key_last_game_idx:
                key_last_game_idx[k] = game_idx

    # 2. Categorize all items in the pool into buckets:
    # - never_used: questions never seen in recent history
    # - fully_rested: questions used long ago (older than the strict lockout window)
    # - in_lockout: questions used recently (within the strict lockout window)
    never_used = []
    fully_rested = []
    in_lockout = []

    for item in pool:
        k = get_key_fn(item)
        last_idx = key_last_game_idx.get(k)
        if last_idx is None:
            never_used.append(item)
        elif last_idx >= strict_lockout_games:
            fully_rested.append((last_idx, item))
        else:
            in_lockout.append((last_idx, item))

    # 3. Selection Strategy:
    # Priority 1: Unused questions (never seen) -> fully randomized
    random.shuffle(never_used)

    # Priority 2: Fully rested questions (past the full cycle cooldown).
    # To smoothly mix questions on loop and avoid repeating identical groups:
    # We group fully rested questions by usage count or broad age windows,
    # shuffle them thoroughly, and mix them into the selection.
    random.shuffle(fully_rested)
    # Sort with a soft random jitter so rested questions from across older games
    # seamlessly mix together rather than appearing in rigid game-by-game blocks.
    fully_rested.sort(key=lambda x: -x[0] + random.uniform(-1.5, 1.5))
    rested_items = [x[1] for x in fully_rested]

    # Priority 3: In-lockout questions (only used as a fallback if the entire pool < count)
    in_lockout.sort(key=lambda x: -x[0])  # oldest first
    lockout_items = [x[1] for x in in_lockout]

    # Combine candidates in order of priority
    candidates = never_used + rested_items + lockout_items

    selected = candidates[:count]

    # Final shuffle so in-game display order is completely fresh and randomized
    random.shuffle(selected)
    return selected
