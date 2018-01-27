#!/usr/bin/python

from __future__ import absolute_import

try:
    import http.client as http_client
except ImportError:
    import httplib as http_client

import functools
import json
import logging
import os
import send_signifai
import socket
import time
import unittest


__author__ = "SignifAI, Inc."
__copyright__ = "Copyright (C) 2018, SignifAI, Inc."
__version__ = "1.0"


class BaseHTTPSRespMock(object):
    def __init__(self, data, status=200):
        self.readData = data
        self.status = status

    def read(self, *args, **kwargs):
        # e.g. throw IOError or socket.timeout
        return self.readData


class BaseHTTPSConnMock(object):
    def __init__(self, *args, **kwargs):
        # e.g. throw HTTPException
        self.args = args
        self.kwargs = kwargs

    def close(self):
        return True

    def connect(self):
        # e.g. try throwing timeout
        return True

    def getresponse(self):
        # e.g. try throwing IOError,
        #      returning bad JSON, etc.
        return BaseHTTPSRespMock("")

    def request(self, *args, **kwargs):
        # e.g. try throwing timeout
        return True


class TestHTTPPost(unittest.TestCase):
    corpus = {
        "event_source": "nagios",
        "service": "httpd",
        "timestamp": time.time(),
        "event_description": "web server down",
        "value": "critical",
        "attributes": {"state": "alarm"}
    }
    events = {"events": [corpus]}

    def setUp(self):
        hplog = logging.getLogger("http_post")
        hplog.setLevel(100)

    # Connection failure handling tests
    #   - Connection initialization
    def test_post_bad_host(self):
        # Should return False, NOT throw
        # (don't use a mock for this, it should never touch the collector)
        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         signifai_host="noresolve.signifai.io")
        self.assertFalse(result)

    def test_create_exception(self):
        # Should return False
        class AlwaysThrow(BaseHTTPSConnMock):
            retries = 0

            def __init__(self, *args, **kwargs):
                self.__class__.retries += 1
                raise http_client.HTTPException()

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=AlwaysThrow)
        self.assertFalse(result)
        # Ensure we don't attempt a retry
        self.assertEqual(AlwaysThrow.retries, 1)

    def test_connect_exception(self):
        # Should return False
        class AlwaysThrowOnConnect(BaseHTTPSConnMock):
            retries = 0

            def connect(self, *args, **kwargs):
                self.__class__.retries += 1
                raise http_client.HTTPException()

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=AlwaysThrowOnConnect)
        self.assertFalse(result)
        # Ensure we don't attempt a retry
        self.assertEqual(AlwaysThrowOnConnect.retries, 1)

    #   - Retry mechanism
    def test_connect_retries_fail(self):
        # Should return False
        total_retries = 5

        class AlwaysTimeout(BaseHTTPSConnMock):
            retry_count = 0

            def __init__(self, *args, **kwargs):
                super(self.__class__, self).__init__(*args, **kwargs)

            def connect(self):
                # The retry mechanism in POST_data will recreate
                # the connection object completely, so we need
                # to store the retries in the class, _not_ the
                # instance
                self.__class__.retry_count += 1
                raise socket.timeout

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         attempts=total_retries,
                                         httpsconn=AlwaysTimeout)
        self.assertFalse(result)
        self.assertEqual(AlwaysTimeout.retry_count, total_retries)

    def test_connect_retries_can_succeed(self):
        # Should return True
        total_retries = 5

        class SucceedsAtLast(BaseHTTPSConnMock):
            tries = 0

            def connect(self, *args, **kwargs):
                # The retry mechanism in POST_data will recreate
                # the connection object completely, so we need
                # to store the retries in the class, _not_ the
                # instance
                if self.__class__.tries < (total_retries-1):
                    self.__class__.tries += 1
                    raise socket.timeout
                else:
                    return True

            def getresponse(self):
                return BaseHTTPSRespMock(json.dumps({
                    "success": True,
                    "failed_events": []
                }))

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         attempts=total_retries,
                                         httpsconn=SucceedsAtLast)
        self.assertTrue(result)

    # Transport failures (requesting, getting response)
    #   - Request timeout
    def test_request_timeout(self):
        # Should return False, NOT throw

        class RequestTimesOut(BaseHTTPSConnMock):
            retries = 0

            def request(self, *args, **kwargs):
                self.__class__.retries += 1
                raise socket.timeout

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=RequestTimesOut)
        self.assertFalse(result)
        self.assertEqual(RequestTimesOut.retries, 1)

    #   - Misc. request error
    def test_request_httpexception(self):
        # Should return False, NOT throw

        class RequestThrows(BaseHTTPSConnMock):
            retries = 0

            def request(self, *args, **kwargs):
                self.__class__.retries += 1
                raise http_client.HTTPException()
        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=RequestThrows)
        self.assertFalse(result)
        self.assertEqual(RequestThrows.retries, 1)

    #   - Getresponse timeout
    def test_getresponse_timeout(self):
        # Should return False, NOT throw

        class GetResponseTimesOut(BaseHTTPSConnMock):
            def getresponse(self):
                raise socket.timeout

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=GetResponseTimesOut)
        self.assertFalse(result)

    #   - Misc. getresponse failure
    def test_getresponse_httpexception(self):
        # Should return False, NOT throw

        class GetResponseThrows(BaseHTTPSConnMock):
            def getresponse(self):
                raise http_client.HTTPException()

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=GetResponseThrows)
        self.assertFalse(result)

    #   - Server error
    def test_post_bad_status(self):
        # Should return False, NOT throw

        class BadStatus(BaseHTTPSConnMock):
            def getresponse(self):
                return BaseHTTPSRespMock("500 Internal Server Error",
                                         status=500)

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=BadStatus)
        self.assertFalse(result)

    # Data correctness failures (all other operations being successful,
    # but the server returned an error/failed event)
    #   - All events fail
    def test_post_bad_corpus(self):
        # Should return False, NOT throw

        class BadContent(BaseHTTPSConnMock):
            def request(self, *args, **kwargs):
                body = kwargs['body']
                self.failed_events = json.loads(body)['events']

            def getresponse(self):
                return BaseHTTPSRespMock(json.dumps({
                    "success": False,
                    "failed_events": self.failed_events
                }))

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=BadContent)
        self.assertIsNone(result)

    #   - Only some events fail (we treat that as a whole failure)
    def test_post_somebad_somegood(self):
        # Should return False, NOT throw
        events = {"events": [self.corpus, self.corpus]}

        class ReturnsPartialBad(BaseHTTPSConnMock):
            def request(self, *args, **kwargs):
                body = kwargs['body']
                self.failed_events = [{
                    "event": json.loads(body)['events'][1],
                    "error": "some error, doesn't matter"
                }]

            def getresponse(self):
                return BaseHTTPSRespMock(json.dumps({
                        "success": True,
                        "failed_events": self.failed_events
                }))

        result = send_signifai.POST_data(auth_key="", data=events,
                                         httpsconn=ReturnsPartialBad)
        self.assertIsNone(result)

    #   - Ensure request is made as expected based on parameters
    def test_post_request_generation(self):
        # Should return True AND no test case in TestEventGeneration
        # may fail
        test_case = self
        API_KEY = "TEST_API_KEY"

        class TestEventGeneration(BaseHTTPSConnMock):
            def request(self, method, uri, body, headers):
                # This sort of blows encapsulation, but whatever
                test_case.assertEqual(uri, send_signifai.DEFAULT_POST_URI)
                # XXX: json.dumps (or some underlying process) determinism
                #      (specifically, the string may not be generated the
                #      same in both cases due to key/value traversal order,
                #      etc.)
                test_case.assertEqual(body, json.dumps(test_case.events))
                test_case.assertEqual(headers['Authorization'],
                                      "Bearer {KEY}".format(KEY=API_KEY))
                test_case.assertEqual(headers['Content-Type'],
                                      "application/json")
                test_case.assertEqual(headers['Accept'],
                                      "application/json")
                test_case.assertEqual(method, "POST")

            def getresponse(self):
                return BaseHTTPSRespMock(json.dumps({
                    "success": True,
                    "failed_events": []
                }))

        result = send_signifai.POST_data(auth_key=API_KEY, data=self.events,
                                         httpsconn=TestEventGeneration)
        self.assertTrue(result)

    # Success tests
    #   - All is well
    def test_good_post(self):
        # Should return True

        class SucceedsToPOST(BaseHTTPSConnMock):
            def getresponse(self):
                return BaseHTTPSRespMock(json.dumps({
                    "success": True,
                    "failed_events": []
                }))

        result = send_signifai.POST_data(auth_key="", data=self.events,
                                         httpsconn=SucceedsToPOST)
        self.assertTrue(result)


