/**
 * Vue 3 payload preview for Event Bus Message Templates.
 *
 * Adds a "Preview Payload" button to the Message Template form. Clicking it
 * opens a dialog hosting a small reactive Vue app that calls the whitelisted
 * `preview_payload` API and renders the JSON output with a validation badge.
 */

// Import the compiler-included Vue build: these components declare their markup
// via the string `template:` option, which the runtime-only build silently
// ignores (it renders an empty comment node, with no console error under a
// production build). See docs/development/template-authoring-design.md.
import { createApp, defineComponent, onMounted, reactive, ref } from "vue/dist/vue.esm-bundler.js";

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

/** Tear down any previously mounted preview so refreshes don't stack apps. */
function unmountPreview(frm) {
	if (frm.__ebPreviewApp) {
		frm.__ebPreviewApp.unmount();
		frm.__ebPreviewApp = null;
	}
}

/**
 * Mount the preview inline in the Validation & Preview tab.
 *
 * The preview reads the *saved* template server-side, so an unsaved document
 * has nothing to render against — say so rather than mounting a widget whose
 * button would always fail.
 */
function mountPreview(frm) {
	const field = frm.get_field("payload_preview_html");
	if (!field) return;

	unmountPreview(frm);
	const wrapper = field.$wrapper;
	wrapper.empty();

	if (frm.is_new() || !frm.doc.template_name) {
		wrapper.html(
			`<div class="text-muted">${__("Save the template to preview its payload.")}</div>`
		);
		return;
	}

	const mountPoint = $('<div class="eb-preview-mount"></div>').appendTo(wrapper).get(0);
	const app = createApp(PayloadPreview, {
		messageTemplate: frm.doc.template_name,
		appliesTo: frm.doc.applies_to_doctype || "",
	});
	app.mount(mountPoint);
	frm.__ebPreviewApp = app;
}

frappe.ui.form.on("Event Bus Message Template", {
	refresh(frm) {
		mountPreview(frm);
	},

	applies_to_doctype(frm) {
		// The document picker is bound to this doctype, so rebuild it.
		mountPreview(frm);
	},

	onload_post_render(frm) {
		frm.$wrapper.on("remove", () => unmountPreview(frm));
	},
});
