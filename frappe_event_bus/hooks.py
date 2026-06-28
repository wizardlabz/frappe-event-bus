app_name = "frappe_event_bus"
app_title = "Frappe Event Bus"
app_publisher = "WizardLabz"
app_description = "Bring event-driven architecture to ERPNext and Frappe."
app_email = "amir.magdy@wizardlabz.com"
app_license = "gpl-3.0"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "frappe_event_bus",
# 		"logo": "/assets/frappe_event_bus/logo.png",
# 		"title": "Frappe Event Bus",
# 		"route": "/frappe_event_bus",
# 		"has_permission": "frappe_event_bus.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_event_bus/css/frappe_event_bus.css"
# app_include_js = "/assets/frappe_event_bus/js/frappe_event_bus.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_event_bus/css/frappe_event_bus.css"
# web_include_js = "/assets/frappe_event_bus/js/frappe_event_bus.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_event_bus/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_event_bus/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_event_bus.utils.jinja_methods",
# 	"filters": "frappe_event_bus.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_event_bus.install.before_install"
# after_install = "frappe_event_bus.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "frappe_event_bus.uninstall.before_uninstall"
# after_uninstall = "frappe_event_bus.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_event_bus.utils.before_app_install"
# after_app_install = "frappe_event_bus.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_event_bus.utils.before_app_uninstall"
# after_app_uninstall = "frappe_event_bus.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_event_bus.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_event_bus.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_event_bus.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_event_bus.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_event_bus.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_event_bus.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_event_bus.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_event_bus.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_event_bus.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_event_bus.utils.before_request"]
# after_request = ["frappe_event_bus.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_event_bus.utils.before_job"]
# after_job = ["frappe_event_bus.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_event_bus.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


# =============================================================================
# Frappe Event Bus configuration
# =============================================================================

# Frontend: Message Template payload preview (Vue 3).
app_include_js = "/assets/frappe_event_bus/js/payload_preview.bundle.js"

# Generic document-event hook -> rule engine.
doc_events = {
	"*": {
		"after_insert": "frappe_event_bus.rule_engine.handle_event",
		"on_update": "frappe_event_bus.rule_engine.handle_event",
		"on_submit": "frappe_event_bus.rule_engine.handle_event",
		"on_cancel": "frappe_event_bus.rule_engine.handle_event",
		"on_trash": "frappe_event_bus.rule_engine.handle_event",
	}
}

# Drain the outbox on a schedule (retry due / pending messages).
scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"frappe_event_bus.publisher.retry.process_outbox",
		],
	},
}

# Providers are contributed by separate provider apps via this hook. Each entry
# is a dotted path to a callable returning a provider spec dict:
#   {"name", "label", "connection_doctype", "destination_doctype", "publisher"}
event_bus_providers = []