class TestOptionParse(unittest.TestCase):
    def _do_test_envs(self, option_name, base_args, *envs):
        test_str = "TEST_STRING"
        test_str2 = "SHOULD_NEVER_BE"

        for i in range(0, len(envs)-1):
            os.environ[envs[i]] = test_str
            os.environ[envs[i+1]] = test_str2
            opts, _ = send_signifai.parse_opts(base_args)
            self.assertEqual(getattr(opts, option_name), test_str)
            self.assertNotEqual(getattr(opts, option_name), test_str2)
            del os.environ[envs[i]]
            del os.environ[envs[i+1]]

        os.environ[envs[-1]] = test_str
        opts, _ = send_signifai.parse_opts(base_args)
        del os.environ[envs[-1]]
        self.assertEqual(getattr(opts, option_name), test_str)

    def test_hostname_env_fallbacks(self):
        args = ["-s", "CRITICAL", "-o", "fake_output", "-k", "fake_key"]
        self._do_test_envs('hostname', args, "ICINGA_HOSTNAME",
                           "NAGIOS_HOSTNAME", "HOSTNAME")

    def test_no_host_fails(self):
        args = ["-S", "servicename", "-s", "CRITICAL", "-o", "fake output",
                "-k", "fake_key"]

        self.assertEqual(send_signifai.parse_opts(args), (None, None))

    def test_servicename_env_fallbacks(self):
        args = ["-H", "aHostname", "-o", "fake_output", "-k", "fake_key",
                "-s", "CRITICAL"]
        self._do_test_envs('service_name', args, "ICINGA_SERVICEDESC",
                           "NAGIOS_SERVICEDESC", "SERVICEDESC")

    def test_no_service_means_None(self):
        # Must set the service_name to None, which will in turn
        # handle the output as a host check result
        args = ["-H", "aHostname", "-o", "fake_output", "-k", "fake_key",
                "-s", "CRITICAL"]

        opts, _ = send_signifai.parse_opts(args)
        self.assertIsNone(opts.service_name)

    def test_service_state_int_aliasing(self):
        # Must translate the state index to CRITICAL
        args = ["-S", "fake_service", "-s", "2", "-o", "fake output",
                "-k", "fake_key", "-H", "fake_host"]

        opts, _ = send_signifai.parse_opts(args)
        self.assertEqual(opts.target_state, "CRITICAL")

    def test_service_state_valid_name(self):
        # Must allow CRITICAL to work
        args = ["-S", "fake_service", "-s", "CRITICAL", "-o", "fake output",
                "-k", "fake_key", "-H", "fake_host"]

        opts, _ = send_signifai.parse_opts(args)
        self.assertEqual(opts.target_state, "CRITICAL")

    def test_service_state_invalid_name(self):
        # Must totally fail
        args = ["-S", "fake_service", "-s", "BEEPBOOP", "-o", "fake output",
                "-k", "fake_key", "-H", "fake_host"]

        # Looks like this test will actually run this function three
        # times for some reason...
        self.assertEqual(send_signifai.parse_opts(args), (None, None))

    def test_no_output_means_empty(self):
        # Must be an empty string and NOT None
        args = ["-S", "fake_service", "-s", "CRITICAL",
                "-k", "fake_key", "-H", "fake_host"]

        opts, _ = send_signifai.parse_opts(args)
        self.assertEqual(opts.check_output, "")
        self.assertIsNotNone(opts.check_output, "")

    def test_output_env_fallback(self):
        TEST_BASE_OUTPUT = "summary line"
        TEST_LONG_OUTPUT = "extended information"
        target_prefixes = {
            "SERVICE": ["-S", "fake_service", "-s", "CRITICAL",
                        "-k", "fake_key", "-H", "fake_host"],
            "HOST": ["-H", "fake_host", "-s", "CRITICAL",
                     "-k", "fake_key"]
        }
        mon_prefixes = ("ICINGA_", "NAGIOS_", "")

        for prefix, args in target_prefixes.items():
            for envkey in mon_prefixes:
                for envkey2 in mon_prefixes:
                    envsummary = ("{envkey}{prefix}OUTPUT"
                                  .format(envkey=envkey, prefix=prefix))
                    envlong = ("{envkey}LONG{prefix}OUTPUT"
                               .format(envkey=envkey2, prefix=prefix))
                    os.environ[envsummary] = TEST_BASE_OUTPUT
                    os.environ[envlong] = TEST_LONG_OUTPUT
                    opts, _ = send_signifai.parse_opts(args)
                    expected = str.join("\n", [TEST_BASE_OUTPUT,
                                               TEST_LONG_OUTPUT])
                    self.assertEqual(opts.check_output, expected)
                    del os.environ[envsummary]
                    del os.environ[envlong]


