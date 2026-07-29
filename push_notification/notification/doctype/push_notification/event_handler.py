import frappe
from .push_notification import enqueue_notification

# Frappe internal doctypes that must never trigger push notification logic.
# Hooking into these causes infinite recursion (e.g. Error Log insert → handle_event → log_error → …)
_SKIP_DOCTYPES = frozenset({
    "Error Log",
    "Notification Log",
    "Push Notification",
    "Push Notification Log",
    "Activity Log",
    "Access Log",
    "Route History",
    "Scheduled Job Log",
})


def validate(doc, method):
    if doc.doctype in _SKIP_DOCTYPES:
        return False
    # During migrate/install the table may not exist yet — bail out safely
    if not frappe.db.table_exists("Push Notification"):
        return False
    _method = method.lower().replace("_", " ")
    query = f"""
        SELECT name FROM `tabPush Notification`
        WHERE doctype_name = '{doc.doctype}' AND LOWER(doctype_event) = '{_method}'
    """
    notification_names = frappe.db.sql(query, pluck="name")
    return notification_names if notification_names else False


@frappe.whitelist()
def handle_event(doc, method):
    try:
        notification_names = validate(doc, method)
        if not notification_names:
            return False
        for notification_name in notification_names:
            enqueue_notification(notification_name, doc)
    except Exception as e:
        # Use file logger — never frappe.log_error() here, that would
        # insert an Error Log doc which re-triggers this hook → recursion.
        frappe.logger("push_notification").error(
            f"Push Notification Event Handler | {doc.doctype} | {method} | {e}",
            exc_info=True,
        )
