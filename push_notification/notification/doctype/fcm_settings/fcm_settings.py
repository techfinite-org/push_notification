# Copyright (c) 2025, Techfinite Systems and contributors
# License: See license.txt

import json
import re
import frappe
from frappe.model.document import Document

_TOPIC_UNSAFE = re.compile(r"[^a-zA-Z0-9\-_.~%]")


class FCMSettings(Document):

    def validate(self):
        self._validate_json_payload("android_custom_payload", "Android Custom Payload")
        self._validate_json_payload("ios_custom_payload", "IOS Custom Payload")
        self._validate_site()

    def _validate_json_payload(self, fieldname: str, label: str):
        value = self.get(fieldname)
        if not value:
            return
        if isinstance(value, dict):
            return
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                frappe.throw(f"<b>{label}</b>: must be a JSON object (got {type(parsed).__name__})")
        except json.JSONDecodeError as e:
            frappe.throw(f"<b>{label}</b>: invalid JSON — {e}")

    def _validate_site(self):
        site = self.site or ""
        if self.enabled and _TOPIC_UNSAFE.search(site):
            frappe.throw(
                f"<b>Site</b> value <code>{site}</code> contains characters that are "
                f"illegal in FCM topic names. Use only letters, numbers, hyphens, "
                f"underscores, dots, tildes, or percent-encoded chars."
            )