def args_test(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        va_args = func(self, *args, **kwargs)

        opts = self._generate_options(*va_args)

        result = send_signifai.generate_REST_payload(opts)

        if opts.target_state == "UNKNOWN":
            self._assert_unknown_handling(opts, result['events'])
        else:
            self.assertEqual(len(result['events']), 1)
            event = result['events'][0]
            self._assert_static_fills(opts, event)
            self._assert_concrete_state_translation(opts.target_state, event)
    return wrapper


class TestPayloadGeneration(unittest.TestCase):
    def _generate_options(self, *args):
        opts, _ = send_signifai.parse_opts(list(args))
        self.assertNotEqual(opts, (None, None))
        return opts

    STATES_TRANSLATION = {
       "OK": {
           "value": "low",
           "state": "ok"
       },
       "WARNING": {
           "value": "medium",
           "state": "alarm"
       },
       "CRITICAL": {
           "value": "critical",
           "state": "alarm"
       },
       "UP": {
           "value": "low",
           "state": "ok"
       },
       "DOWN": {
           "value": "critical",
           "state": "alarm"
       }
    }

    def _assert_concrete_state_translation(self, state, event):
        expected = self.STATES_TRANSLATION[state]
        self.assertEqual(event['value'], expected['value'])
        self.assertEqual(event['attributes']['state'], expected['state'])

    def _assert_static_fills(self, options, event):
        self.assertEqual(event['host'], options.hostname)
        self.assertEqual(event['event_description'], options.check_output)
        if options.service_name:
            self.assertEqual(event['application'], options.service_name)

    def _assert_unknown_handling(self, options, events):
        if options.critical_unknowns:
            target_event = events[0]
        else:
            self.assertEqual(len(events), 2)
            host_responsible_event = events[0]
            target_event = events[1]

            self.assertEqual(host_responsible_event['application'], "icinga")
            self.assertEqual(host_responsible_event['host'],
                             socket.gethostname())
            event_attrs = host_responsible_event['attributes']
            target_host = event_attrs['application/target/host/name']
            if options.service_name:
                target_app = event_attrs['application/target/application/name']
                target_svc = event_attrs['application/target/service/name']
            self.assertEqual(target_host, options.hostname)
            if options.service_name:
                self.assertEqual(target_app, options.service_name)
                self.assertEqual(target_svc, options.service_name)
            self._assert_concrete_state_translation("CRITICAL",
                                                    host_responsible_event)

        self._assert_concrete_state_translation("CRITICAL", target_event)
        self._assert_static_fills(options, target_event)

    @args_test
    def test_host_up(self):
        return ["-H", "fakehost", "-s", "UP",
                "-k", "fake_key", "-o", "fake_output"]

    @args_test
    def test_host_down(self):
        return ["-H", "fakehost", "-s", "DOWN",
                "-k", "fake_key", "-o", "fake_output"]

    @args_test
    def test_host_unknown_normal(self):
        return ["-H", "fakehost", "-s", "UNKNOWN",
                "-k", "fake_key", "-o", "fake_output"]

    @args_test
    def test_host_unknown_as_crit(self):
        return ["-H", "fakehost", "-s", "UNKNOWN",
                "-k", "fake_key", "-o", "fake_output", "-U"]

    @args_test
    def test_service_ok(self):
        return ["-H", "fakehost", "-S", "fakesvc",
                "-k", "fake_key", "-s", "OK", "-o", "fake_output"]

    @args_test
    def test_service_warning(self):
        return ["-H", "fakehost", "-S", "fakesvc",
                "-k", "fake_key", "-s", "WARNING", "-o", "fake_output"]

    @args_test
    def test_service_critical(self):
        return ["-H", "fakehost", "-S", "fakesvc",
                "-k", "fake_key", "-s", "CRITICAL", "-o", "fake_output"]

    @args_test
    def test_service_unknown_normal(self):
        return ["-H", "fakehost", "-S", "fakesvc",
                "-k", "fake_key", "-s", "UNKNOWN", "-o", "fake_output"]

    @args_test
    def test_service_unknown_as_crit(self):
        return ["-H", "fakehost", "-S", "fakesvc",
                "-k", "fake_key", "-s", "UNKNOWN", "-o", "fake_output",
                "-U"]


if __name__ == "__main__":
    unittest.main()
