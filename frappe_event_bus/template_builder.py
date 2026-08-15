"""Turn doctype metadata into a field tree, and a field selection into Jinja.

Kept free of DB writes so the classification and generation logic can be unit
tested directly, in the same spirit as ``rendering.py``.
"""

from __future__ import annotations

from typing import Any

import frappe

#: Fieldtypes that carry no data — layout only.
LAYOUT_FIELDTYPES = frozenset(
	{"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Fold", "Image"}
)

#: Fieldtypes that must never reach a broker.
FORBIDDEN_FIELDTYPES = frozenset({"Password"})

#: Fieldtypes whose value is a file URL the consumer probably cannot fetch.
FLAGGED_FIELDTYPES = frozenset({"Attach", "Attach Image"})

#: Fieldtypes that hold child rows.
TABLE_FIELDTYPES = frozenset({"Table", "Table MultiSelect"})

#: Frappe internals that are rarely meaningful in a published message.
INTERNAL_FIELDNAMES = frozenset(
	{"_user_tags", "_comments", "_assign", "_liked_by", "amended_from", "docstatus", "idx"}
)


def classify_field(df: dict[str, Any]) -> dict[str, Any]:
	"""Decide whether a DocField may be published, and whether to pre-tick it.

	Args:
		df: A DocField as a plain dict (``fieldname``, ``fieldtype``, ``label``,
			optionally ``permlevel``).

	Returns:
		Dict with ``fieldname``, ``label``, ``fieldtype``, ``selectable``,
		``default_selected`` and an optional human-readable ``note``.
	"""
	fieldname = df.get("fieldname") or ""
	fieldtype = df.get("fieldtype") or ""
	base = {
		"fieldname": fieldname,
		"label": df.get("label") or fieldname,
		"fieldtype": fieldtype,
		"selectable": True,
		"default_selected": True,
		"note": None,
	}

	if fieldtype in FORBIDDEN_FIELDTYPES:
		return {
			**base,
			"selectable": False,
			"default_selected": False,
			"note": frappe._("Password field — never published"),
		}

	if int(df.get("permlevel") or 0) > 0:
		return {
			**base,
			"default_selected": False,
			"note": frappe._("Restricted (permlevel {0})").format(df.get("permlevel")),
		}

	if fieldname in INTERNAL_FIELDNAMES:
		return {**base, "default_selected": False, "note": frappe._("Frappe internal field")}

	if fieldtype in FLAGGED_FIELDTYPES:
		return {
			**base,
			"note": frappe._("File URL — private files are not fetchable by the consumer"),
		}

	return base


def build_field_tree(doctype: str) -> dict[str, Any]:
	"""Build a two-level picker tree for ``doctype``.

	Frappe has no grandchild tables, so recursion stops at depth one.

	Args:
		doctype: DocType to introspect.

	Returns:
		Dict with ``doctype``, a list of classified ``fields``, and a list of
		``children``, each carrying its own classified ``fields``.
	"""
	meta = frappe.get_meta(doctype)
	fields: list[dict[str, Any]] = []
	children: list[dict[str, Any]] = []

	for df in meta.fields:
		if df.fieldtype in LAYOUT_FIELDTYPES:
			continue
		if df.fieldtype in TABLE_FIELDTYPES:
			children.append(_build_child(df))
			continue
		fields.append(classify_field(df.as_dict()))

	return {"doctype": doctype, "fields": fields, "children": children}


def _build_child(df: Any) -> dict[str, Any]:
	"""Build one child-table node for a Table DocField."""
	child_meta = frappe.get_meta(df.options)
	return {
		"fieldname": df.fieldname,
		"label": df.label or df.fieldname,
		"child_doctype": df.options,
		"fields": [
			classify_field(cdf.as_dict())
			for cdf in child_meta.fields
			if cdf.fieldtype not in LAYOUT_FIELDTYPES and cdf.fieldtype not in TABLE_FIELDTYPES
		],
	}


#: Frappe's built-in Jinja filter, which is ``frappe.as_json``.
#: NOT Jinja's ``tojson`` — that raises TypeError on Date/Datetime.
JSON_FILTER = "json"


def _value_line(indent: str, key: str, expr: str, last: bool) -> str:
	"""Render one ``"key": {{ expr | json }}`` line with an optional trailing comma."""
	return f'{indent}"{key}": {{{{ {expr} | {JSON_FILTER} }}}}{"" if last else ","}'


def generate_jinja(doctype: str, selection: dict[str, Any]) -> str:
	"""Generate an envelope-plus-data Jinja template for ``selection``.

	Args:
		doctype: The doctype the template is being generated for.
		selection: ``{"fields": [fieldname, ...], "children": {table: [fieldname, ...]}}``

	Returns:
		Jinja source that renders to a JSON object. Every value passes through
		the ``json`` filter so quotes, newlines, ``None`` and dates survive.
	"""
	field_names: list[str] = list(selection.get("fields") or [])
	children: dict[str, list[str]] = {
		table: columns for table, columns in (selection.get("children") or {}).items() if columns
	}

	lines = [
		"{",
		'  "event": {',
		_value_line("    ", "type", "context.event_type", False),
		_value_line("    ", "doctype", "doc.doctype", False),
		_value_line("    ", "name", "doc.name", True),
		"  },",
		'  "data": {',
	]

	total = len(field_names) + len(children)
	emitted = 0

	for fieldname in field_names:
		emitted += 1
		lines.append(_value_line("    ", fieldname, f"doc.{fieldname}", emitted == total))

	for table, columns in children.items():
		emitted += 1
		lines.append(f'    "{table}": [')
		lines.append(f"      {{%- for row in doc.{table} %}}")
		lines.append("      {")
		for index, column in enumerate(columns):
			lines.append(_value_line("        ", column, f"row.{column}", index == len(columns) - 1))
		lines.append('      }{{ "," if not loop.last else "" }}')
		lines.append("      {%- endfor %}")
		lines.append(f'    ]{"" if emitted == total else ","}')

	lines.extend(["  }", "}"])
	return "\n".join(lines)
