import json
import time
import requests
import frappe
from google.auth.transport.requests import Request
from google.oauth2 import service_account
import re
from bs4 import BeautifulSoup

# FCM topic names only allow [a-zA-Z0-9-_.~%] — strip everything else
_TOPIC_UNSAFE = re.compile(r"[^a-zA-Z0-9\-_.~%]")


def _sanitize_topic_segment(segment: str) -> str:
    """Replace characters illegal in FCM topic names with a hyphen."""
    return _TOPIC_UNSAFE.sub("-", segment)


def _parse_custom_payload(raw, field_name: str) -> dict:
    """
    Accept a dict or a JSON string from a Code field.
    Logs a warning and returns {} on malformed input so a bad config
    never silently crashes every notification send.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object")
        return parsed
    except Exception as e:
        frappe.logger("push_notification").warning(
            f"FCM Settings: {field_name} contains invalid JSON — ignored. Error: {e}"
        )
        return {}


class Sender:
    def __init__(self, doc, send_to, title, message, channel=0, message_type="notification",
                 data_message="", settings_name=None, route_doctype="", route_document=""):
        self.doc = doc
        self.title = title
        self.message = message
        self.send_to = send_to
        self.topic = None          # set in prepare_message when channel mode
        self.channel = channel
        self.message_type = message_type
        self.data_message = data_message
        self.settings_name = settings_name
        # Deep-link routing: mobile app reads these from the FCM data block on tap
        self.route_doctype = route_doctype or ""
        self.route_document = route_document or ""
        self.tokens = []
        self.raise_exception = False
        self.skipped_no_device = False  # True when user has no active FCM tokens

    def load_settings(self):
        if self.settings_name:
            self.settings = frappe.get_doc("FCM Settings", self.settings_name)
        else:
            # Fallback for direct Sender() calls not tied to a Push Notification template
            name = frappe.db.get_value("FCM Settings", {"enabled": 1}, "name")
            if not name:
                raise ValueError("No enabled FCM Settings found")
            self.settings = frappe.get_doc("FCM Settings", name)

    def get_token(self):
        filters = {"user": self.user, "active": 1}
        if self.settings_name:
            filters["fcm_settings"] = self.settings_name
        token_names = frappe.get_all("FCM Token", filters=filters, pluck="name")
        if not token_names:
            # Benign — user simply has no registered device for this app; not an error
            return []
        return [frappe.get_doc("FCM Token", name).get_password("token") for name in token_names]

    def get_access_token(self):
        creds = service_account.Credentials.from_service_account_file(
            self.settings.fcm_token_path,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        creds.refresh(Request())
        return creds.token

    def extract_plain_text(self, html: str) -> str:
        if not isinstance(html, str):
            return ""
        text = BeautifulSoup(html, "html.parser").get_text(separator=" ")
        text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def build_headers(self):
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json; UTF-8",
        }

    def render_notification(self):
        return {
            "title": self.extract_plain_text(self.title) if self.settings.sanitize_html else self.title,
            "body": self.extract_plain_text(self.message) if self.settings.sanitize_html else self.message,
        }

    def build_payload(self):
        android = {"ttl": "7200s", "collapse_key": str(int(time.time()))}
        apns = {"headers": {"apns-expiration": "1680372000"}}

        android.update(_parse_custom_payload(self.settings.android_custom_payload, "Android Custom Payload"))
        apns.update(_parse_custom_payload(self.settings.ios_custom_payload, "IOS Custom Payload"))

        return android, apns

    def build_route_data(self) -> dict:
        """FCM data payload for deep-linking. All values MUST be strings."""
        data = {}
        if self.route_doctype:
            data["document_type"] = str(self.route_doctype)
        if self.route_document:
            data["document_name"] = str(self.route_document)
        return data

    def prepare_message(self):
        android, apns = self.build_payload()
        base_message = {
            "android": android,
            "apns": apns,
        }
        if self.message_type == "data_message":
            base_message["data"] = self.data_message
        else:
            base_message["notification"] = self.render_notification()
            # Attach routing keys alongside the notification so taps deep-link.
            # FCM allows notification + data in the same message.
            route_data = self.build_route_data()
            if route_data:
                base_message["data"] = route_data

        if self.channel:
            if self.send_to == "All Users":
                topic_prefix = "all_notifications"
            else:
                topic_prefix = _sanitize_topic_segment(self.send_to.lower())
            site_segment = _sanitize_topic_segment(get_hostname())
            self.topic = f"{topic_prefix}_{site_segment}"
            base_message["topic"] = self.topic
        else:
            self.user = self.send_to
            self.tokens = self.get_token()

        return {"message": base_message}

    def dispatch(self, headers, message):
        url = f"https://fcm.googleapis.com/v1/projects/{self.settings.fcm_project_name}/messages:send"
        if self.tokens:
            for token in self.tokens:
                try:
                    message["message"]["token"] = token
                    self._send_request(url, headers, message, token)
                except Exception as e:
                    self.raise_exception = True
                    frappe.log_error(
                        title="Push Notification Sender",
                        message=f"Error while sending the notification for the user {self.send_to}: {e}"
                    )
        else:
            self._send_request(url, headers, message)

    def _send_request(self, url, headers, payload, token=None):
        res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        if res.status_code == 200:
            return
        # Auto-deactivate stale/unregistered tokens so they stop generating errors
        if res.status_code == 404 and token:
            frappe.db.set_value("FCM Token", {"token": token}, "active", 0)
            frappe.db.commit()
            frappe.logger("push_notification").info(
                f"FCM Token deactivated (UNREGISTERED): user={self.send_to}"
            )
            return
        raise ValueError(f"{res.status_code}\n{res.text}\n{payload}")

    def send(self):
        self.load_settings()
        if not self.settings.enabled:
            raise ValueError("FCM Settings not enabled")
        headers = self.build_headers()
        message = self.prepare_message()

        # No registered devices — skip silently, not an error
        if not self.tokens and not self.topic:
            self.skipped_no_device = True
            frappe.logger("push_notification").info(
                f"Push notification skipped — no active FCM tokens for user {self.send_to}"
            )
            return

        self.dispatch(headers, message)
        if self.raise_exception:
            raise Exception(f"Error while sending notification for user {self.send_to} — check error log")


@frappe.whitelist()
def send(**kwargs):
    try:
        Sender(**kwargs).send()
    except Exception as e:
        frappe.log_error(title="Push Notification Sender", message=str(e))


@frappe.whitelist()
def get_hostname(settings_name=None):
    if settings_name:
        host_name = frappe.db.get_value("FCM Settings", settings_name, "site")
    else:
        host_name = frappe.db.get_value("FCM Settings", {"enabled": 1}, "site")
    if not host_name:
        frappe.throw("Site not found in FCM Settings")
    return host_name
