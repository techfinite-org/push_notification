"""
Migrate FCM Settings from Single DocType to multi-record.

Reads the old single-doc values from `__singles`, creates a named record
called "Default", and points all existing Push Notification records at it.
"""
import frappe


def execute():
    # Read old single-doc values
    rows = frappe.db.sql(
        "SELECT field, value FROM `tabSingles` WHERE doctype = 'FCM Settings'",
        as_dict=True,
    )
    if not rows:
        # Nothing to migrate (fresh install)
        return

    old_values = {row["field"]: row["value"] for row in rows}

    # Skip if a record named "Default" already exists
    if frappe.db.exists("FCM Settings", "Default"):
        return

    frappe.get_doc({
        "doctype": "FCM Settings",
        "app_name": "Default",
        "enabled": int(old_values.get("enabled", 0)),
        "fcm_token_path": old_values.get("fcm_token_path", ""),
        "fcm_project_name": old_values.get("fcm_project_name", ""),
        "site": old_values.get("site", ""),
        "sanitize_html": int(old_values.get("sanitize_html", 0)),
        "send_push_notification_with_system_notification": int(
            old_values.get("send_push_notification_with_system_notification", 0)
        ),
        "android_custom_payload": old_values.get("android_custom_payload", ""),
        "ios_custom_payload": old_values.get("ios_custom_payload", ""),
    }).insert(ignore_permissions=True)

    # Point all existing Push Notification records at the migrated record
    frappe.db.sql(
        "UPDATE `tabPush Notification` SET fcm_settings = 'Default' WHERE fcm_settings IS NULL OR fcm_settings = ''"
    )

    # Clean up old single-doc rows
    frappe.db.sql("DELETE FROM `tabSingles` WHERE doctype = 'FCM Settings'")

    frappe.db.commit()
    frappe.logger("push_notification").info(
        "Migrated FCM Settings single doc → named record 'Default'"
    )
