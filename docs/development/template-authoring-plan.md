# Template Authoring & Form Layout — Implementation Plan

**Spec:** [template-authoring-design.md](template-authoring-design.md)
**Goal:** Give Message Templates a doctype-aware field picker that generates a
valid Jinja starting point, bind templates to a doctype optionally, and split
config-heavy doctypes into tabs.

**Architecture:** A pure `template_builder` module turns doctype meta into a
field tree and a selection into Jinja text. A whitelisted API exposes both. A
Vue 3 dialog (same pattern as the existing `payload_preview.bundle.js`) drives
it and writes into the always-editable `jinja_template` field. Tabs are pure
doctype-JSON changes.

**Tech Stack:** Frappe v15, Python 3.12, Vue 3 via esbuild bundle, pytest-style
`FrappeTestCase`.

## Global Constraints

- Values in generated Jinja go through Frappe's built-in **`| json`** filter
  (`frappe.as_json`). Never Jinja's `tojson` — it raises `TypeError` on Date
  and Datetime.
- `render_payload` stays the only runtime payload builder. No second path.
- `jinja_template` is never read-only. The picker writes into it and holds no
  further relationship with it.
- `applies_to_doctype` is nullable. Blank = generic template, works as today.
- Existing Section Breaks stay. Tab Breaks are inserted above them.
- No new doctypes and no child tables.
- Conventional Commits. No Claude attribution in author, message, or trailers.

## File Structure

| File | Responsibility |
|---|---|
| `frappe_event_bus/template_builder.py` | **Create.** Pure: meta → field tree, selection → Jinja. No DB writes. |
| `frappe_event_bus/tests/test_template_builder.py` | **Create.** Unit tests for the above. |
| `frappe_event_bus/api.py` | **Modify.** Add two whitelisted endpoints. |
| `.../doctype/event_bus_message_template/event_bus_message_template.json` | **Modify.** Add `applies_to_doctype`; add Tab Breaks. |
| `.../doctype/event_bus_message_template/event_bus_message_template.py` | **Modify.** Type hint for the new field. |
| `.../doctype/event_bus_rule/event_bus_rule.py` | **Modify.** Cross-check validation. |
| `.../doctype/event_bus_rule/event_bus_rule.js` | **Create.** Link filter + quick-entry prefill. |
| `.../doctype/event_bus_rule/event_bus_rule.json` | **Modify.** Tab Breaks. |
| `.../doctype/event_bus_outbox_message/event_bus_outbox_message.json` | **Modify.** Tab Breaks. |
| `frappe_event_bus/public/js/template_builder.bundle.js` | **Create.** Vue 3 picker dialog. |
| `frappe_event_bus/hooks.py` | **Modify.** Register the new bundle. |
| *(rabbitmq repo)* `rabbitmq_event_bus_connection.json`, `rabbitmq_event_bus_destination.json` | **Modify.** Tab Breaks. |

---

## Task 1: Field tree from doctype meta

**Files:**
- Create: `frappe_event_bus/template_builder.py`
- Create: `frappe_event_bus/tests/test_template_builder.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `classify_field(df: dict) -> dict` and
  `build_field_tree(doctype: str) -> dict`. Tree shape:
  ```python
  {
    "doctype": "ToDo",
    "fields": [
      {"fieldname": "description", "label": "Description", "fieldtype": "Text Editor",
       "selectable": True, "default_selected": True, "note": None},
    ],
    "children": [
      {"fieldname": "items", "label": "Items", "child_doctype": "ToDo Item",
       "fields": [ ...same shape... ]},
    ],
  }
  ```

- [ ] **Step 1: Write the failing test**

```python
# frappe_event_bus/tests/test_template_builder.py
"""Unit tests for the doctype-aware template builder."""

from __future__ import annotations

import unittest

from frappe_event_bus.template_builder import classify_field


class TestClassifyField(unittest.TestCase):
	"""Field classification is pure: a DocField dict in, a decision out."""

	def test_ordinary_field_is_selected_by_default(self):
		out = classify_field({"fieldname": "customer", "fieldtype": "Link", "label": "Customer"})
		self.assertTrue(out["selectable"])
		self.assertTrue(out["default_selected"])
		self.assertIsNone(out["note"])

	def test_password_is_never_selectable(self):
		out = classify_field({"fieldname": "password", "fieldtype": "Password", "label": "Password"})
		self.assertFalse(out["selectable"])
		self.assertFalse(out["default_selected"])
		self.assertIn("never published", out["note"])

	def test_permlevel_field_is_opt_in(self):
		out = classify_field({"fieldname": "cost", "fieldtype": "Currency", "label": "Cost", "permlevel": 1})
		self.assertTrue(out["selectable"])
		self.assertFalse(out["default_selected"])
		self.assertIn("permlevel 1", out["note"])

	def test_internal_fieldname_is_opt_in(self):
		out = classify_field({"fieldname": "amended_from", "fieldtype": "Link", "label": "Amended From"})
		self.assertTrue(out["selectable"])
		self.assertFalse(out["default_selected"])

	def test_attach_is_selected_but_flagged(self):
		out = classify_field({"fieldname": "logo", "fieldtype": "Attach Image", "label": "Logo"})
		self.assertTrue(out["default_selected"])
		self.assertIn("private", out["note"].lower())
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && \
   bench --site dev.localhost run-tests --app frappe_event_bus \
   --module frappe_event_bus.tests.test_template_builder'
