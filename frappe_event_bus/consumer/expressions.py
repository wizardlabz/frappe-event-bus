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

It also owns :func:`as_mapping`, the one guard every consumer module uses
before treating a decoded payload or header set as a mapping.
"""

from __future__ import annotations

import re
from typing import Any

import frappe
import jinja2

#: A rendered key must contain no residual Jinja. frappe.render_template uses
#: jinja2.DebugUndefined, which stringifies an unresolved variable as
#: "{{ no such element: ... }}" rather than raising — and it does so even when
#: the rest of the expression resolved. Two different messages missing the same
#: field would then render an identical key, so any residue at all makes the
#: render unusable.
_UNRESOLVED_EXPRESSION_RE = re.compile(r"\{\{.*?\}\}")


def as_mapping(value: Any) -> dict[str, Any]:
	"""Coerce a decoded payload or header set to a plain, safe-to-``.get()`` dict.

	Two jobs, both of which have produced real bugs:

	*Anything that is not a mapping becomes an empty dict.* ``frappe.parse_json``
	returns whatever the JSON decodes to, and a broker is free to publish a
	document that is valid JSON but not an object — ``'[1, 2, 3]'`` decodes to a
	``list``, ``'"hello"'`` to a ``str``. Neither has ``.get``, so every caller
	that reached for a named field on the raw result raised ``AttributeError``
	and made the message permanently unpersistable. An absent field and a
	payload with no fields at all are the same answer to the caller: no value.

	*A frappe._dict is stripped down to a plain dict.* ``frappe._dict.__getattr__``
	is ``dict.get``, so a missing key returns ``None`` instead of raising
	``AttributeError``. Jinja's dot lookup only falls through to ``__getitem__``
	(and from there to Undefined) when attribute access raises, so
	"{{ payload.missing }}" against a frappe._dict renders the literal text
	"None" and never reaches DebugUndefined at all — the
	``_UNRESOLVED_EXPRESSION_RE`` check above cannot see a failure that never
	produced "{{ ... }}" text. A plain dict has no such __getattr__, so the same
	lookup raises through to Undefined as expected.
	"""
	if not isinstance(value, dict):
		return {}
	return dict(value)


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
			"payload": as_mapping(payload),
			"headers": as_mapping(headers),
			"consumer": consumer,
		}
		rendered = frappe.render_template(expression, context).strip()
	except jinja2.TemplateSyntaxError:
		# A malformed template is an operator's configuration error, not a
		# property of the message, so it is the one render failure worth
		# reporting from here. Everything else — including a payload that
		# parsed as valid JSON but isn't a mapping, which as_mapping() now
		# absorbs into an empty context rather than an exception — is a normal
		# per-message outcome that must not write an Error Log row per message.
		frappe.log_error(
			title="Event Bus: key expression is not valid Jinja",
			message=frappe.get_traceback(),
		)
		return None
	except Exception:
		return None

	if not rendered or _UNRESOLVED_EXPRESSION_RE.search(rendered):
		return None

	return rendered
