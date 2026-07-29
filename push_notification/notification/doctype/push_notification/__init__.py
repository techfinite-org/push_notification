import frappe


def push_notification_enabled():
    """Check whether to send push notification alongside system notifications."""
    return frappe.get_cached_value(
        "FCM Settings", None, "send_push_notification_with_system_notification"
    )
