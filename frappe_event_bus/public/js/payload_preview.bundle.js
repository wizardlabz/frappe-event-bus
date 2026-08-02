/**
 * Vue 3 payload preview for Event Bus Message Templates.
 *
 * Adds a "Preview Payload" button to the Message Template form. Clicking it
 * opens a dialog hosting a small reactive Vue app that calls the whitelisted
 * `preview_payload` API and renders the JSON output with a validation badge.
 */

import { createApp, defineComponent, onMounted, reactive, ref } from "vue";

const PayloadPreview = defineComponent({
	name: "PayloadPreview",
	props: {
		messageTemplate: { type: String, required: true },
		appliesTo: { type: String, default: "" },
	},
	setup(props) {
		const state = reactive({
			loading: false,
			valid: null,
			output: "",
			error: "",
			referenceDoctype: props.appliesTo || "",
			referenceName: "",
		});

		// When the template is bound to a doctype we know what to preview
		// against, so offer a real Link picker instead of free text.
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
					change: () => {
						state.referenceName = control.get_value();
					},
				},
				render_input: true,
			});
		});

		async function runPreview() {
			state.loading = true;
			state.error = "";
			try {
				const r = await frappe.call({
					method: "frappe_event_bus.api.preview_payload",
					args: {
						message_template: props.messageTemplate,
						reference_doctype: state.referenceDoctype || null,
						reference_name: state.referenceName || null,
					},
				});
				const data = r.message || {};
				state.valid = data.valid;
				if (data.valid) {
					state.output = data.output;
				} else {
					state.output = "";
					state.error = data.error || __("Unknown error");
				}
			} catch (e) {
				state.valid = false;
				state.error = (e && e.message) || String(e);
			} finally {
				state.loading = false;
			}
		}

		return { state, runPreview, linkMount, __ };
	},
	template: `
		<div class="eb-payload-preview">
			<div class="row">
				<div v-if="appliesTo" class="col-sm-6 mb-2">
					<div ref="linkMount"></div>
				</div>
				<template v-else>
					<div class="col-sm-6 mb-2">
						<input class="form-control" v-model="state.referenceDoctype"
							:placeholder="__('Reference DocType (optional)')" />
					</div>
					<div class="col-sm-6 mb-2">
						<input class="form-control" v-model="state.referenceName"
							:placeholder="__('Reference Name (optional)')" />
					</div>
				</template>
			</div>
			<button class="btn btn-primary btn-sm mb-3" :disabled="state.loading" @click="runPreview">
				{{ state.loading ? __('Rendering...') : __('Render Preview') }}
			</button>
			<div v-if="state.valid === true" class="indicator-pill green mb-2">{{ __('Valid JSON') }}</div>
			<div v-if="state.valid === false" class="indicator-pill red mb-2">{{ __('Invalid') }}</div>
			<pre v-if="state.output" class="eb-output">{{ state.output }}</pre>
			<div v-if="state.error" class="text-danger">{{ state.error }}</div>
		</div>
	`,
});

function openPreviewDialog(frm) {
	if (!frm.doc.template_name) {
		frappe.msgprint(__("Save the template first."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Payload Preview"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "preview_area" }],
	});
	dialog.show();

	const mountPoint = dialog.fields_dict.preview_area.$wrapper.get(0);
	const app = createApp(PayloadPreview, {
		messageTemplate: frm.doc.template_name,
		appliesTo: frm.doc.applies_to_doctype || "",
	});
	app.mount(mountPoint);
	dialog.onhide = () => app.unmount();
}

frappe.ui.form.on("Event Bus Message Template", {
	refresh(frm) {
		frm.add_custom_button(__("Preview Payload"), () => openPreviewDialog(frm));
	},
});
