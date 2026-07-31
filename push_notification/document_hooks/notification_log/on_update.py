import frappe
from ...notification.doctype.push_notification import push_notification_enabled
from ...notification.doctype.push_notification.sender import Sender

# Statuses set by push_notification.py.create_log() that mean
# "this log was created by us and needs a real FCM send"
_PENDING_STATUS = "Sent Via Push Notification"


@frappe.whitelist()
def trigger_notification(doc_name):
    """
    Runs inside a background worker.
    Re-reads the Notification Log by name so we never unpickle a stale doc.
    """
    doc = frappe.get_doc("Notification Log", doc_name)

    if doc.custom_push_notification_status in ["Sent", "Error", "No Device"]:
        return

    status = "Sent"
    try:
        sender = Sender(
            doc, doc.for_user, doc.subject, doc.email_content,
            channel=0, settings_name=doc.custom_fcm_settings or None,
            route_doctype=doc.document_type or "",
            route_document=doc.document_name or "",
        )
        sender.send()
        if sender.skipped_no_device:
            status = "No Device"
    except Exception as e:
        frappe.log_error(title="Push Notification Sender", message=str(e))
        status = "Error"
    finally:
        # Use set_value to avoid re-triggering the on_update hook via doc.save()
        frappe.db.set_value(
            "Notification Log",
            doc_name,
            "custom_push_notification_status",
            status,
            update_modified=False,
        )
        frappe.db.commit()


def send_push_notification(doc, event):
    try:
        if doc.custom_push_notification_status != _PENDING_STATUS:
            if not push_notification_enabled() or doc.custom_push_notification_status in ["Sent", "Error", "No Device"]:
                return

        frappe.enqueue(
            method="push_notification.document_hooks.notification_log.on_update.trigger_notification",
            doc_name=doc.name,
            job_name=f"{doc.name}-push-notification",
            timeout=3600,
            queue="long",
        )
    except Exception as e:
        frappe.log_error(
            title="Push Notification Trigger: on_update hook",
            message=f"{frappe.get_traceback()} error: {e}",
        )
