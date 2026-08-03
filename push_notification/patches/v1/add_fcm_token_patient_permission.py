"""
Grant the Patient role access to FCM Token.

The patient mobile app registers its device by writing an FCM Token row and
disables it on logout. Out of the box FCM Token is System Manager only, so
those writes fail with a PermissionError and the device silently never
receives a push.

Healthcare-specific, so it lives in a patch rather than in the shared
fcm_token.json permissions: push_notification is installed on products that
have no Patient role at all. The patch no-ops on those sites.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

DOCTYPE = "FCM Token"
ROLE = "Patient"

# Matches what the role was granted by hand on the live site: the client
# inserts a row on login, flips `active` to 0 on logout, and reads back its
# own row to check registration. `delete` is kept so a client that clears its
# token outright is not broken - dropping it is safe only once the mobile
# side is confirmed to never call delete.
PERMISSIONS = ("read", "write", "create", "delete")


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	# Not a healthcare site - nothing to grant.
	if not frappe.db.exists("Role", ROLE):
		return

	# add_permission() calls setup_custom_perms() first, which copies the
	# doctype's existing DocPerms into Custom DocPerm. The System Manager rule
	# is preserved; we are only adding a row, never replacing the set.
	add_permission(DOCTYPE, ROLE, 0)

	for ptype in PERMISSIONS:
		# validate=False: validate_permissions_for_doctype() re-validates every
		# rule on the doctype and would abort the whole migrate over an
		# unrelated rule someone added by hand in the UI.
		update_permission_property(DOCTYPE, ROLE, 0, ptype, 1, validate=False)

	frappe.clear_cache(doctype=DOCTYPE)

	frappe.logger("push_notification").info(
		f"Granted {ROLE} role {', '.join(PERMISSIONS)} on {DOCTYPE}"
	)
