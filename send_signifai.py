#!/usr/bin/python

from __future__ import absolute_import

try:
    # We want to be able to report to bugsnag if present,
    # but if it's not we want to handle that gracefully
    import bugsnag
except ImportError:
    bugsnag = None
from copy import deepcopy
import json
import logging
try:
    # python3
    import http.client as http_client
except ImportError:
    # python2
    import httplib as http_client

from optparse import OptionParser
import os
import socket
import sys
import time


DEFAULT_POST_URI = "/v1/incidents"


def bugsnag_notify(exception, metadata, log=None):
    if not log:
        log = logging.getLogger("bugsnag_unattached_notify")

    if not bugsnag:
        log.warning("Can't notify bugsnag: module not installed!")
        return True

    return bugsnag.notify(exception, metadata)


def POST_data(auth_key, data,
              signifai_host="collectors.signifai.io",
              signifai_port=http_client.HTTPS_PORT,
              signifai_uri=DEFAULT_POST_URI,
              timeout=5,
              attempts=5,
              httpsconn=http_client.HTTPSConnection):
    log = logging.getLogger("http_post")
    client = None
    retries = 0
    while client is None and retries < attempts:
        try:
            client = httpsconn(host=signifai_host,
                               port=signifai_port,
                               timeout=timeout)
        except http_client.HTTPException as http_exc:
            # uh, if we can't even create the object, we're toast
            log.fatal("Couldn't create HTTP connection object", exc_info=True)
            return False

        try:
            client.connect()
        except socket.timeout:
            # try again until we expire
            log.info("Connection timed out; on retry {retries} of {attempts}"
                     .format(retries=retries, attempts=attempts))
            retries += 1
            client.close()
            client = None
            continue
        except (http_client.HTTPException, socket.error) as http_exc:
            log.fatal("Couldn't connect to SignifAi collector", exc_info=True)
            return False

    if client is None and retries == attempts:
        # we expired
        log.fatal("Could not connect successfully after {attempts} attempts"
                  .format(attempts=attempts))
        return False
    else:
        headers = {
            "Authorization": "Bearer {auth_key}".format(auth_key=auth_key),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        res = None
        try:
            client.request("POST", signifai_uri, body=json.dumps(data),
                           headers=headers)
        except socket.timeout:
            # ... don't think we should retry the POST
            log.fatal("POST timed out...?")
            return False
        except (http_client.HTTPException, socket.error) as http_exc:
            # nope
            log.fatal("Couldn't POST to SignifAi Collector", exc_info=True)
            return False

        try:
            res = client.getresponse()
        except socket.timeout:
            # ... don't think we should retry here
            log.fatal("Response from server timed out...?")
            return False
        except (http_client.HTTPException, socket.error) as http_exc:
            log.fatal("Couldn't get server response")
            return False

        if 200 <= res.status < 300:
            try:
                collector_response = json.loads(res.read())
            except (ValueError, json.JSONDecodeError):
                log.fatal("Didn't receive valid JSON response from collector")
                return False
            except IOError:
                log.fatal("Couldn't read response from collector",
                          exc_info=True)
            else:
                if (not collector_response['success'] or
                        collector_response['failed_events']):
                    errs = collector_response['failed_events']
                    log.fatal("Errors submitting events: {errs}"
                              .format(errs=errs))
                    # not really False but not really True
                    return None
                else:
                    return True
        else:
            log.fatal("Received error from SignifAi Collector, body follows: ")
            log.fatal(res.read())
            return False


def try_get_env(*possibilities):
    value = None
    for which in possibilities:
        try:
            value = os.environ[which]
        except KeyError:
            pass
        else:
            break
    return value


def icingios_get_env(macro_name, default=None):
    macro = macro_name.upper()
    icinga_env_var = "ICINGA_{macro}".format(macro=macro)
    nagios_env_var = "NAGIOS_{macro}".format(macro=macro)
    ret = try_get_env(icinga_env_var, nagios_env_var, macro)
    if ret is None:
        return default
    return ret


def parse_opts(argv=None):
    parser = OptionParser()
    log = logging.getLogger("option_parser")

    parser.add_option("-H", "--host",
                      help="Hostname of machine with issue",
                      action="store", dest="hostname", type=str,
                      default=icingios_get_env("HOSTNAME"))

    parser.add_option("-S", "--service",
                      help="Service name of service with issue",
                      action="store", dest="service_name", type=str,
                      default=icingios_get_env("SERVICEDESC"))

    parser.add_option("-s", "--state",
                      help="The host or service's current state",
                      action="store", dest="target_state", type=str,
                      default=None)

    parser.add_option("-o", "--output",
                      help="The check output (preferably $*OUTPUT$ + "
                           "$*LONGOUTPUT$)",
                      action="store", dest="check_output", type=str,
                      default=None)

    parser.add_option("-k", "--auth-key",
                      help="The SignifAi auth key for the collector API",
                      action="store", dest="auth_key", type=str,
                      default=None)

    parser.add_option("-U", "--unknown-is-critical",
                      help="Treat UNKNOWN as CRITICAL/DOWN",
                      action="store_true", dest="critical_unknowns",
                      default=False)

    parser.add_option("-b", "--bugsnag-key",
                      help="Report errors to bugsnag with notification key",
                      action="store", dest="bugsnag_key", type=str,
                      default=None)

    if argv is None:
        argv = sys.argv

    (options, args) = parser.parse_args(argv)

    ICINGIOS_SERVICE_STATES = ["OK", "WARNING", "CRITICAL", "UNKNOWN"]
    ICINGIOS_HOST_STATES = ["UP", "DOWN"]
    if options.auth_key is None:
        log.fatal("No auth key specified")
        return (None, None)

    try:
        options.target_state = int(options.target_state)
    except TypeError:
        if options.target_state is None:
            log.fatal("No state specified")
            return (None, None)

        if (options.target_state.upper() not in ICINGIOS_SERVICE_STATES or
                options.target_state.upper() not in ICINGIOS_HOST_STATES):
            log.fatal("Invalid state specified")
            return (None, None)
        else:
            options.target_state = options.target_state.upper()
    else:
        try:
            if options.service_name is None:
                target_state = ICINGIOS_HOST_STATES[options.target_state]
            else:
                target_state = ICINGIOS_SERVICE_STATES[options.target_state]
            options.target_state = target_state
        except IndexError:
            # rip
            options.target_state = "UNKNOWN"

    if not options.hostname:
        log.fatal("No/invalid hostname specified")
        return (None, None)

    if not options.check_output:
        # Fill out the output from environment variables then if we can
        if options.service_name is None:
            # host output
            options.check_output = (icingios_get_env("HOSTOUTPUT", "") +
                                    icingios_get_env("LONGHOSTOUTPUT", ""))
        else:
            # service output
            options.check_output = (icingios_get_env("SERVICEOUTPUT", "") +
                                    icingios_get_env("LONGSERVICEOUTPUT", ""))

    if options.bugsnag_key:
        if bugsnag:
            project_root = os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__)
                )
            )
            bugsnag.configure(
                api_key=options.bugsnag_key,
                project_root=project_root
            )
        else:
            log.warning("Couldn't initialize bugsnag: bugsnag not present")

    return (options, args)


