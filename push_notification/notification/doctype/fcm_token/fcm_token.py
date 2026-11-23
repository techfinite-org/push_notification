# Copyright (c) 2025, Techfinite Systems and contributors
# License: See license.txt

import frappe
from frappe.model.document import Document


@frappe.whitelist()
def get_user_topics():
    """
    Return the FCM topic names the calling user should subscribe to.

    Called by the mobile app immediately after login so it subscribes to the
    correct role-based topics without constructing topic strings client-side.
    The server is the single source of truth for topic naming — the sanitization
    rule, the site segment, and the role set all live here.

    Returns a list of strings, e.g.:
        ["clinical-manager_sleepqure.localhost", "sales-user_sleepqure.localhost"]
    """
    from push_notification.notification.doctype.push_notification.sender import (
        _sanitize_topic_segment,
        get_hostname,
    )

    user = frappe.session.user
    if not user or user == "Guest":
        return []

    try:
        site_segment = _sanitize_topic_segment(get_hostname())
    except Exception:
        # FCM Settings not configured — no topics to subscribe to.
        return []

    # Exclude internal Frappe roles that will never be used as push targets.
    _SKIP_ROLES = frozenset({"Guest", "All", "System Manager"})

    topics = []
    for role in frappe.get_roles(user):
        if role in _SKIP_ROLES:
            continue
        topic_prefix = _sanitize_topic_segment(role.lower())
        topics.append(f"{topic_prefix}_{site_segment}")

    return topics


class FCMToken(Document):

    def get_user_id(self):
        user = frappe.get_all(
            "User",
            or_filters=[
                ["username", "=", self.user],
                ["name", "=", self.user]
            ],
            fields=["name"]
        )
        if not user:
            raise ValueError("User not found")
        if len(user) >= 2:
            raise ValueError("User name must be unique")
        return user[0].name

    def autoname(self):
        try:
            user = self.get_user_id()
            self.user = user
            # Include fcm_settings so the same user+device can have tokens
            # for multiple apps (Firebase projects) without collision
            self.name = f"{user}-{self.device}-{self.fcm_settings}"
        except Exception as e:
            frappe.log_error(title="FCM Token", message=str(e))

    def on_update(self):
        existing = frappe.db.sql(
            "SELECT device, fcm_settings FROM `tabFCM Token` WHERE name = %s",
            self.name,
            as_dict=True,
        )
        if existing:
            row = existing[0]
            if row.get("device") != self.device or row.get("fcm_settings") != self.fcm_settings:
                self.rename(
                    name=f"{self.user}-{self.device}-{self.fcm_settings}",
                    force=True,
                )
