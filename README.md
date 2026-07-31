# Push Notification

A common Frappe app for sending **Firebase Cloud Messaging (FCM)** push notifications,
built to be shared across multiple Techfinite products (HMS, ERP, HRMS, etc.) — one app,
many Firebase projects, many mobile apps.

---

## Features

- **Multi-app / multi-project** — one backend can drive several mobile apps, each with its
  own Firebase project, via multiple **FCM Settings** records.
- **Event-driven** — fire a notification on any DocType event (`after_insert`, `on_submit`, …)
  with an optional Jinja **condition**.
- **Two recipient modes**
  - **Receiver By Document Field** — send to the user held in a field on the triggering doc
    (e.g. `owner`, `leave_approver`).
  - **Channel** — broadcast to an FCM topic and to every user in a group. Group by
    **Role** (generic, works on any product), **Designation**, or **Department** (HR sites).
- **Per-user device tokens** — one token per user + device + app (`FCM Token`).
- **In-app notification log** — reuses Frappe's core **Notification Log** (bell icon).
- **Deep-link routing** — sends `document_type` / `document_name` in the FCM data payload so
  the mobile app can navigate to the right screen on tap.
- **Resilient sending** — stale (`UNREGISTERED`) tokens auto-deactivate, malformed custom
  payloads are ignored with a log, tokenless users are a benign skip (not an error), and the
  `"*"` doc-event hook is guarded against recursion and missing tables.

---

## Doctypes

| DocType | Type | Purpose |
|---|---|---|
| **FCM Settings** | Multi-record | One per Firebase project / mobile app. Holds service-account path, project name, site, enable flag, HTML sanitize, custom Android/iOS payloads. Named by **App Name**. |
| **FCM Token** | Standard | A user's device token, tied to one FCM Settings (app). Named `{user}-{device}-{app}`. |
| **Push Notification** | Standard | The notification template: which app, event, condition, recipient, message. |

Custom fields added to **Notification Log** (fixtures): `custom_push_notification_status`,
`custom_fcm_settings`.

---

## Installation

```bash
# from your bench directory
bench get-app push_notification <repo-url-or-path>
bench --site <site> install-app push_notification
bench --site <site> migrate
```

Python dependencies (installed automatically): `google-auth`, `requests`, `beautifulsoup4`.

---

## Setup

### 1. Firebase service account
Download a service-account JSON from the Firebase console
(**Project Settings → Service Accounts → Generate new private key**) and place it on the
server, e.g. `sites/<site>/fcm_<app>.json`.

### 2. FCM Settings
Create one **FCM Settings** record per mobile app:

| Field | Example |
|---|---|
| App Name | `SleepQure HMS` |
| Enabled | ✓ |
| FCM Token Path | `/home/frappe/frappe-bench/sites/sleepqure.local/fcm_sleepqure.json` |
| FCM Project Name | `sleepqure-hms` (the Firebase project ID) |
| Site | `sleepqure.local` (used in topic names) |
| Sanitize HTML | ✓ recommended |
| Android / IOS Custom Payload | optional JSON object merged into `message.android` / `message.apns` |

### 3. Device token registration (mobile → backend)
When a user logs in, the mobile app creates an **FCM Token** record (via Frappe REST /
`frappe.client.insert`) with: `user`, `device`, `token`, `fcm_settings` (the App Name),
`active = 1`. Re-register on `onTokenRefresh`; set `active = 0` on logout.

---

## Creating a notification

Desk → **Push Notification** → New:

| Field | Meaning |
|---|---|
| FCM Settings (App) | Which Firebase project to send through |
| DocType Name / Doctype Event | The event that triggers this notification |
| Recipient type | `Receiver By Document Field` or `Channel` |
| Send To | For *Document Field*: a fieldname on the event doc. For *Channel*: a Role / Designation / Department value, or `All Users` |
| Channel Category | (Channel only) `Role`, `Designation`, or `Department` |
| Condition | Optional Jinja, e.g. `doc.status == "Approved"` |
| Title / Message | Jinja templates rendered against `doc` (the event doc) |

Use the **Send** button to fire immediately, or let the configured DocType event trigger it.

---

## How it works

```
DocType event (any doctype)
  → hooks.py doc_events "*" → event_handler.handle_event
      (cached rule map; skips internal doctypes; guards missing tables)
  → matching Push Notification rules enqueued
  → trigger_notification (background worker, reloads docs by name)
      ├─ Receiver By Document Field → create Notification Log per user
      │      → Notification Log on_update hook → Sender (FCM per-token send)
      └─ Channel → Sender (FCM topic send) + create Notification Logs
```

### FCM payload (per-user example)

```json
{
  "message": {
    "token": "<device_token>",
    "notification": { "title": "Leave Submitted", "body": "Pending approval." },
    "data": { "document_type": "Leave Application", "document_name": "HR-LAP-2026-00042" },
    "android": { "ttl": "7200s" },
    "apns": { "headers": { "apns-expiration": "1680372000" } }
  }
}
```

For **Channel** sends, `token` is replaced by `topic`, formatted as
`{group_slug}_{site}` — e.g. role *Nurse* on `sleepqure.local` → `nurse_sleepqure.local`.
Slug rule: lowercased, spaces and FCM-illegal chars → `-`.

---

## Mobile app checklist

1. Register the FCM token after login (include the `fcm_settings` app name).
2. Re-register on `onTokenRefresh`; deactivate on logout.
3. Request notification permission (Android 13+ runtime dialog).
4. For channel notifications, `subscribeToTopic("{group_slug}_{site}")`.
5. On tap, read `data.document_type` + `data.document_name` and navigate.
6. If setting `channel_id` in the Android custom payload, it must match the channel the app
   created (e.g. `high_importance_channel`).

---

## License

MIT
