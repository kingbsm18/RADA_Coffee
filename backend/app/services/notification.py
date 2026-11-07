"""Strong-alert notifications (rule R12): decide what to send and deliver it.

Single module for both the decision and the delivery channel(s); do not
re-introduce a separate infra/notifier.py unless a second channel needs it.
TODO: implement.
"""
