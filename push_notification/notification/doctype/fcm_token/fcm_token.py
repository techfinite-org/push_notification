# Copyright (c) 2025, Techfinite Systems and contributors
# License: See license.txt

import frappe
from frappe.model.document import Document


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