```

Expected: `ModuleNotFoundError: No module named 'frappe_event_bus.template_builder'`

- [ ] **Step 3: Write `classify_field` and the constants**

```python
# frappe_event_bus/template_builder.py
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

#: Frappe internals that are rarely meaningful in a published message.
INTERNAL_FIELDNAMES = frozenset(
	{"_user_tags", "_comments", "_assign", "_liked_by", "amended_from", "docstatus", "idx"}
)


def classify_field(df: dict[str, Any]) -> dict[str, Any]:
	"""Decide whether a DocField may be published, and whether to pre-tick it."""
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
		return {**base, "selectable": False, "default_selected": False,
		        "note": frappe._("Password field — never published")}

	if int(df.get("permlevel") or 0) > 0:
		return {**base, "default_selected": False,
		        "note": frappe._("Restricted (permlevel {0})").format(df.get("permlevel"))}

	if fieldname in INTERNAL_FIELDNAMES:
		return {**base, "default_selected": False, "note": frappe._("Frappe internal field")}

	if fieldtype in FLAGGED_FIELDTYPES:
		return {**base, "note": frappe._("File URL — private files are not fetchable by the consumer")}

	return base
```

- [ ] **Step 4: Run the tests and confirm they pass**

Same command as Step 2. Expected: 5 passed.

- [ ] **Step 5: Write the failing test for `build_field_tree`**

```python
# append to frappe_event_bus/tests/test_template_builder.py
from frappe.tests.utils import FrappeTestCase

from frappe_event_bus.template_builder import build_field_tree


class TestBuildFieldTree(FrappeTestCase):
	"""Tree construction reads live meta, so it needs a site."""

	def test_layout_fieldtypes_are_omitted(self):
		tree = build_field_tree("ToDo")
		types = {f["fieldtype"] for f in tree["fields"]}
		self.assertFalse(types & {"Section Break", "Column Break", "Tab Break"})

	def test_real_fields_are_present(self):
		tree = build_field_tree("ToDo")
		self.assertIn("description", {f["fieldname"] for f in tree["fields"]})

	def test_child_tables_are_nested_not_inlined(self):
		tree = build_field_tree("DocType")
		self.assertNotIn("Table", {f["fieldtype"] for f in tree["fields"]})
		children = {c["fieldname"] for c in tree["children"]}
		self.assertIn("fields", children)

	def test_child_table_rows_are_classified_too(self):
		tree = build_field_tree("DocType")
		child = next(c for c in tree["children"] if c["fieldname"] == "fields")
		self.assertIn("fieldname", {f["fieldname"] for f in child["fields"]})
		self.assertTrue(all("default_selected" in f for f in child["fields"]))
```

- [ ] **Step 6: Run and confirm failure**

Expected: `ImportError: cannot import name 'build_field_tree'`

- [ ] **Step 7: Implement `build_field_tree`**

```python
# append to frappe_event_bus/template_builder.py

#: Fieldtypes that hold child rows.
TABLE_FIELDTYPES = frozenset({"Table", "Table MultiSelect"})


def build_field_tree(doctype: str) -> dict[str, Any]:
	"""Build a two-level picker tree for ``doctype``.

	Frappe has no grandchild tables, so recursion stops at depth one.
	"""
	meta = frappe.get_meta(doctype)
	fields: list[dict[str, Any]] = []
	children: list[dict[str, Any]] = []

	for df in meta.fields:
		if df.fieldtype in LAYOUT_FIELDTYPES:
			continue
		if df.fieldtype in TABLE_FIELDTYPES:
			child_meta = frappe.get_meta(df.options)
			children.append(
				{
					"fieldname": df.fieldname,
					"label": df.label or df.fieldname,
					"child_doctype": df.options,
					"fields": [
						classify_field(cdf.as_dict())
						for cdf in child_meta.fields
						if cdf.fieldtype not in LAYOUT_FIELDTYPES
						and cdf.fieldtype not in TABLE_FIELDTYPES
					],
				}
			)
			continue
		fields.append(classify_field(df.as_dict()))

	return {"doctype": doctype, "fields": fields, "children": children}
```

- [ ] **Step 8: Run and confirm pass**

Expected: 9 passed.

- [ ] **Step 9: Commit**

```bash
git add frappe_event_bus/template_builder.py frappe_event_bus/tests/test_template_builder.py
git commit -m "feat: classify doctype fields for template generation"
```

---

## Task 2: Generate Jinja from a selection

**Files:**
- Modify: `frappe_event_bus/template_builder.py`
- Modify: `frappe_event_bus/tests/test_template_builder.py`

**Interfaces:**
- Consumes: `build_field_tree` from Task 1.
- Produces: `generate_jinja(doctype: str, selection: dict) -> str`, where
  `selection` is `{"fields": ["a","b"], "children": {"items": ["x","y"]}}`.

- [ ] **Step 1: Write the failing tests — including the one that matters**

```python
# append to frappe_event_bus/tests/test_template_builder.py
import datetime
import json

from frappe_event_bus.rendering import render_payload
from frappe_event_bus.template_builder import generate_jinja


