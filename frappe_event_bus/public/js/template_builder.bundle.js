/**
 * Vue 3 field picker for Event Bus Message Templates.
 *
 * Adds an "Insert from DocType" button that lists the target doctype's fields
 * (two levels — Frappe has no grandchild tables), lets the user prune them,
 * and writes generated Jinja into the always-editable jinja_template field.
 */

import { computed, createApp, defineComponent, reactive } from "vue";

const FieldPicker = defineComponent({
	name: "FieldPicker",
	props: {
		doctype: { type: String, required: true },
		onInsert: { type: Function, required: true },
	},
	setup(props) {
		const state = reactive({
			loading: true,
			inserting: false,
			error: "",
			fields: [],
			children: [],
			mode: "cursor",
		});

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
			state.fields.forEach((f) => {
				if (f.selectable) f.checked = checked;
			});
			state.children.forEach((c) =>
				c.fields.forEach((f) => {
					if (f.selectable) f.checked = checked;
				})
			);
		}

		async function insert() {
			state.inserting = true;
			try {
				const r = await frappe.call({
					method: "frappe_event_bus.api.generate_template",
					args: { doctype: props.doctype, selection: JSON.stringify(selection()) },
				});
				props.onInsert(r.message || "", state.mode);
			} catch (e) {
				state.error = (e && e.message) || String(e);
			} finally {
				state.inserting = false;
			}
		}

		load();
		return { state, counts, insert, setAll, __ };
	},
	template: `
		<div class="eb-field-picker">
			<div v-if="state.loading">{{ __("Loading fields...") }}</div>
			<div v-if="state.error" class="text-danger mb-2">{{ state.error }}</div>
			<template v-if="!state.loading">
				<div class="mb-2">
					<button class="btn btn-xs btn-default" @click="setAll(true)">{{ __("Select all") }}</button>
					<button class="btn btn-xs btn-default ml-1" @click="setAll(false)">{{ __("None") }}</button>
				</div>
				<div class="eb-tree" style="max-height:45vh;overflow:auto">
					<div v-for="f in state.fields" :key="f.fieldname" class="mb-1">
						<label :class="{ 'text-muted': !f.selectable }" style="font-weight:normal">
							<input type="checkbox" v-model="f.checked" :disabled="!f.selectable" />
							{{ f.label }}
							<span class="text-muted small">{{ f.fieldtype }}</span>
							<span v-if="f.note" class="text-muted small">— {{ f.note }}</span>
						</label>
					</div>
					<div v-for="c in state.children" :key="c.fieldname" class="mt-3">
						<div><b>{{ c.label }}</b> <span class="text-muted small">{{ c.child_doctype }}</span></div>
						<div v-for="f in c.fields" :key="f.fieldname" class="ml-3">
							<label :class="{ 'text-muted': !f.selectable }" style="font-weight:normal">
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
					<label class="mr-3" style="font-weight:normal">
						<input type="radio" value="cursor" v-model="state.mode" /> {{ __("Insert at cursor") }}
					</label>
					<label style="font-weight:normal">
						<input type="radio" value="replace" v-model="state.mode" /> {{ __("Replace entire template") }}
					</label>
				</div>
				<button class="btn btn-primary btn-sm mt-3" :disabled="state.inserting" @click="insert">
					{{ state.inserting ? __("Inserting...") : __("Insert") }}
				</button>
			</template>
		</div>
	`,
});

function applyInsert(frm, text, mode) {
	const field = frm.get_field("jinja_template");
	const editor = field && field.editor;

	if (mode === "replace" || !frm.doc.jinja_template) {
		frm.set_value("jinja_template", text);
	} else if (editor && editor.getDoc) {
		const editorDoc = editor.getDoc();
		editorDoc.replaceRange(text, editorDoc.getCursor());
		frm.set_value("jinja_template", editor.getValue());
	} else {
		frm.set_value("jinja_template", `${frm.doc.jinja_template}\n${text}`);
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
				{
					fieldtype: "Link",
					options: "DocType",
					label: __("DocType"),
					fieldname: "doctype",
					reqd: 1,
				},
				(values) => openPicker(frm, values.doctype),
				__("Insert from DocType")
			);
		});
	},
});
