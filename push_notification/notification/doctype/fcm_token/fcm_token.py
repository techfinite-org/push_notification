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
            self.name = f"{user}-{self.device}"
            self.user = user
        except Exception as e:
            frappe.log_error(title="FCM Token", message=str(e))

    def on_update(self):
        device = frappe.db.sql(
            f"SELECT device FROM `tabFCM Token` WHERE name = '{self.name}'",
            as_dict=True
        )
        if device:
            device = device[0].get("device")
            if device and device != self.device:
                self.rename(name=f"{self.user}-{self.device}", force=True)
