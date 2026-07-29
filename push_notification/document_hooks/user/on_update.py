import frappe


def get_fcm_ids(user):
    return frappe.get_all("FCM Token", filters={"user": user}, pluck="name")


def update_fcm_token_status(user, active):
    fcm_ids = get_fcm_ids(user)
    if not fcm_ids:
        return
    frappe.db.sql(
        "UPDATE `tabFCM Token` SET active = %s WHERE user = %s",
        (active, user),
        auto_commit=True,
    )


def disable_fcm_token(doc, method):
    if doc.enabled:
        return
    update_fcm_token_status(doc.name, 0)


def enable_fcm_token(doc, method):
    if not doc.enabled:
        return
    update_fcm_token_status(doc.name, 1)
