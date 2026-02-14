import random


DECLINE_MESSAGES = [
    "They already found someone, but I can keep looking for you.",
    "That spot filled up, want me to keep searching?",
    "They’re not available anymore. I can ask a few more people.",
    "Looks like that group is full. Want me to keep looking?",
]


def polite_decline() -> str:
    return random.choice(DECLINE_MESSAGES)
