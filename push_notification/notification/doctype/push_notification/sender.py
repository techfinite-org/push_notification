import json
import time
import requests
import frappe
from google.auth.transport.requests import Request
from google.oauth2 import service_account
import re
from bs4 import BeautifulSoup


class Sender:
    def __init__(self, doc, send_to, title, message, channel=0, message_type="notification", data_message=""):
        self.doc = doc
        self.title = title
        self.message = message
        self.channel = channel
        self.send_to = send_to
        self.message_type = message_type
        self.data_message = data_message
        self.tokens = []
        self.raise_exception = False

    def load_settings(self):
        self.settings = frappe.get_doc("FCM Settings")

    def get_token(self):
        token_names = frappe.get_all("FCM Token", filters={"user": self.user, "active": 1}, pluck="name")
        if not token_names:
            raise ValueError(f"No FCM tokens for user {self.user}")
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

        if self.settings.android_custom_payload:
            android.update(self.settings.android_custom_payload)
        if self.settings.ios_custom_payload:
            apns.update(self.settings.ios_custom_payload)

        return android, apns

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

        if self.channel:
            self.channel = self.send_to.lower().replace(" ", "-") if self.send_to != "All Users" else "all_notifications"
            base_message["topic"] = f"{self.channel}_{get_hostname()}"
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
                    self._send_request(url, headers, message)
                except Exception as e:
                    self.raise_exception = True
                    frappe.log_error(
                        title="Push Notification Sender",
                        message=f"Error while sending the notification for the user {self.send_to}: {e}"
                    )
        else:
            self._send_request(url, headers, message)

    def _send_request(self, url, headers, payload):
        res = requests.post(url, headers=headers, data=json.dumps(payload))
        if res.status_code != 200:
            raise ValueError(f"{res.status_code}\n{res.text}\n{payload}")

    def send(self):
        self.load_settings()
        if not self.settings.enabled:
            raise ValueError("FCM Settings not enabled")
        headers = self.build_headers()
        message = self.prepare_message()
        self.dispatch(headers, message)
        if self.raise_exception:
            raise Exception(f"Error while sending notification for user {self.user} — check error log")


@frappe.whitelist()
def send(**kwargs):
    try:
        Sender(**kwargs).send()
    except Exception as e:
        frappe.log_error(title="Push Notification Sender", message=str(e))


@frappe.whitelist()
def get_hostname():
    host_name = frappe.get_doc("FCM Settings").site
    if not host_name:
        frappe.throw("Site not found in FCM Settings")
    return host_name
