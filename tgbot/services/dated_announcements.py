"""Owner-approved announcements, each sent once on its date at 11:00 to the
groups and to every registered user (tasks.send_dated_announcement).

Every outgoing text is approved by the owner before it is added here, so the
texts are fixed, not generated. Add an entry under a new date to schedule the
next one; past dates are never sent again.
"""
import datetime as _dt

ANNOUNCEMENTS = {
    # 2026-10-26: the small-changes announcement was sent by hand right after
    # midnight instead (owner's request, a shorter colloquial text, through
    # internal/ops/broadcast campaign changes_2026_10_26), so the 11:00 entry
    # was removed to avoid sending it twice.
}


def announcement_for(date):
    return ANNOUNCEMENTS.get(date)
