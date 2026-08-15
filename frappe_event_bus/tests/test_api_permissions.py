"""Whitelisted endpoints must authorize their caller.

``@frappe.whitelist()`` exposes a function over ``/api/method/...`` to every
authenticated user. The desk hides the buttons from users who cannot see the
doctypes, but the HTTP endpoint does not care what the UI renders — so each
endpoint has to check permission itself.

The sharpest case is ``preview_payload``: both ``reference_doctype`` and
``reference_name`` come from the caller, and ``frappe.get_doc`` performs no
permission check of its own. Without an explicit check, any logged-in user
could render an arbitrary document through a template and read its fields back
out of the rendered payload.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus import api
from frappe_event_bus.frappe_event_bus.doctype.event_bus_message_template.event_bus_message_template import (
	render_example_output,
)
from frappe_event_bus.publisher.replay import replay_outbox_message

TEMPLATE = "_Test EB Perm Template"
RULE = "_Test EB Perm Rule"
OUTBOX_USER = "_test_eb_nobody@example.com"
TEMPLATE_READER = "_test_eb_reader@example.com"
READER_ROLE = "_Test EB Template Reader"


def _ensure_user(email: str, roles: list[str]) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "EB Test",
				"send_welcome_email": 0,
			}
		)
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", email)

	user.set("roles", [])
	for role in roles:
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)


def _ensure_role(name: str) -> None:
	if not frappe.db.exists("Role", name):
		frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert(
			ignore_permissions=True
		)


class TestApiPermissions(FrappeTestCase):
	"""Every whitelisted endpoint rejects a caller who lacks the permission."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_role(READER_ROLE)
		# A role that can read templates but has no access to Event Bus Rule,
		# so the two checks in preview_payload can be told apart.
		frappe.permissions.add_permission("Event Bus Message Template", READER_ROLE, 0)
		frappe.permissions.update_permission_property("Event Bus Message Template", READER_ROLE, 0, "read", 1)
		_ensure_user(OUTBOX_USER, ["Blogger"])
		_ensure_user(TEMPLATE_READER, [READER_ROLE])
		frappe.clear_cache()

	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup()
		frappe.get_doc(
			{
				"doctype": "Event Bus Message Template",
				"template_name": TEMPLATE,
				"enabled": 1,
				"jinja_template": '{"name": {{ doc.name | json }}}',
				"example_context": '{"doc": {"name": "EXAMPLE-0001"}}',
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Event Bus Rule",
				"rule_name": RULE,
				"enabled": 0,
				"reference_doctype": "ToDo",
				"event_type": "after_insert",
				"message_template": TEMPLATE,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		self._cleanup()

	def _cleanup(self):
		frappe.delete_doc_if_exists("Event Bus Rule", RULE, force=1)
		frappe.delete_doc_if_exists("Event Bus Message Template", TEMPLATE, force=1)

	def _make_outbox(self) -> str:
		outbox = frappe.get_doc(
			{
				"doctype": "Event Bus Outbox Message",
				"event_rule": RULE,
				"message_template": TEMPLATE,
				"provider": "fake",
				"connection": "c",
				"destination": "d",
				"reference_doctype": "ToDo",
				"reference_document": "TODO-0001",
				"event_type": "after_insert",
				"payload": "{}",
				"status": "Failed",
				"attempt_count": 1,
			}
		).insert(ignore_permissions=True)
		return outbox.name

	# --- preview_payload -----------------------------------------------------

	def test_preview_payload_rejects_a_caller_without_template_access(self):
		frappe.set_user(OUTBOX_USER)
		with self.assertRaises(frappe.PermissionError):
			api.preview_payload(TEMPLATE)

	def test_preview_payload_rejects_a_reference_document_the_caller_cannot_read(self):
		"""The disclosure vector: template access must not grant document access."""
		frappe.set_user(TEMPLATE_READER)
		with self.assertRaises(frappe.PermissionError):
			api.preview_payload(TEMPLATE, reference_doctype="Event Bus Rule", reference_name=RULE)

	def test_preview_payload_still_works_for_an_administrator(self):
		report = api.preview_payload(TEMPLATE)
		self.assertTrue(report["rendered"])

	# --- replay_outbox_message -----------------------------------------------

	def test_replay_rejects_a_caller_without_outbox_write(self):
		name = self._make_outbox()
		frappe.set_user(OUTBOX_USER)
		with self.assertRaises(frappe.PermissionError):
			replay_outbox_message(name)

	def test_replay_still_works_for_an_administrator(self):
		name = self._make_outbox()
		self.assertEqual(replay_outbox_message(name)["status"], "Pending")

	# --- render_example_output -----------------------------------------------

	def test_render_example_output_rejects_a_caller_without_template_access(self):
		frappe.set_user(OUTBOX_USER)
		with self.assertRaises(frappe.PermissionError):
			render_example_output(TEMPLATE)

	def test_render_example_output_still_works_for_an_administrator(self):
		self.assertIn("valid", render_example_output(TEMPLATE))

	# --- already-guarded endpoints keep rejecting ----------------------------

	def test_get_field_tree_rejects_an_unprivileged_caller(self):
		frappe.set_user(OUTBOX_USER)
		with self.assertRaises(frappe.PermissionError):
			api.get_field_tree("ToDo")

	def test_generate_template_rejects_an_unprivileged_caller(self):
		frappe.set_user(OUTBOX_USER)
		with self.assertRaises(frappe.PermissionError):
			api.generate_template("ToDo", {"fields": ["description"], "children": {}})
