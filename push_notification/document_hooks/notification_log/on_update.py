import frappe
from ...notification.doctype.push_notification import push_notification_enabled
from ...notification.doctype.push_notification.sender import Sender


@frappe.whitelist()
def trigger_notification(doc):
    if doc.custom_push_notification_status in ["Sent", "Error"]:
        return

    status = "Sent"
    try:
        Sender(doc, doc.for_user, doc.subject, doc.email_content, channel=0).send()
    except Exception as e:
        frappe.log_error(title="Push Notification Sender", message=str(e))
        status = "Error"
    finally:
        doc.custom_push_notification_status = status
        doc.save(ignore_permissions=True)


def send_push_notification(doc, event):
    try:
        if doc.custom_push_notification_status != "Sent Vai Push Notification":
            if not push_notification_enabled() or doc.custom_push_notification_status in ["Sent", "Error"]:
                return

        frappe.enqueue(
            method="push_notification.document_hooks.notification_log.on_update.trigger_notification",
            doc=doc,
            job_name=f"{doc.name}-push-notification",
            timeout=3600,
            queue="long",
        )
    except Exception as e:
        frappe.log_error(
            title="Push Notification Trigger: on_update hook",
            message=f"{frappe.get_traceback()} error: {e}",
        )
