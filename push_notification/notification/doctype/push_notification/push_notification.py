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
            # Inject the same whitelisted frappe namespace that Frappe's own
            # Notification doctype exposes — enables frappe.get_doc(),
            # frappe.db.get_value(), frappe.db.exists(), etc. in conditions.
            from frappe.utils.safe_exec import get_safe_globals
            context = {
                "doc": self.event_doc,
                "frappe": get_safe_globals().get("frappe"),
            }
            return frappe.safe_eval(self.condition, None, context)
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Invalid Push Notification Condition")
            raise ValueError(f"Invalid condition: '{self.condition}' - {e}")

    def _render(self, text: str) -> str:
        if not text:
            return ""
        return frappe.render_template(text, {"doc": self.event_doc}) if self.event_doc else text

    def _resolve_recipient(self, field_path: str):
        """
        Resolve a recipient from the event document.

        Examples:
            owner
                -> returns event document owner

            patient
                -> detects Link field
                -> gets target DocType from df.options
                -> loads linked Patient
                -> returns its user_id

            patient.user_id
                -> explicitly traverses Patient and returns user_id

            party (Dynamic Link, e.g. Subscription.party)
                -> resolves target doctype at runtime from the field named in
                   df.options (e.g. "party_type"), then loads and resolves same
                   as a regular Link
        """
        if not field_path or not self.event_doc:
            return None

        parts = field_path.split(".")
        current_doc = self.event_doc

        for index, fieldname in enumerate(parts):
            value = current_doc.get(fieldname)

            if not value:
                return None

            df = current_doc.meta.get_field(fieldname)
            is_last = index == len(parts) - 1

            if is_last:
                if not df:
                    return value

                if df.fieldtype == "Link":
                    if df.options == "User":
                        return value
                    linked_doc = frappe.get_doc(df.options, value)
                    return self._get_linked_user(linked_doc)

                if df.fieldtype == "Dynamic Link":
                    target_doctype = current_doc.get(df.options)
                    if not target_doctype:
                        return None
                    if target_doctype == "User":
                        return value
                    linked_doc = frappe.get_doc(target_doctype, value)
                    return self._get_linked_user(linked_doc)

                return value

            # Intermediate segment: must be a Link or Dynamic Link to keep hopping.
            if not df:
                return None

            if df.fieldtype == "Link":
                if not df.options:
                    return None
                current_doc = frappe.get_doc(df.options, value)
                continue

            if df.fieldtype == "Dynamic Link":
                target_doctype = current_doc.get(df.options)
                if not target_doctype:
                    return None
                current_doc = frappe.get_doc(target_doctype, value)
                continue

            return None

        return None

    def _get_linked_user(self, linked_doc):
        """
        Find the Frappe User associated with a linked document.
        """

        # Standard user-link fields used by Patient, Employee and similar doctypes.
        for fieldname in ("user_id", "user"):
            df = linked_doc.meta.get_field(fieldname)

            if not df:
                continue

            user = linked_doc.get(fieldname)

            if user and frappe.db.exists("User", user):
                return user

        # Optional fallback for doctypes that store only an email address.
        for fieldname in ("email", "email_id", "personal_email"):
            df = linked_doc.meta.get_field(fieldname)

            if not df:
                continue

            email = linked_doc.get(fieldname)

            if not email:
                continue

            user = frappe.db.get_value(
                "User",
                {
                    "email": email,
                    "enabled": 1,
                },
                "name",
            )

            if user:
                return user

        return None


    def render_message(self) -> None:
        self.title = self._render(self.title)
        self.message = self._render(self.message)

        self.resolved_send_to = self.send_to

        if self.recipient_type == "Receiver By Document Field":
            self.resolved_send_to = self._resolve_recipient(self.send_to)

    def get_user_list(self) -> list[str] | bool:
        recipient = getattr(
            self,
            "resolved_send_to",
            self.send_to,
        )

        base_query = "SELECT DISTINCT ts.name FROM `tabUser` ts"
        filters = ["ts.enabled = 1"]
        values = {}

        if self.send_to != "All Users":
            if self.recipient_type == "Channel":
                if self.channel_category == "Role":
                    base_query += """
                        INNER JOIN `tabHas Role` hr
                            ON hr.parent = ts.name
                           AND hr.parenttype = 'User'
                    """
                    filters.append("hr.role = %(channel)s")
                    values["channel"] = self.send_to
                else:
                    base_query += """
                        INNER JOIN `tabEmployee` te
                            ON te.user_id = ts.name
                    """

                    filter_field = (
                        "designation"
                        if self.channel_category == "Designation"
                        else "department"
                    )

                    filters.extend([
                        f"te.`{filter_field}` = %(channel)s",
                        "te.status = 'Active'",
                    ])
                    values["channel"] = self.send_to
            else:
                if not recipient:
                    return False

                filters.append(
                    "(ts.name = %(recipient)s OR ts.email = %(recipient)s)"
                )
                values["recipient"] = recipient

        query = f"{base_query} WHERE {' AND '.join(filters)}"

        users = frappe.db.sql(
            query,
            values=values,
            pluck=True,
        )

        return users or False

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
def trigger_notification(notification_doc_name, event_doctype=None, event_doc_name=None, before_save_data=None):
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
            # Reattach the before-save snapshot captured at hook time so that
            # has_value_changed() in conditions returns the correct result.
            if before_save_data and event_doc:
                event_doc._doc_before_save = frappe.get_doc(before_save_data)
        doc.send(event_doc)
    except Exception as e:
        frappe.log_error(
            title="Push Notification Trigger Error",
            message=f"{frappe.get_traceback()} error: {e}",
        )


@frappe.whitelist()
def enqueue_notification(notification_doc_name, event_doctype=None, event_doc_name=None, before_save_data=None):
    try:
        frappe.enqueue(
            method="push_notification.notification.doctype.push_notification.push_notification.trigger_notification",
            queue="long",
            timeout=3600,
            notification_doc_name=notification_doc_name,
            event_doctype=event_doctype,
            event_doc_name=event_doc_name,
            before_save_data=before_save_data,
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
