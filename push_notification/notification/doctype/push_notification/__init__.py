import frappe


def push_notification_enabled():
    """Check whether to send push notification alongside system notifications."""
    name = frappe.db.get_value("FCM Settings", {"enabled": 1}, "name")
    if not name:
        return False
    return frappe.db.get_value(
        "FCM Settings", name, "send_push_notification_with_system_notification"
    )