class TestGenerateJinja(FrappeTestCase):
	"""Generated Jinja must render to valid JSON for hostile real-world values."""

	def test_envelope_shape(self):
		out = generate_jinja("ToDo", {"fields": ["description"], "children": {}})
		self.assertIn('"event"', out)
		self.assertIn('"data"', out)
		self.assertIn("{{ doc.description | json }}", out)

	def test_never_uses_tojson(self):
		# tojson raises TypeError on Date/Datetime — the filter choice is load-bearing.
		out = generate_jinja("ToDo", {"fields": ["date"], "children": {}})
		self.assertNotIn("tojson", out)

	def test_renders_to_valid_json_for_hostile_values(self):
		out = generate_jinja("ToDo", {"fields": ["description", "date"], "children": {}})
		doc = frappe._dict(
			doctype="ToDo",
			name="TODO-0001",
			description='has "quotes", back\\slash,\nnewline, <tag> & \'apos\'',
			date=datetime.date(2026, 8, 2),
		)
		rendered = render_payload(out, {"doc": doc, "context": {"event_type": "on_update"}})
		parsed = json.loads(rendered)
		self.assertEqual(parsed["data"]["description"], doc.description)
		self.assertEqual(parsed["data"]["date"], "2026-08-02")

	def test_renders_datetime_and_none(self):
		out = generate_jinja("ToDo", {"fields": ["description", "date"], "children": {}})
		doc = frappe._dict(
			doctype="ToDo", name="TODO-0002",
			description=None, date=datetime.datetime(2026, 8, 2, 13, 5, 1),
		)
		parsed = json.loads(render_payload(out, {"doc": doc, "context": {"event_type": "after_insert"}}))
		self.assertIsNone(parsed["data"]["description"])
		self.assertTrue(parsed["data"]["date"].startswith("2026-08-02"))

	def test_child_table_rows_render(self):
		out = generate_jinja("DocType", {"fields": ["module"], "children": {"fields": ["fieldname"]}})
		doc = frappe._dict(
			doctype="DocType", name="ToDo", module="Core",
			fields=[frappe._dict(fieldname="a"), frappe._dict(fieldname='b"quoted')],
		)
		parsed = json.loads(render_payload(out, {"doc": doc, "context": {"event_type": "on_update"}}))
		self.assertEqual([r["fieldname"] for r in parsed["data"]["fields"]], ["a", 'b"quoted'])

	def test_empty_child_table_renders_empty_array(self):
		out = generate_jinja("DocType", {"fields": [], "children": {"fields": ["fieldname"]}})
		doc = frappe._dict(doctype="DocType", name="ToDo", fields=[])
		parsed = json.loads(render_payload(out, {"doc": doc, "context": {"event_type": "on_update"}}))
		self.assertEqual(parsed["data"]["fields"], [])

	def test_empty_selection_still_valid_json(self):
		out = generate_jinja("ToDo", {"fields": [], "children": {}})
		doc = frappe._dict(doctype="ToDo", name="TODO-0003")
		parsed = json.loads(render_payload(out, {"doc": doc, "context": {"event_type": "on_trash"}}))
		self.assertEqual(parsed["data"], {})
```

- [ ] **Step 2: Run and confirm failure**

Expected: `ImportError: cannot import name 'generate_jinja'`

- [ ] **Step 3: Implement `generate_jinja`**

```python
# append to frappe_event_bus/template_builder.py

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
	children: dict[str, list[str]] = dict(selection.get("children") or {})
	children = {table: cols for table, cols in children.items() if cols}

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
```

- [ ] **Step 4: Run and confirm pass**

Expected: 16 passed. If `test_renders_to_valid_json_for_hostile_values` fails,
the filter is wrong — check it is `| json` and not `| tojson`.

- [ ] **Step 5: Commit**

```bash
git add frappe_event_bus/template_builder.py frappe_event_bus/tests/test_template_builder.py
git commit -m "feat: generate envelope Jinja from a field selection"
```

---

## Task 3: Whitelisted API for the picker

**Files:**
- Modify: `frappe_event_bus/api.py`
- Modify: `frappe_event_bus/tests/test_template_builder.py`

**Interfaces:**
- Consumes: `build_field_tree`, `generate_jinja` from Tasks 1–2.
- Produces: `api.get_field_tree(doctype)` and
  `api.generate_template(doctype, selection)` — both whitelisted, both
  `System Manager` only.

- [ ] **Step 1: Write the failing test**

```python
# append to frappe_event_bus/tests/test_template_builder.py
from frappe_event_bus import api


class TestBuilderApi(FrappeTestCase):
	def test_get_field_tree_returns_tree(self):
		tree = api.get_field_tree("ToDo")
		self.assertEqual(tree["doctype"], "ToDo")
		self.assertIn("description", {f["fieldname"] for f in tree["fields"]})

	def test_generate_template_accepts_json_string_selection(self):
		out = api.generate_template("ToDo", json.dumps({"fields": ["description"], "children": {}}))
		self.assertIn("{{ doc.description | json }}", out)

	def test_generate_template_accepts_dict_selection(self):
		out = api.generate_template("ToDo", {"fields": ["description"], "children": {}})
		self.assertIn("{{ doc.description | json }}", out)
