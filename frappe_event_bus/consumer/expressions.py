"""Safe rendering of user-authored Jinja key expressions.

Two traps make a naive render unusable as a key, and both have produced real
bugs in this app:

* ``frappe.render_template`` renders with ``jinja2.DebugUndefined``, so an
  unresolved variable stringifies as ``"{{ no such element: ... }}"`` rather
  than raising — and it does so even when the rest of the expression resolved.
* ``frappe._dict.__getattr__`` is ``dict.get``, so a missing key on a parsed
  payload resolves to ``None`` and renders the literal ``"None"`` without ever
  reaching ``Undefined`` at all.

Either would yield a key that is identical across unrelated messages. This
module is the single place that knows about both.
"""

from __future__ import annotations

import re
from typing import Any

import frappe

#: A rendered key must contain no residual Jinja. frappe.render_template uses
#: jinja2.DebugUndefined, which stringifies an unresolved variable as
#: "{{ no such element: ... }}" rather than raising — and it does so even when
#: the rest of the expression resolved. Two different messages missing the same
#: field would then render an identical key, so any residue at all makes the
#: render unusable.
_UNRESOLVED_EXPRESSION_RE = re.compile(r"\{\{.*?\}\}")


def _plain(value: Any) -> dict[str, Any]:
	"""Strip a frappe._dict down to a plain dict before it reaches Jinja.

	frappe.parse_json wraps a decoded object in frappe._dict, whose
	``__getattr__`` is ``dict.get`` — a missing key returns ``None`` instead of
	raising ``AttributeError``. Jinja's dot lookup only falls through to
	``__getitem__`` (and from there to Undefined) when attribute access
	raises, so "{{ payload.missing }}" against a frappe._dict renders the
	literal text "None" and never reaches DebugUndefined at all — the
	``_UNRESOLVED_EXPRESSION_RE`` check above cannot see a failure that never
	produced "{{ ... }}" text. A plain dict has no such __getattr__, so the
	same lookup raises through to Undefined as expected.
	"""
	return dict(value or {})


def render_key_expression(
	expression: str | None,
	payload: Any,
	headers: Any,
	consumer: Any,
) -> str | None:
	"""Render a Jinja key expression, or return None when it cannot be used.

	None covers every way an expression can fail to yield a usable key: a
	blank expression, a template syntax error, a raised exception, an
	unresolved variable left behind as residual "{{ ... }}" text, or a render
	that resolved to nothing at all. Callers own the fallback — this function
	only ever admits it could not produce a key; it never fails open with an
	empty string or the debug marker text itself.
	"""
	expression = (expression or "").strip()
	if not expression:
		return None

	try:
		context = {
			"payload": _plain(payload),
			"headers": _plain(headers),
			"consumer": consumer,
		}
		rendered = frappe.render_template(expression, context).strip()
	except Exception:
		# Covers both a template error and _plain() rejecting a payload that
		# parsed as valid JSON but isn't a mapping (e.g. a bare string or a
		# list) — a broker is free to publish either, and neither is a reason
		# to raise out of a pure key-computation helper.
		frappe.log_error(
			title="Event Bus: key expression failed to render",
			message=frappe.get_traceback(),
		)
		return None

	if not rendered or _UNRESOLVED_EXPRESSION_RE.search(rendered):
		return None

	return rendered
