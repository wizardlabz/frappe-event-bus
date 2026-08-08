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
import { computed, createApp, defineComponent, onMounted, reactive, ref } from "vue/dist/vue.esm-bundler.js";

const PayloadPreview = defineComponent({
	name: "PayloadPreview",
	props: {
		messageTemplate: { type: String, required: true },
		appliesTo: { type: String, default: "" },
	},
	setup(props) {
		const state = reactive({
			loading: false,
			// Staged validation, so the UI can say which check failed.
			rendered: null,
			jsonValid: null,
			schemaPresent: false,
			schemaParsed: null,
			schemaValid: null,
			stage: null,
			output: "",
			error: "",
			referenceDoctype: props.appliesTo || "",
			referenceName: "",
		});

		// When the template is bound to a doctype we know what to preview
		// against, so offer a real Link picker instead of free text.
		const linkMount = ref(null);

		onMounted(async () => {
			if (!props.appliesTo || !linkMount.value) return;
			const control = frappe.ui.form.make_control({
				parent: linkMount.value,
				df: {
					fieldtype: "Link",
					options: props.appliesTo,
					label: __("Preview Against"),
					fieldname: "reference_name",
					// Rendering on selection removes the extra click; the
					// preview is something you glance at, not a job you launch.
					change: () => {
						const picked = control.get_value();
						if (picked === state.referenceName) return;
						state.referenceName = picked;
						if (picked) runPreview();
					},
				},
				render_input: true,
			});

			// Seed with the most recent document so the tab is useful on open.
			const recent = await frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: props.appliesTo,
					limit_page_length: 1,
					order_by: "modified desc",
				},
			});
			const seed = recent.message && recent.message[0] && recent.message[0].name;
			if (seed && !state.referenceName) {
				control.set_value(seed);
			}
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
				const d = r.message || {};
				state.rendered = d.rendered;
				state.jsonValid = d.json_valid;
				state.schemaPresent = d.schema_present;
				state.schemaParsed = d.schema_parsed;
				state.schemaValid = d.schema_valid;
				state.stage = d.stage;
				state.output = d.output || "";
				state.error = d.error || "";
			} catch (e) {
				state.rendered = false;
				state.jsonValid = false;
				state.schemaValid = null;
				state.schemaParsed = null;
				state.error = (e && e.message) || String(e);
			} finally {
				state.loading = false;
			}
		}

		const stageLabel = computed(() => {
			if (state.stage === "render") return __("Render error:");
			if (state.stage === "json") return __("JSON error:");
			if (state.stage === "schema_invalid") return __("Invalid schema:");
			if (state.stage === "schema") return __("Schema error:");
			return __("Error:");
		});

		// Four states, because "the schema is broken" is a different problem
		// from "the payload does not match it" and points at a different file.
		const schemaPill = computed(() => {
			if (!state.schemaPresent) return { color: "gray", text: __("No schema set") };
			if (state.schemaParsed === false) return { color: "orange", text: __("Invalid schema") };
			if (state.schemaValid) return { color: "green", text: __("Matches schema") };
			return { color: "red", text: __("Fails schema") };
		});

		return { state, runPreview, linkMount, stageLabel, schemaPill, __ };
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
			<div v-if="state.loading" class="text-muted mb-2">{{ __("Rendering...") }}</div>

			<div v-if="!state.loading && state.rendered !== null" class="mb-3">
				<span class="indicator-pill mr-2" :class="state.rendered ? 'green' : 'red'">
					{{ state.rendered ? __("Template renders") : __("Template failed") }}
				</span>
				<span class="indicator-pill mr-2" :class="state.jsonValid ? 'green' : 'red'">
					{{ state.jsonValid ? __("Valid JSON") : __("Invalid JSON") }}
				</span>
				<span class="indicator-pill" :class="schemaPill.color">{{ schemaPill.text }}</span>
			</div>

			<div v-if="state.error" class="alert alert-warning py-2">
				<b>{{ stageLabel }}</b> {{ state.error }}
			</div>

			<pre v-if="state.output" class="eb-output">{{ state.output }}</pre>
			<div v-if="!state.loading && state.rendered === null" class="text-muted">
				{{ __("Select a document to preview its payload.") }}
			</div>
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
