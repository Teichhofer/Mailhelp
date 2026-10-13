"""Activity reports (2.2): which dated activities belong to one topic in a period.

A report reads the mailbox without changing it, lets the language model decide
per mail whether it belongs to the topic, extracts the dates of relevant mails
and offers the result for review and as an xlsx list.  It never creates
proposals, Telegram messages or external entries.
"""