```

- [ ] **Step 2: Run and confirm failure**

Expected: `AttributeError: module 'frappe_event_bus.api' has no attribute 'get_field_tree'`

- [ ] **Step 3: Implement the endpoints**

```python
# append to frappe_event_bus/api.py, after preview_payload
@frappe.whitelist()
def get_field_tree(doctype: str) -> dict[str, Any]:
	"""Return the two-level picker tree for ``doctype``.

	Args:
		doctype: DocType to introspect.
	"""
	frappe.only_for("System Manager")
	from frappe_event_bus.template_builder import build_field_tree

	return build_field_tree(doctype)


@frappe.whitelist()
def generate_template(doctype: str, selection: str | dict[str, Any]) -> str:
	"""Generate Jinja for ``doctype`` from a picker ``selection``.

	Args:
		doctype: DocType the template targets.
		selection: ``{"fields": [...], "children": {table: [...]}}``, JSON or dict.
	"""
	frappe.only_for("System Manager")
	from frappe_event_bus.template_builder import generate_jinja

	return generate_jinja(doctype, _as_dict(selection))
```

Add the import at the top of `api.py` if not already present: `from typing import Any`
(it is — line 6).

- [ ] **Step 4: Run and confirm pass**

Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add frappe_event_bus/api.py frappe_event_bus/tests/test_template_builder.py
git commit -m "feat: expose field tree and template generation over the API"
```

---

## Task 4: `applies_to_doctype` binding and Rule cross-check

