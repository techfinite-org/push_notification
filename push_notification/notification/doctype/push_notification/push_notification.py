# Copyright (c) 2025, Techfinite Systems and contributors
# License: See license.txt

import frappe
from frappe.model.document import Document
from .sender import Sender


class PushNotification(Document):

    def on_update(self):
        from .event_handler import invalidate_rule_cache
        invalidate_rule_cache(self, "on_update")

    def on_trash(self):
        from .event_handler import invalidate_rule_cache
        invalidate_rule_cache(self, "on_trash")

    def validate_condition(self) -> bool:
        if not self.condition:
            return True
        try:
            return frappe.safe_eval(self.condition, None, {"doc": self.event_doc})
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Invalid Push Notification Condition")
            raise ValueError(f"Invalid condition: '{self.condition}' - {e}")

    def _render(self, text: str) -> str:
        if not text:
            return ""
        return frappe.render_template(text, {"doc": self.event_doc}) if self.event_doc else text

    def _resolve_path(self, path: str):
        """
        Resolve a dotted field path against the event doc, hopping through Link
        fields. E.g. 'patient.user_id' loads the linked Patient and returns its
        user_id. A plain 'owner' or 'user' still works (single segment, no hop).
        Returns None if any hop is missing or the field has no value.
        """
        if not path or not self.event_doc:
            return None
        doc = self.event_doc
        parts = path.split(".")
        for i, part in enumerate(parts):
            if doc is None:
                return None
            value = doc.get(part)
            if i == len(parts) - 1:
                return value
            df = doc.meta.get_field(part)
            if not df or not df.options or not value:
                return None
            doc = frappe.get_doc(df.options, value)
        return None

    def render_message(self) -> None:
        self.title = self._render(self.title)
        self.message = self._render(self.message)

        if self.recipient_type == "Receiver By Document Field":
            self.send_to = self._resolve_path(self.send_to)

    def get_user_list(self) -> list[str] | bool:
        base_query = "SELECT ts.name FROM tabUser ts"
        filters = ["ts.enabled = 1"]

        if self.send_to != "All Users":
            if self.recipient_type == "Channel":
                if self.channel_category == "Role":
                    # Generic, app-agnostic grouping — works on any Frappe product
                    # (HMS/ERP/HRMS) since every user has roles via tabHas Role.
                    base_query += " JOIN `tabHas Role` hr ON hr.parent = ts.name AND hr.parenttype = 'User'"
                    filters.append(f"hr.role = {frappe.db.escape(self.send_to)}")
                else:
                    # HR-specific grouping (requires Employee records)
                    base_query += " JOIN `tabEmployee` te ON te.user_id = ts.name"
                    filter_field = "te.designation" if self.channel_category == "Designation" else "te.department"
                    filters.extend([
                        f"{filter_field} = {frappe.db.escape(self.send_to)}",
                        "te.status = 'Active'",
                    ])
            else:
                filters.append(f"ts.email = {frappe.db.escape(self.send_to)}")

        query = f"{base_query} WHERE {' AND '.join(filters)}"
        users = frappe.db.sql(query, pluck="name")
        return users if users else False

    def create_log(self, status: str = "") -> None:
        users = self.get_user_list()
        if not users:
            frappe.log_error(title="Push Notification", message="User not found to send notification")
            return

        from_user = self.event_doc.modified_by if self.event_doc else frappe.session.user
        status = status or "Sent Via Push Notification"
        # Deep-link routing: carry the triggering document so the mobile app can
        # navigate on tap. Empty when triggered manually (no event doc).
        route_doctype = self.event_doc.doctype if self.event_doc else ""
        route_document = self.event_doc.name if self.event_doc else ""
        for user in users:
            frappe.get_doc({
                "doctype": "Notification Log",
                "subject": self.title,
                "email_content": self.message,
                "type": "Alert",
                "for_user": user,
                "from_user": from_user,
                "custom_push_notification_status": status,
                "custom_fcm_settings": self.fcm_settings,
                "document_type": route_doctype,
                "document_name": route_document,
            }).insert(ignore_permissions=True)

    def _send(self) -> None:
        """
        When a Notification Log is created, a push notification will be sent
        using the `on_update` hook via document_hooks/notification_log/on_update.py.
        """
        if self.recipient_type == "Receiver By Document Field":
            self.create_log()
        else:
            try:
                Sender(self, self.send_to, self.title, self.message, 1,
                       settings_name=self.fcm_settings,
                       route_doctype=self.event_doc.doctype if self.event_doc else "",
                       route_document=self.event_doc.name if self.event_doc else "").send()
                self.create_log(status="Sent")
            except Exception as e:
                self.create_log(status="Error")
                raise Exception(e)

    def send(self, event_doc: Document | None = None) -> None:
        self.event_doc = event_doc
        if self.validate_condition():
            self.render_message()
            self._send()


@frappe.whitelist()
def trigger_notification(notification_doc_name, event_doctype=None, event_doc_name=None):
    """
    Reload the event doc inside the worker from doctype+name
    instead of unpickling a stale Document object from Redis.
    """
    try:
        doc = frappe.get_doc("Push Notification", notification_doc_name)
        if doc.disabled:
            return
        event_doc = None
        if event_doctype and event_doc_name:
            event_doc = frappe.get_doc(event_doctype, event_doc_name)
        doc.send(event_doc)
    except Exception as e:
        frappe.log_error(
            title="Push Notification Trigger Error",
            message=f"{frappe.get_traceback()} error: {e}",
        )


@frappe.whitelist()
def enqueue_notification(notification_doc_name, event_doctype=None, event_doc_name=None):
    try:
        frappe.enqueue(
            method="push_notification.notification.doctype.push_notification.push_notification.trigger_notification",
            queue="long",
            timeout=3600,
            notification_doc_name=notification_doc_name,
            event_doctype=event_doctype,
            event_doc_name=event_doc_name,
            job_name=f"{notification_doc_name}_{frappe.utils.now()}",
        )
    except Exception as e:
        frappe.log_error("Notification Queue Error", str(e))


@frappe.whitelist()
def get_doctype_fields(doctype_name):
    """
    Return selectable recipient paths for a doctype:
      - all top-level fields (e.g. 'owner', 'user')
      - one-level Link hops (e.g. 'patient.user_id') so notifications can target
        the user behind a linked record when the doctype has no direct user field.
    """
    try:
        meta = frappe.get_meta(doctype_name)
        fields = []
        for df in meta.fields:
            if not df.fieldname:
                continue
            fields.append(df.fieldname)
            # Expand one level through Link fields
            if df.fieldtype == "Link" and df.options:
                try:
                    linked_meta = frappe.get_meta(df.options)
                except Exception:
                    continue
                for ldf in linked_meta.fields:
                    if ldf.fieldname and ldf.fieldtype in ("Link", "Data"):
                        fields.append(f"{df.fieldname}.{ldf.fieldname}")
        return fields
    except Exception as e:
        frappe.throw(f"Error fetching fields: {str(e)}")
