app_name = "push_notification"
app_title = "Push Notification"
app_publisher = "Techfinite Systems"
app_description = "Common FCM push notification app for Techfinite products"
app_email = "it-support@techfinite.com"
app_license = "mit"

doc_events = {
    "*": {
        "before_insert":              "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "after_insert":               "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "before_validate":            "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "validate":                   "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "before_save":                "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "after_save":                 "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "before_submit":              "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "on_submit":                  "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "before_cancel":              "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "on_cancel":                  "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "before_update_after_submit": "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "on_update":                  "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "before_delete":              "push_notification.notification.doctype.push_notification.event_handler.handle_event",
        "on_trash":                   "push_notification.notification.doctype.push_notification.event_handler.handle_event",
    },
    "Notification Log": {
        "on_update": "push_notification.document_hooks.notification_log.on_update.send_push_notification"
    },
    "User": {
        "on_update": [
            "push_notification.document_hooks.user.on_update.disable_fcm_token",
            "push_notification.document_hooks.user.on_update.enable_fcm_token",
        ]
    },
}

fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [["dt", "=", "Notification Log"]]
    }
]