**Files:**
- Modify: `.../doctype/event_bus_message_template/event_bus_message_template.json`
- Modify: `.../doctype/event_bus_message_template/event_bus_message_template.py`
- Modify: `.../doctype/event_bus_rule/event_bus_rule.py`
- Create: `frappe_event_bus/tests/test_template_binding.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `applies_to_doctype` on Event Bus Message Template; a `validate`
  hook on Event Bus Rule that throws `frappe.ValidationError` on mismatch.

- [ ] **Step 1: Write the failing test**

```python
# frappe_event_bus/tests/test_template_binding.py
"""Template-to-doctype binding is optional, but enforced when present."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


def _template(name: str, applies_to: str | None) -> str:
	if frappe.db.exists("Event Bus Message Template", name):
		frappe.delete_doc("Event Bus Message Template", name, force=True)
	doc = frappe.get_doc(
		{
			"doctype": "Event Bus Message Template",
			"template_name": name,
			"applies_to_doctype": applies_to,
			"jinja_template": '{"name": {{ doc.name | json }}}',
		}
	).insert()
	return doc.name


class TestTemplateBinding(FrappeTestCase):
	def test_generic_template_works_with_any_rule(self):
		tpl = _template("eb-generic", None)
		rule = frappe.get_doc(
			{
				"doctype": "Event Bus Rule", "rule_name": "eb-rule-generic",
				"reference_doctype": "ToDo", "event_type": "after_insert",
				"message_template": tpl,
			}
		)
		rule.insert()
		self.assertTrue(rule.name)

	def test_matching_binding_is_accepted(self):
		tpl = _template("eb-todo", "ToDo")
		rule = frappe.get_doc(
			{
				"doctype": "Event Bus Rule", "rule_name": "eb-rule-match",
				"reference_doctype": "ToDo", "event_type": "after_insert",
				"message_template": tpl,
			}
		)
		rule.insert()
		self.assertTrue(rule.name)

	def test_mismatched_binding_is_rejected(self):
		tpl = _template("eb-note", "Note")
		rule = frappe.get_doc(
			{
				"doctype": "Event Bus Rule", "rule_name": "eb-rule-mismatch",
				"reference_doctype": "ToDo", "event_type": "after_insert",
				"message_template": tpl,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			rule.insert()
```

- [ ] **Step 2: Run and confirm failure**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && \
   bench --site dev.localhost run-tests --app frappe_event_bus \
   --module frappe_event_bus.tests.test_template_binding'
```

Expected: `test_mismatched_binding_is_rejected` fails — no validation exists yet.
The other two may error on the unknown `applies_to_doctype` field.

- [ ] **Step 3: Add the field to the doctype JSON**

In `event_bus_message_template.json`, add `"applies_to_doctype"` to
`field_order` immediately after `"template_name"`, and add to `fields`:

```json
  {
   "description": "Optional. Bind this template to a DocType to enable the field picker and real-document preview. Leave blank for a generic, reusable template.",
   "fieldname": "applies_to_doctype",
   "fieldtype": "Link",
   "in_standard_filter": 1,
   "label": "Applies To DocType",
   "options": "DocType"
  },
```

- [ ] **Step 4: Add the type hint**

In `event_bus_message_template.py`, inside the auto-generated block, add in
alphabetical position (before `description`):

```python
		applies_to_doctype: DF.Link | None
```

- [ ] **Step 5: Add the Rule validation**

In `event_bus_rule.py`, add to the controller class:

```python
	def validate(self) -> None:
		"""Reject a template bound to a different doctype than this rule targets."""
		self._validate_template_binding()

	def _validate_template_binding(self) -> None:
		"""Throw if the linked template declares a conflicting ``applies_to_doctype``."""
		if not self.message_template:
			return
		applies_to = frappe.db.get_value(
			"Event Bus Message Template", self.message_template, "applies_to_doctype"
		)
		if applies_to and applies_to != self.reference_doctype:
			frappe.throw(
				frappe._(
					"Message Template {0} applies to {1}, but this rule targets {2}."
				).format(self.message_template, applies_to, self.reference_doctype),
				title=frappe._("Template DocType Mismatch"),
			)
```

If `event_bus_rule.py` already defines `validate`, add the
`self._validate_template_binding()` call to it instead of redefining.

- [ ] **Step 6: Migrate and run**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && bench --site dev.localhost migrate'
```

Then re-run the module. Expected: 3 passed.

- [ ] **Step 7: Run the full suite for regressions**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && \
   bench --site dev.localhost run-tests --app frappe_event_bus'
```

Expected: all prior tests still pass.

- [ ] **Step 8: Commit**

```bash
git add frappe_event_bus/
git commit -m "feat: add optional applies_to_doctype binding with rule cross-check"
```

---

## Task 5: Picker dialog

**Files:**
- Create: `frappe_event_bus/public/js/template_builder.bundle.js`
- Modify: `frappe_event_bus/hooks.py:256`

**Interfaces:**
- Consumes: `frappe_event_bus.api.get_field_tree`,
  `frappe_event_bus.api.generate_template` from Task 3.
- Produces: an **Insert from DocType** button on the Message Template form.

- [ ] **Step 1: Write the bundle**

```javascript
/**
 * Vue 3 field picker for Event Bus Message Templates.
 *
 * Adds an "Insert from DocType" button that lists the target doctype's fields
 * (two levels — Frappe has no grandchild tables), lets the user prune them,
 * and writes generated Jinja into the always-editable jinja_template field.
 */

import { createApp, defineComponent, reactive, computed } from "vue";

const FieldPicker = defineComponent({
	name: "FieldPicker",
	props: {
		doctype: { type: String, required: true },
		onInsert: { type: Function, required: true },
	},
	setup(props) {
		const state = reactive({ loading: true, error: "", fields: [], children: [], mode: "cursor" });

		async function load() {
			try {
				const r = await frappe.call({
					method: "frappe_event_bus.api.get_field_tree",
					args: { doctype: props.doctype },
				});
				const tree = r.message || {};
				state.fields = (tree.fields || []).map((f) => ({ ...f, checked: f.default_selected }));
				state.children = (tree.children || []).map((c) => ({
					...c,
					fields: (c.fields || []).map((f) => ({ ...f, checked: f.default_selected })),
				}));
			} catch (e) {
				state.error = (e && e.message) || String(e);
			} finally {
				state.loading = false;
			}
		}

		const counts = computed(() => {
			let selected = state.fields.filter((f) => f.checked).length;
			let excluded = state.fields.filter((f) => !f.selectable).length;
			let tables = 0;
			for (const c of state.children) {
				const n = c.fields.filter((f) => f.checked).length;
				if (n) tables += 1;
				selected += n;
				excluded += c.fields.filter((f) => !f.selectable).length;
			}
			return { selected, excluded, tables };
		});

		function selection() {
			const children = {};
			for (const c of state.children) {
				const cols = c.fields.filter((f) => f.checked).map((f) => f.fieldname);
				if (cols.length) children[c.fieldname] = cols;
			}
			return {
				fields: state.fields.filter((f) => f.checked).map((f) => f.fieldname),
				children,
			};
		}

		function setAll(checked) {
			state.fields.forEach((f) => { if (f.selectable) f.checked = checked; });
			state.children.forEach((c) => c.fields.forEach((f) => { if (f.selectable) f.checked = checked; }));
		}

		async function insert() {
			const r = await frappe.call({
				method: "frappe_event_bus.api.generate_template",
				args: { doctype: props.doctype, selection: JSON.stringify(selection()) },
			});
			props.onInsert(r.message || "", state.mode);
		}

		load();
		return { state, counts, insert, setAll, __ };
	},
	template: `
		<div class="eb-field-picker">
			<div v-if="state.loading">{{ __("Loading fields...") }}</div>
			<div v-if="state.error" class="text-danger">{{ state.error }}</div>
			<template v-if="!state.loading && !state.error">
				<div class="mb-2">
					<button class="btn btn-xs btn-default" @click="setAll(true)">{{ __("Select all") }}</button>
					<button class="btn btn-xs btn-default ml-1" @click="setAll(false)">{{ __("None") }}</button>
				</div>
				<div class="eb-tree" style="max-height:45vh;overflow:auto">
					<div v-for="f in state.fields" :key="f.fieldname" class="mb-1">
						<label :class="{ 'text-muted': !f.selectable }">
							<input type="checkbox" v-model="f.checked" :disabled="!f.selectable" />
							{{ f.label }}
							<span class="text-muted small">{{ f.fieldtype }}</span>
							<span v-if="f.note" class="text-muted small">— {{ f.note }}</span>
						</label>
					</div>
					<div v-for="c in state.children" :key="c.fieldname" class="mt-3">
						<div><b>{{ c.label }}</b> <span class="text-muted small">{{ c.child_doctype }}</span></div>
						<div v-for="f in c.fields" :key="f.fieldname" class="ml-3">
							<label :class="{ 'text-muted': !f.selectable }">
								<input type="checkbox" v-model="f.checked" :disabled="!f.selectable" />
								{{ f.label }}
								<span class="text-muted small">{{ f.fieldtype }}</span>
								<span v-if="f.note" class="text-muted small">— {{ f.note }}</span>
							</label>
						</div>
					</div>
				</div>
				<div class="mt-3 text-muted">
					{{ __("Sends {0} fields across {1} child tables. {2} excluded as sensitive.",
					      [counts.selected, counts.tables, counts.excluded]) }}
				</div>
				<div class="mt-2">
					<label class="mr-3"><input type="radio" value="cursor" v-model="state.mode" /> {{ __("Insert at cursor") }}</label>
					<label><input type="radio" value="replace" v-model="state.mode" /> {{ __("Replace entire template") }}</label>
				</div>
				<button class="btn btn-primary btn-sm mt-3" @click="insert">{{ __("Insert") }}</button>
			</template>
		</div>
	`,
});

function applyInsert(frm, text, mode) {
	const field = frm.get_field("jinja_template");
	if (mode === "replace" || !frm.doc.jinja_template) {
		frm.set_value("jinja_template", text);
	} else {
		const editor = field && field.editor;
		const current = frm.doc.jinja_template || "";
		if (editor && editor.getCursor) {
			const doc = editor.getDoc();
			doc.replaceRange(text, doc.getCursor());
			frm.set_value("jinja_template", editor.getValue());
		} else {
			frm.set_value("jinja_template", current + "\n" + text);
		}
	}
	frappe.show_alert({ message: __("Template inserted"), indicator: "green" });
}

function openPicker(frm, doctype) {
	const dialog = new frappe.ui.Dialog({
		title: __("Insert from {0}", [doctype]),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "picker_area" }],
	});
	dialog.show();
	const app = createApp(FieldPicker, {
		doctype,
		onInsert: (text, mode) => {
			applyInsert(frm, text, mode);
			dialog.hide();
		},
	});
	app.mount(dialog.fields_dict.picker_area.$wrapper.get(0));
	dialog.onhide = () => app.unmount();
}

frappe.ui.form.on("Event Bus Message Template", {
	refresh(frm) {
		frm.add_custom_button(__("Insert from DocType"), () => {
			if (frm.doc.applies_to_doctype) {
				openPicker(frm, frm.doc.applies_to_doctype);
				return;
			}
			frappe.prompt(
				{ fieldtype: "Link", options: "DocType", label: __("DocType"), fieldname: "doctype", reqd: 1 },
				(values) => openPicker(frm, values.doctype),
				__("Insert from DocType")
			);
		});
	},
});
```

- [ ] **Step 2: Register the bundle**

In `hooks.py`, replace the single-string `app_include_js` at line 256 with a list:

```python
app_include_js = [
	"/assets/frappe_event_bus/js/payload_preview.bundle.js",
	"/assets/frappe_event_bus/js/template_builder.bundle.js",
]
```

- [ ] **Step 3: Build the assets**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && bench build --app frappe_event_bus'
```

Expected: a `template_builder.bundle.<hash>.js` appears in
`frappe_event_bus/public/dist/js/`.

- [ ] **Step 4: Verify in the browser**

Open `http://dev.localhost:8000/app/event-bus-message-template/new`, set
**Applies To DocType** to `ToDo`, save, then click **Insert from DocType**.
Confirm: the tree lists ToDo fields, the footer count moves as you tick, and
**Insert** writes Jinja into the template field. Then click **Preview Payload**
and confirm it renders valid JSON against a real ToDo.

- [ ] **Step 5: Commit**

```bash
git add frappe_event_bus/public/js/template_builder.bundle.js frappe_event_bus/hooks.py
git commit -m "feat: add doctype field picker to message template form"
```

---

## Task 6: Rule form — link filter and quick-entry prefill

**Files:**
- Create: `.../doctype/event_bus_rule/event_bus_rule.js`

**Interfaces:**
- Consumes: `applies_to_doctype` from Task 4.
- Produces: no server interface.

- [ ] **Step 1: Write the client script**

```javascript
/**
 * Event Bus Rule form behaviour.
 *
 * Restricts the Message Template link to templates that either target this
 * rule's Reference DocType or are generic, and pre-binds newly created
 * templates to it.
 */

frappe.ui.form.on("Event Bus Rule", {
	onload(frm) {
		frm.set_query("message_template", () => {
			if (!frm.doc.reference_doctype) return {};
			return {
				filters: [["applies_to_doctype", "in", [frm.doc.reference_doctype, ""]]],
			};
		});

		// Frappe reads this off the docfield, not the control (link.js:187).
		const field = frm.fields_dict.message_template;
		if (field) {
			field.df.get_route_options_for_new_doc = () => ({
				applies_to_doctype: frm.doc.reference_doctype || "",
			});
		}
	},

	reference_doctype(frm) {
		// A template bound to the old doctype can no longer be valid here.
		if (frm.doc.message_template) {
			frm.set_value("message_template", null);
		}
	},
});
```

- [ ] **Step 2: Verify in the browser**

Open a new Event Bus Rule, set **Reference DocType** to `ToDo`, then open the
Message Template link. Confirm only ToDo-bound and generic templates appear.
Type a new name and choose **Create a new Event Bus Message Template**; confirm
`Applies To DocType` arrives pre-filled with `ToDo`.

- [ ] **Step 3: Commit**

```bash
git add frappe_event_bus/frappe_event_bus/doctype/event_bus_rule/event_bus_rule.js
git commit -m "feat: filter and pre-bind message templates from the rule form"
```

---

## Task 6b: Preview against a bound doctype

**Files:**
- Modify: `frappe_event_bus/public/js/payload_preview.bundle.js`

**Interfaces:**
- Consumes: `applies_to_doctype` from Task 4. The server endpoint
  `api.preview_payload(message_template, reference_doctype, reference_name)`
  already exists and is unchanged.
- Produces: no new interface.

Today the preview dialog asks for `reference_doctype` and `reference_name` as
two free-text inputs, so you must type an exact docname from memory. With the
binding in place the doctype is known and the name can be a real Link picker.

- [ ] **Step 1: Accept the bound doctype as a prop**

In `payload_preview.bundle.js`, add `appliesTo` to `props`:

```javascript
	props: {
		messageTemplate: { type: String, required: true },
		appliesTo: { type: String, default: "" },
	},
```

and seed it in `setup`, right after the `reactive` block:

```javascript
		state.referenceDoctype = props.appliesTo || "";
```

- [ ] **Step 2: Swap the name input for a Link picker**

Replace the two `<input>` elements in the template with a single mount point
when the doctype is known, keeping the free-text pair as the fallback:

```javascript
			<div class="row">
				<div v-if="!appliesTo" class="col-sm-6 mb-2">
					<input class="form-control" v-model="state.referenceDoctype"
						:placeholder="__('Reference DocType (optional)')" />
				</div>
				<div v-if="appliesTo" class="col-sm-6 mb-2">
					<div class="frappe-control" ref="linkMount"></div>
				</div>
				<div v-if="!appliesTo" class="col-sm-6 mb-2">
					<input class="form-control" v-model="state.referenceName"
						:placeholder="__('Reference Name (optional)')" />
				</div>
			</div>
```

- [ ] **Step 3: Mount the Frappe Link control**

Add to `setup`, using Vue's `onMounted`:

```javascript
		const linkMount = ref(null);

		onMounted(() => {
			if (!props.appliesTo || !linkMount.value) return;
			const control = frappe.ui.form.make_control({
				parent: linkMount.value,
				df: {
					fieldtype: "Link",
					options: props.appliesTo,
					label: __("Preview Against"),
					fieldname: "reference_name",
					change: () => { state.referenceName = control.get_value(); },
				},
				render_input: true,
			});
		});
```

and add `linkMount` to the returned object. Update the import line to
`import { createApp, defineComponent, reactive, ref, onMounted } from "vue";`.

- [ ] **Step 4: Pass the prop at the call site**

In `openPreviewDialog`:

```javascript
	const app = createApp(PayloadPreview, {
		messageTemplate: frm.doc.template_name,
		appliesTo: frm.doc.applies_to_doctype || "",
	});
```

- [ ] **Step 5: Build and verify in the browser**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && bench build --app frappe_event_bus'
```

On a template with `Applies To DocType = ToDo`, open **Preview Payload** and
confirm the document field is an autocompleting Link, not free text, and that
rendering against a picked ToDo returns valid JSON. On a template with no
binding, confirm the two free-text inputs still appear and still work.

- [ ] **Step 6: Commit**

```bash
git add frappe_event_bus/public/js/payload_preview.bundle.js
git commit -m "feat: preview against a link-picked document when template is bound"
```

---

## Task 7: Tabs on core doctypes

**Files:**
- Modify: `.../event_bus_message_template/event_bus_message_template.json`
- Modify: `.../event_bus_rule/event_bus_rule.json`
- Modify: `.../event_bus_outbox_message/event_bus_outbox_message.json`

**Interfaces:** none. Layout only — no fieldnames change, no fields move
between doctypes.

- [ ] **Step 1: Message Template tabs**

Add two Tab Break fields. New `field_order`:

```
template_name, applies_to_doctype, message_type, column_break_head, version,
enabled, description, section_break_template, jinja_template,
tab_validation, json_schema, section_break_example, example_context, example_output
```

Add to `fields`:

```json
  {"fieldname": "tab_validation", "fieldtype": "Tab Break", "label": "Validation & Preview"}
```

The first tab needs no explicit Tab Break — Frappe labels the implicit first
tab from `"Details"` unless one is added; add one at the top for a clearer
label:

```json
  {"fieldname": "tab_template", "fieldtype": "Tab Break", "label": "Template"}
```

placed first in `field_order`.

- [ ] **Step 2: Rule tabs**

New `field_order`:

```
tab_rule, rule_name, enabled, column_break_head, reference_doctype, event_type,
section_break_match, condition, section_break_message, message_template,
tab_destinations, section_break_dest, destinations,
tab_advanced, deduplication_key_template, description
```

Add to `fields`:

```json
  {"fieldname": "tab_rule", "fieldtype": "Tab Break", "label": "Rule"},
  {"fieldname": "tab_destinations", "fieldtype": "Tab Break", "label": "Destinations"},
  {"fieldname": "tab_advanced", "fieldtype": "Tab Break", "label": "Advanced"}
```

- [ ] **Step 3: Outbox Message tabs**

New `field_order`:

```
tab_message, status, event_rule, message_template, column_break_head, provider,
connection, destination, routing_key, section_break_ref, reference_doctype,
reference_document, event_type, column_break_ref, deduplication_key,
tab_payload, section_break_payload, payload, headers,
tab_delivery, section_break_delivery, attempt_count, next_retry_at,
published_at, column_break_delivery, last_error
```

Add to `fields`:

```json
  {"fieldname": "tab_message", "fieldtype": "Tab Break", "label": "Message"},
  {"fieldname": "tab_payload", "fieldtype": "Tab Break", "label": "Payload"},
  {"fieldname": "tab_delivery", "fieldtype": "Tab Break", "label": "Delivery"}
```

- [ ] **Step 4: Migrate and verify**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && bench --site dev.localhost migrate'
```

Open each of the three forms and confirm the tabs render with the right fields
under each, and that no field disappeared.

- [ ] **Step 5: Run the full suite**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && \
   bench --site dev.localhost run-tests --app frappe_event_bus'
```

Expected: all pass. Layout changes should not affect behaviour; a failure here
means a fieldname was mistyped in `field_order`.

- [ ] **Step 6: Commit**

```bash
git add frappe_event_bus/
git commit -m "feat: split config-heavy doctypes into tabs"
```

---

## Task 8: Tabs on RabbitMQ doctypes

**Repo:** `frappe_event_bus_rabbitmq` (separate branch, separate PR)

**Files:**
- Modify: `.../rabbitmq_event_bus_connection/rabbitmq_event_bus_connection.json`
- Modify: `.../rabbitmq_event_bus_destination/rabbitmq_event_bus_destination.json`

**Interfaces:** none.

- [ ] **Step 1: Branch**

```bash
cd ../frappe_event_bus_rabbitmq && git checkout -b feat/tabbed-forms
```

- [ ] **Step 2: Connection tabs**

New `field_order`:

```
tab_connection, connection_name, enabled, column_break_head, host, port,
virtual_host, section_break_auth, username, password,
tab_advanced, tls_enabled, tls_verify, column_break_auth,
section_break_tuning, connection_timeout, heartbeat, section_break_notes, notes
```

Add to `fields`:

```json
  {"fieldname": "tab_connection", "fieldtype": "Tab Break", "label": "Connection"},
  {"fieldname": "tab_advanced", "fieldtype": "Tab Break", "label": "Advanced"}
```

- [ ] **Step 3: Destination tabs**

New `field_order`:

```
tab_destination, destination_name, connection, column_break_head, exchange,
exchange_type, routing_key,
tab_topology, section_break_exchange, declare_exchange, durable_exchange,
column_break_exchange, queue_name, declare_queue, durable_queue, bind_queue,
tab_publishing, section_break_publish, persistent_message, publisher_confirms,
section_break_headers, headers_template, section_break_notes, notes
```

Add to `fields`:

```json
  {"fieldname": "tab_destination", "fieldtype": "Tab Break", "label": "Destination"},
  {"fieldname": "tab_topology", "fieldtype": "Tab Break", "label": "Topology"},
  {"fieldname": "tab_publishing", "fieldtype": "Tab Break", "label": "Publishing"}
```

- [ ] **Step 4: Migrate and verify**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && bench --site dev.localhost migrate'
```

Open both forms and confirm the tabs render and no field disappeared. The
`password` field must still be present on Connection — it is excluded from
*publishing*, not from the form.

- [ ] **Step 5: Run the provider suite**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && \
   bench --site dev.localhost run-tests --app frappe_event_bus_rabbitmq'
```

- [ ] **Step 6: Commit**

```bash
git add frappe_event_bus_rabbitmq/
git commit -m "feat: split connection and destination forms into tabs"
```

---

## Task 9: End-to-end verification

**Files:** none — this is a manual gate before opening PRs.

- [ ] **Step 1: Generate and publish for real**

In the desk UI:
1. Create a Message Template with `Applies To DocType = ToDo`.
2. **Insert from DocType**, accept the defaults, **Replace entire template**.
3. **Preview Payload** against a real ToDo — confirm valid JSON.
4. Create a Rule: `reference_doctype = ToDo`, `event_type = after_insert`,
   the template above, and a RabbitMQ destination.
5. Create a ToDo whose description contains `"quotes"`, a backslash and a
   newline.

- [ ] **Step 2: Confirm delivery**

Check the Outbox Message list for a `published` row, and confirm the message
arrived in the RabbitMQ management UI at `http://localhost:15672`
(guest/guest). The payload must contain the hostile description intact.

This is the test that proves the `| json` filter choice end to end, through the
real worker rather than a unit test.

- [ ] **Step 3: Full suite, both apps**

```bash
docker exec frappe-event-bus-dev-frappe-1 bash -lc \
  'cd /workspace/development/frappe-bench && \
   bench --site dev.localhost run-tests --app frappe_event_bus && \
   bench --site dev.localhost run-tests --app frappe_event_bus_rabbitmq'
```

- [ ] **Step 4: Open both PRs**

One in each repo, cross-referencing the design doc.
