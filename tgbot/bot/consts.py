from environs import Env

env = Env()
env.read_env()

ADMIN_GROUP_ID = env.str("ADMIN_GROUP_ID")
CHALLENGE_CHANNEL_ID = env.str("CHALLENGE_CHANNEL_ID")
BOYS_GROUP_ID = env.str("BOYS_GROUP_ID")
GIRLS_GROUP_ID = env.str("GIRLS_GROUP_ID")

# 0 / unset -> None so aiogram drops the param and messages go to the
# main group (works for non-forum supergroups).
def _thread(name):
    return env.int(name, 0) or None

TECHNICAL_SUPPORT_THREAD_ID = _thread("TECHNICAL_SUPPORT_THREAD_ID")
MESSAGE_THREAD_ID = _thread("MESSAGE_THREAD_ID")
PAYMENT_THREAD_ID = _thread("PAYMENT_THREAD_ID")
GAMES_THREAD_ID = _thread("GAMES_THREAD_ID")
B_BOYS_THREAD_ID = _thread("B_BOYS_THREAD_ID")
B_GIRLS_THREAD_ID = _thread("B_GIRLS_THREAD_ID")
D_BOYS_THREAD_ID = _thread("D_BOYS_THREAD_ID")
D_GIRLS_THREAD_ID = _thread("D_GIRLS_THREAD_ID")
C_BOYS_THREAD_ID = _thread("C_BOYS_THREAD_ID")
C_GIRLS_THREAD_ID = _thread("C_GIRLS_THREAD_ID")
E_BOYS_THREAD_ID = _thread("E_BOYS_THREAD_ID")
E_GIRLS_THREAD_ID = _thread("E_GIRLS_THREAD_ID")

REFERRAL_THRESHOLD = 1
REFERRAL_CODE_LENGTH = 8
