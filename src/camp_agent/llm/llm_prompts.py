_CONTEXT = (
    "You help triage messages sent by guests of a holiday camp to its 24x7 assistant."
    " Personal details in the message are masked as [ref], [email] and [phone]."
)

VERIFY = (
    f"{_CONTEXT} Decide whether the message is a genuine guest message, spam, or too unclear"
    " to act on. Spam is advertising, links to unrelated sites, or abuse. Unclear is a message"
    " with no identifiable request or question, such as random letters or 'it's broken'"
    " with no hint of what is broken."
)

SPLIT = (
    f"{_CONTEXT} Split the message into its separate intents: one question, one fault, one"
    " request or one complaint each. Keep each intent in the guest's own words. A message with"
    " one intent gives a list of one."
)

CLASSIFY = (
    f"{_CONTEXT} Classify one guest intent."
    " category: maintenance for faults in the cabin (heating, hot water, leaks, electrics),"
    " housekeeping for cleaning and supplies, restaurant for tables, information for questions,"
    " refund, compensation, cabin_move or safety_close_out for those requests, otherwise other."
    " route: question for a question the camp guide can answer, fault for a fault or"
    " housekeeping need, table for a restaurant booking, money for refunds, compensation,"
    " cabin moves and anything else a person must decide."
    " urgency: urgent for no hot water, no heating in cold weather, leaks or anything unsafe;"
    " can_wait for routine requests such as towels; otherwise normal."
)
