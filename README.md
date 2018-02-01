This script plugs into Icinga v1 and Nagios and sends an
incident event to [SignifAI](https://www.signifai.io).

## Installation

1. Update the API_KEY in the configuration (signifai.cfg) to
   the API key you get from REST from https://app.signifai.io
2. Put signifai.cfg in your config directory (or include it
   in your icinga.cfg or nagios.cfg)
3. SignifAI optionally uses Bugsnag to monitor the operation of the script. To enable this functionality, install the Bugsnag Python module using `pip install bugsnag` and add the notification key provided by SignifAI with the `-b` flag.
4. Put send_signifai.py in the directory $USER1$ is set to
   ($USER1$ is typically set by resources.cfg), which is 
   usually where all of your other Icinga/Nagios plugins
   are kept anyway. Ensure it is chmod 0755 -- that is,
   readable/writable/executable by its owning user and
   readable/executable by its group and the world. 
5. Add the contact/contact group 'signifai' to any host or
   service you want SignifAI to keep track of. It may help
   greatly to set this up in a service/host template -- see
   the Icinga/Nagios documentation for more information on
   using host/service templates.


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
