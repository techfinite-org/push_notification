# Copyright (c) 2025, Techfinite Systems and contributors
# License: See license.txt

import frappe
from frappe.model.document import Document
from .sender import Sender


class PushNotification(Document):

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

    def render_message(self) -> None:
        self.title = self._render(self.title)
        self.message = self._render(self.message)

        if self.recipient_type == "Receiver By Document Field":
            self.send_to = getattr(self.event_doc, self.send_to, None)

    def get_user_list(self) -> list[str] | bool:
        base_query = "SELECT ts.name FROM tabUser ts"
        filters = ["ts.enabled = 1"]

        if self.send_to != "All Users":
            if self.recipient_type == "Channel":
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
        status = status or "Sent Vai Push Notification"
        for user in users:
            frappe.get_doc({
                "doctype": "Notification Log",
                "subject": self.title,
                "email_content": self.message,
                "type": "Alert",
                "for_user": user,
                "from_user": from_user,
                "custom_push_notification_status": status,
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
                Sender(self, self.send_to, self.title, self.message, 1).send()
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
def trigger_notification(notification_doc_name, event_doc=None):
    try:
        doc = frappe.get_doc("Push Notification", notification_doc_name)
        if not doc.disabled:
            doc.send(event_doc)
    except Exception as e:
        frappe.log_error(
            title="Push Notification Trigger Error",
            message=f"{frappe.get_traceback()} error: {e}",
        )


@frappe.whitelist()
def enqueue_notification(notification_doc_name, event_doc=None):
    try:
        frappe.enqueue(
            method="push_notification.notification.doctype.push_notification.push_notification.trigger_notification",
            queue="long",
            timeout=3600,
            notification_doc_name=notification_doc_name,
            event_doc=event_doc,
            job_name=f"{notification_doc_name}_{frappe.utils.now()}",
        )
    except Exception as e:
        frappe.log_error("Notification Queue Error", str(e))


@frappe.whitelist()
def get_doctype_fields(doctype_name):
    try:
        meta = frappe.get_meta(doctype_name)
        return [df.fieldname for df in meta.fields if df.fieldname]
    except Exception as e:
        frappe.throw(f"Error fetching fields: {str(e)}")
