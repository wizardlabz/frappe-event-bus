# Installation

## Requirements

- A Frappe **v15** bench (ERPNext optional — the core depends only on Frappe)
- Python 3.11+
- A running Frappe scheduler
- At least one broker, if you want messages to go anywhere

The core app has no broker dependency. Broker libraries such as `pika` come with the provider app you install.

## Install the core

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/wizardlabz/frappe-event-bus --branch main
bench --site <your-site> install-app frappe_event_bus
bench --site <your-site> migrate
```

## Install a provider

Providers are separate apps. For RabbitMQ:

```bash
bench get-app https://github.com/wizardlabz/frappe-event-bus-rabbitmq --branch main
bench --site <your-site> install-app frappe_event_bus_rabbitmq
```

The provider refuses to install if the core is missing, with a clear message rather than an import error. You can add providers later without reinstalling or reconfiguring the core.

## Enable the bus

The bus ships **disabled**. Until you turn it on, saving documents creates no outbox rows however many rules exist.

Open **Event Bus Settings** and check **Enabled**, or:

```bash
bench --site <your-site> set-config -p enable_scheduler true
bench --site <your-site> console
```

```python
settings = frappe.get_doc("Event Bus Settings")
settings.enabled = 1
settings.save()
frappe.db.commit()
```

Review the other five fields while you are there — see the [settings reference](reference/settings.md).

## Confirm the scheduler is running

Publishing leans on two scheduled jobs: a 5-minute pass that drains due messages and retries, and a daily retention purge. Messages also publish immediately after the triggering transaction commits, but retries depend entirely on the scheduler.

```bash
bench --site <your-site> doctor
bench --site <your-site> enable-scheduler
```

If outbox messages sit in `Pending` and never move, an idle scheduler is the usual cause.

## Verify the install

```bash
bench --site <your-site> console
```

```python
frappe.get_installed_apps()          # includes frappe_event_bus
frappe.get_doc("Event Bus Settings").enabled

from frappe_event_bus.providers.registry import get_providers
get_providers()                      # {'rabbitmq': {...}} once a provider is installed
```

An empty registry means no provider app is installed, or its `event_bus_providers` hook is not being picked up — try `bench --site <your-site> migrate && bench restart`.

## Upgrading

```bash
cd $PATH_TO_YOUR_BENCH/apps/frappe_event_bus
git pull
cd $PATH_TO_YOUR_BENCH
bench --site <your-site> migrate
bench restart
```

Keep provider major versions aligned with the core — see [version compatibility](concepts/providers.md#version-compatibility).

## Next

[Getting started](getting-started.md) walks through publishing your first message.
