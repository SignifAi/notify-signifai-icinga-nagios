This script plugs into Icinga v1, v2 and Nagios and sends an
incident event to [SignifAI](https://www.signifai.io).

## Installation

1. Depending on Icinga/Nagios version:
   a. v1 or Nagios: Update the API_KEY in the configuration (icinga/signifai.cfg) 
   to the API key you get from REST from https://app.signifai.io and the
   BUGSNAG_KEY to the key you get from SignifAI 
   b. v2: Update the signifai_api_key and signifai_bugsnag_key variables in 
   the "signifai" User object in icinga2/signifai.conf to the API key you 
   get from REST and the bugsnag key you get from SignifAI, respectively
2. Depending on Icinga/Nagios version:
   a. v1 or Nagios: Put icinga/signifai.cfg in your config directory (or add an 
   include= line to your icinga.cfg or nagios.cfg)
   b. v2: Put icinga2/signifai.cfg in your config directory (usually
   /etc/icinga2/conf.d/).
3. SignifAI optionally uses Bugsnag to monitor the operation of the script. To enable this functionality, install the Bugsnag Python module using `pip install bugsnag` and add the notification key provided by SignifAI with the `-b` flag.
4. Put send_signifai.py in:
   a. v1 or Nagios: The directory $USER1$ is set to ($USER1$ 
   is typically set by resources.cfg), which is usually 
   where all of your other Icinga/Nagios plugins are kept 
   anyway. Ensure it is chmod 0755 -- that is, 
   readable/writable/executable by its owning user and
   readable/executable by its group and the world. 
   b. v2: Whatever PluginDir in /etc/icinga2/constants.conf
   is set to; again, usually where all of your other Icinga
   plugins are kept anyway
5. For Nagios/v1: Add the contact/contact group 'signifai' to any host or
   service you want SignifAI to keep track of. It may help
   greatly to set this up in a service/host template -- see
   the Icinga/Nagios documentation for more information on
   using host/service templates.
   a. Icinga v2 users needn't do anything; the configuration will, by
   default, attach to _all available hosts and services_. If you want
   different behavior (a subset of hosts or services, for instance),
   you will need to modify the "assign where" clause in the host and
   service Notification objects.


## Command-line arguments

`-H`: the hostname of the machine with a status change.

`-S`: the name of the service with a status change. If omitted,
      it is assumed that the status change is for the _host_.

`-s`: The current (changed) state of the host or service. This
      can be in word form ("UP", "DOWN", "OK", "WARNING", "CRITICAL",
      "UNKNOWN") or in int form (0-3 with out-of-range being
      treated as UNKNOWN). 

`-k`: Your API key for the SignifAI application

`-o`: The output of the check; preferably including the extended
      (or "long") output.

`-U`: Treat UNKNOWN as CRITICAL. By default, UNKNOWNs generate an
      _additional_ critical event in SignifAI for the monitoring 
      host itself, in accordance with UNKNOWN as a state 
      indicating that a failure occurred with the check _itself_ 
      (e.g. failure to execute) rather than the resource being
      checked. With this flag set, that additional event will
      not be generated.

`-b`: If you have the bugsnag Python module installed and you
      provide a notification key to this flag, failures to
      send the event to SignifAI (but _not_ in option parsing
      or data generation, although the latter will often be
      caught as well) will be sent to bugsnag