def main(argv=sys.argv):
    argv.pop(0)

    oplog = logging.getLogger("option_parser")
    oplog.setLevel(20)
    oplog.addHandler(logging.StreamHandler(sys.stdout))
    (options, args) = parse_opts(argv)

    if options is None:
        return 1

    ICINGIOS2PRI = {
        "WARNING": "medium",
        "CRITICAL": "critical",
        "DOWN": "critical",
        "UNKNOWN": "critical"
    }

    REST_target = {
        "event_source": "icinga",
        "timestamp": int(time.time()),
        "host": options.hostname,
        "event_description": options.check_output,
        "attributes": {}
    }
    REST_events = {"events": []}

    if options.target_state in ("OK", "UP"):
        REST_target['value'] = "low"
        REST_target['attributes']['state'] = "ok"
    elif options.target_state == "UNKNOWN" and not options.critical_unknowns:
        # Create and append
        REST_host = deepcopy(REST_target)
        REST_host['host'] = socket.gethostname()
        REST_host['application'] = "icinga"
        REST_host['attributes'] = {
            "application/target/host/name": options.hostname,
            "state": "alarm"
        }
        if options.service_name:
            APPLICATION_NAME = "application/target/application/name"
            SERVICE_NAME = "application/target/service/name"
            REST_host['attributes'][APPLICATION_NAME] = options.service_name
            REST_host['attributes'][SERVICE_NAME] = options.service_name

        REST_host['value'] = "critical"
        REST_events['events'].append(REST_host)

        REST_target['value'] = "critical"
        REST_target['attributes']['state'] = "alarm"
    else:
        REST_target['value'] = ICINGIOS2PRI[options.target_state]
        REST_target['attributes']['state'] = "alarm"
        if options.service_name:
            REST_target['service'] = options.service_name

    REST_events['events'].append(REST_target)

    postlog = logging.getLogger("http_post")
    postlog.setLevel(20)
    postlog.addHandler(logging.StreamHandler(sys.stdout))
    try_post = POST_data(options.auth_key, REST_events)
    if not try_post:
        return 1
    else:
        return 0

    pass


if __name__ == "__main__":
    sys.exit(main())