#!/usr/bin/python

from __future__ import absolute_import

try:
    import http.client as http_client
except ImportError:
    import httplib as http_client

import json
import logging
import os
import send_signifai
import socket
import sys
import time
import unittest


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
        return BaseHTTPSMock("")

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
                                         signifai_host="cantresolve.signifai.io")
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

if __name__=="__main__":
    unittest.main()