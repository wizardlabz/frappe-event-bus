"""Event Bus Message Template controller."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.model.document import Document

from frappe_event_bus.rendering import render_payload


class EventBusMessageTemplate(Document):
	"""A versioned Jinja payload template rendered into JSON messages."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		description: DF.SmallText | None
		enabled: DF.Check
		example_context: DF.Code | None
		example_output: DF.Code | None
		jinja_template: DF.Code
		json_schema: DF.Code | None
		message_type: DF.Data | None
		template_name: DF.Data
		version: DF.Data | None
	# end: auto-generated types

	def render(self, context: dict[str, Any]) -> str:
		"""Render this template with ``context`` into a validated JSON string."""
		return render_payload(self.jinja_template, context, self.json_schema)

	def render_example(self) -> str:
		"""Render using ``example_context`` and store the result in ``example_output``."""
		context = frappe.parse_json(self.example_context) if self.example_context else {}
		output = self.render(context)
		self.example_output = output
		return output

	def validate(self) -> None:
		"""Keep ``example_output`` in sync when an example context is present."""
		if self.example_context:
			try:
				self.render_example()
			except frappe.ValidationError:
				# Don't block saving on a bad example; surface it as a message.
				frappe.msgprint(
					frappe._("Example context could not be rendered; example output not updated."),
					indicator="orange",
				)


@frappe.whitelist()
def render_example_output(template_name: str) -> dict[str, Any]:
	"""Whitelisted preview: render the stored example for a template.

	Returns a dict with ``valid``, ``output`` and optional ``error``.
	"""
	doc: EventBusMessageTemplate = frappe.get_doc("Event Bus Message Template", template_name)
	try:
		output = doc.render_example()
		return {"valid": True, "output": output, "parsed": json.loads(output)}
	except frappe.ValidationError as exc:
		return {"valid": False, "error": str(exc)}
