import frappe
from .push_notification import enqueue_notification

# Frappe internal doctypes that must never trigger push notification logic.
# Hooking into these causes infinite recursion (e.g. Error Log insert → handle_event → log_error → …)
_SKIP_DOCTYPES = frozenset({
    "Error Log",
    "Notification Log",
    "Push Notification",
    "FCM Token",
    "FCM Settings",
    "Version",
    "Comment",
    "DocShare",
    "Email Queue",
    "Prepared Report",
    "Activity Log",
    "Access Log",
    "Route History",
    "Scheduled Job Log",
})

# Cache key for the {(doctype, event): [names]} lookup map
_CACHE_KEY = "push_notification_rule_map"


def _get_rule_map() -> dict:
    """
    Return a cached {(doctype, event): [push_notification_names]} map.
    Invalidated on PushNotification on_update / on_trash.
    """
    cached = frappe.cache().get_value(_CACHE_KEY)
    if cached is not None:
        return cached

    if not frappe.db.table_exists("Push Notification"):
        return {}

    rows = frappe.db.sql(
        """
        SELECT name, doctype_name, LOWER(doctype_event) AS doctype_event
        FROM `tabPush Notification`
        WHERE disabled = 0
          AND doctype_name IS NOT NULL
          AND doctype_event IS NOT NULL
        """,
        as_dict=True,
    )
    rule_map = {}
    for row in rows:
        key = (row.doctype_name, row.doctype_event)
        rule_map.setdefault(key, []).append(row.name)

    frappe.cache().set_value(_CACHE_KEY, rule_map)
    return rule_map


def invalidate_rule_cache(doc, method):
    """Hook: called on PushNotification on_update and on_trash to bust the cache."""
    frappe.cache().delete_value(_CACHE_KEY)


def validate(doc, method):
    if doc.doctype in _SKIP_DOCTYPES:
        return False

    _method = method.lower().replace("_", " ")

    # Frappe fires on_submit/on_cancel hooks but the UI option labels them
    # "After Submit" / "After Cancel" — translate so the lookup matches.
    _HOOK_ALIAS = {
        "on submit": "after submit",
        "on cancel": "after cancel",
    }
    _method = _HOOK_ALIAS.get(_method, _method)

    rule_map = _get_rule_map()
    return rule_map.get((doc.doctype, _method)) or False


@frappe.whitelist()
def handle_event(doc, method):
    try:
        notification_names = validate(doc, method)
        if not notification_names:
            return False
        # Capture the before-save snapshot while it still exists on the live doc.
        # The background worker reloads the doc fresh (no _doc_before_save), so
        # has_value_changed() would always return True without this.
        before_doc = doc.get_doc_before_save()
        before_save_data = before_doc.as_dict() if before_doc else None

        for notification_name in notification_names:
            enqueue_notification(notification_name, doc.doctype, doc.name, before_save_data=before_save_data)
    except Exception as e:
        # Use file logger — never frappe.log_error() here, that inserts
        # an Error Log doc which re-triggers this hook → infinite recursion.
        frappe.logger("push_notification").error(
            f"Push Notification Event Handler | {doc.doctype} | {method} | {e}",
            exc_info=True,
        )
