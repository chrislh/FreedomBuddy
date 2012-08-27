#! /usr/bin/env python # -*- mode: auto-fill; fill-column: 80 -*-

"""Making Santiago dance, in 4 parts:

- Validating the initial request (playing B).
- Validating the initial response (playing A).
  - Validating the silent response.
  - Validating the rejection response.
  - Validating the acceptance response.
  - Validating the forwarded request (playing C).
- Validating the forwarded request (playing D, when C isn't the target).
- Validating the forwarded response.
  - Validating the direct response (playing A).
  - Validating the indirect response (playing C, B, and A).

"""

import os
import sys
import unittest

import gnupg
import json
import logging
import santiago
import utilities


class SantiagoTest(unittest.TestCase):
    """The base class for tests."""

    if sys.version_info < (2, 7):
        """Add a poor man's forward compatibility."""
  
        class ContainsError(AssertionError):
            pass

        def assertIn(self, a, b):
            if not a in b:
                raise self.ContainsError("%s not in %s" % (a, b))

class UnpackRequest(SantiagoTest):

    """Are requests unpacked as expected?

    - Messages that aren't for me (that I can't decrypt) are ignored.
    - Messages with invalid signatures are rejected.
    - Only passing messages return the dictionary.
    - Each message identifies the Santiago protocol version it uses.
    - Messages come with a range of Santiago protocol versions I can reply with.
    - Messages that don't share any of my versions are ignored (either the
      client or I won't be able to understand the message).
    - The message is unpacked correctly.  This is a bit difficult because of the
      number of overlapping data types.

      First, we have the keys that must be present in each message:

      - client
      - host
      - service
      - locations
      - reply_to
      - request_version
      - reply_versions

      Next the list-keys which must be lists (they'll later be converted
      directly to sets):

      - reply_to
      - locations
      - reply_versions

      Finally, we have the keys that may be empty:

      - locations
      - reply_to

      ``locations`` is empty on an incoming (request) message, while
      ``reply_to`` may be assumed if the reply destinations haven't changed
      since the previous message.  If they have, and the client still doesn't
      send the reply_to, then the host will be unable to communicate with it, so
      it's in the client's best interests to send it whenever reasonable.

      So, the structure of a message is a little weird here.  We have three sets
      of overlapping requirements:

      #. Certain keys must be present.
      #. Certain keys must be lists.
      #. Certain keys may be unset.

      The really odd ones out are "locations" and "reply_to", which fall into
      all three categories.

    """
    def setUp(self):
        """Create a request."""

        self.gpg = gnupg.GPG(use_agent = True)

        self.keyid = utilities.load_config().get("pgpprocessor", "keyid")

        self.santiago = santiago.Santiago(me = self.keyid)

        self.request = { "host": self.keyid, "client": self.keyid,
                         "service": santiago.Santiago.SERVICE_NAME, "reply_to": [1],
                         "locations": [1],
                         "request_version": 1, "reply_versions": [1], }

        self.ALL_KEYS = set(("host", "client", "service",
                             "locations", "reply_to",
                             "request_version", "reply_versions"))
        self.REQUIRED_KEYS = set(("client", "host", "service",
                                  "request_version", "reply_versions"))
        self.OPTIONAL_KEYS = set(("locations", "reply_to"))
        self.LIST_KEYS = set(("reply_to", "locations", "reply_versions"))

    def test_valid_message(self):
        """A message that should pass does pass normally."""

        adict = self.validate_request(dict(self.request))
        self.request = self.wrap_message(self.request)

        self.assertEqual(self.santiago.unpack_request(self.request), adict)

    def validate_request(self, adict):
        adict.update({ "from": self.keyid,
                       "to": self.keyid })

        return adict

    def test_request_contains_all_keys(self):
        """The test request needs all supported keys."""

        for key in self.ALL_KEYS:
            self.assertIn(key, self.request)

    def wrap_message(self, message):
        """The standard wrapping method for these tests."""

        return str(self.gpg.encrypt(json.dumps(message),
                                    recipients=[self.keyid],
                                    sign=self.keyid))

    def test_key_lists_updated(self):
        """Are the lists of keys up-to-date?"""

        for key in ("ALL_KEYS", "REQUIRED_KEYS", "OPTIONAL_KEYS", "LIST_KEYS"):
            self.assertEqual(getattr(self, key),
                             getattr(santiago.Santiago, key))

    def test_all_keys_accounted_for(self):
        """All the keys in the ALL_KEYS list are either required or optional."""

        self.assertEqual(set(self.ALL_KEYS),
                         set(self.REQUIRED_KEYS) | set(self.OPTIONAL_KEYS))

    def test_requred_keys_are_required(self):
        """If any required keys are missing, the message is skipped."""

        for key in self.ALL_KEYS:
            broken_dict = dict(self.request)
            del broken_dict[key]
            encrypted_data = self.wrap_message(broken_dict)

            self.assertEqual(self.santiago.unpack_request(encrypted_data), None)

    def test_non_null_keys_are_set(self):
        """If any keys that can't be empty are empty, the message is skipped."""

        for key in self.REQUIRED_KEYS:
            broken_dict = dict(self.request)
            broken_dict[key] = None
            encrypted_data = self.wrap_message(broken_dict)

            self.assertEqual(self.santiago.unpack_request(encrypted_data), None)

    def test_null_keys_are_null(self):
        """If any optional keys are null, the message's still processed."""

        for key in self.OPTIONAL_KEYS:
            broken_dict = dict(self.request)
            broken_dict[key] = None
            encrypted_data = self.wrap_message(broken_dict)

            broken_dict = self.validate_request(broken_dict)

            self.assertEqual(self.santiago.unpack_request(encrypted_data),
                             broken_dict)

    def test_skip_undecryptable_messages(self):
        """Mesasges that I can't decrypt (for other folks) are skipped.

        I don't know how I'll encrypt to a key that isn't there though.

        """
        pass

    def test_skip_invalid_signatures(self):
        """Messages with invalid signatures are skipped."""

        self.request = self.wrap_message(self.request)

        # delete the 7th line for the fun of it.
        mangled = self.request.splitlines(True)
        del mangled[7]
        self.request = "".join(mangled)

        self.assertEqual(self.santiago.unpack_request(self.request), None)

    def test_incoming_lists_are_lists(self):
        """Any variables that must be lists, before processing, actually are."""

        for key in self.LIST_KEYS:
            broken_request = dict(self.request)
            broken_request[key] = 1
            broken_request = self.wrap_message(broken_request)

            self.assertEqual(self.santiago.unpack_request(broken_request), None)

    def test_require_protocol_version_overlap(self):
        """Clients that can't accept protocols I can send are ignored."""

        santiago.Santiago.SUPPORTED_PROTOCOLS, unsupported = \
            set(["e"]), santiago.Santiago.SUPPORTED_PROTOCOLS

        self.request = self.wrap_message(self.request)

        self.assertFalse(self.santiago.unpack_request(self.request))

        santiago.Santiago.SUPPORTED_PROTOCOLS, unsupported = \
            unsupported, santiago.Santiago.SUPPORTED_PROTOCOLS

        self.assertTrue(santiago.Santiago.SUPPORTED_PROTOCOLS, set([1]))

    def test_require_protocol_version_understanding(self):
        """The service must ignore any protocol versions it can't understand."""

        self.request["request_version"] = "e"

        self.request = self.wrap_message(self.request)

        self.assertFalse(self.santiago.unpack_request(self.request))

class HandleRequest(SantiagoTest):
    """Process an incoming request, from a client, for to host services.

    - Verify we're willing to host for both the client and proxy.  If we
      aren't, quit and return nothing.
    - Forward the request if it's not for me.
    - Learn new Santiagi if they were sent.
    - Reply to the client on the appropriate protocol.

    """
    def setUp(self):
        """Do a good bit of setup to make this a nicer test-class.

        Successful tests will call ``Santiago.outgoing_request``, so that's
        overridden to record that the method is called.

        """
        self.keyid = utilities.load_config().get("pgpprocessor", "keyid")

        self.santiago = santiago.Santiago(
            hosting = {self.keyid: {santiago.Santiago.SERVICE_NAME: [1] }},
            consuming = {self.keyid: {santiago.Santiago.SERVICE_NAME: [1] }},
            me = self.keyid)

        self.santiago.requested = False
        self.santiago.outgoing_request = (lambda *args, **kwargs:
                                              self.record_success())

        self.from_ = self.keyid
        self.to = self.keyid
        self.host = self.keyid
        self.client = self.keyid
        self.service = santiago.Santiago.SERVICE_NAME
        self.reply_to = [1]
        self.request_version = 1
        self.reply_versions = [1]

    def record_success(self):
        """Record that we tried to reply to the request."""

        self.santiago.requested = True

    def test_call(self):
        """A short-hand for calling handle_request with all 8 arguments.  Oy."""

        self.santiago.handle_request(
                self.from_, self.to,
                self.host, self.client,
                self.service, self.reply_to,
                self.request_version, self.reply_versions)

    def test_valid_message(self):
        """Reply to valid messages."""

        self.test_call()

        self.assertTrue(self.santiago.requested)

    def test_unwilling_source(self):
        """Don't handle the request if the cilent or proxy isn't trusted.

        Ok, so, "isn't trusted" is the wrong turn of phrase here.  Technically,
        it's "this Santiago isn't willing to host services for", but the
        former's much easier to type.

        """
        for key in ("client", ):
            setattr(self, key, 0)

            self.test_call()

            self.assertFalse(self.santiago.requested)

    def test_learn_services(self):
        """New reply_to locations are learned."""

        self.reply_to.append(2)

        self.test_call()

        self.assertTrue(self.santiago.requested)
        self.assertEqual(self.santiago.consuming[self.keyid][santiago.Santiago.SERVICE_NAME],
                         [1, 2])

# class HandleReply(SantiagoTest):

#     """
#     def handle_reply(self, from_, to, host, client,
#                      service, locations, reply_to):
#         "Process a reply from a Santiago service.

#         The last call in the chain that makes up the Santiago system, we now
#         take the reply from the other Santiago server and learn any new service
#         locations, if we've requested locations for that service."

#     """
#     def test_valid_message(self):
#         """A valid message should teach new service locations."""

#         self.fail()

#     def test_no_request_to_host(self):
#         """If I haven't asked the host for any services, ignore the reply."""

#         self.fail()

#     def test_no_request_for_service(self):
#         """If I haven't asked the host for this service, ignore the reply."""

#         self.fail()

#     def test_not_to_me(self):
#         """Ignore messages to another Santiago service.

#         if not self.i_am(to):

#         """

#         self.fail()

#     def test_for_other_client(self):
#         """Ignore messages that another Santiago is the client for.

#         if not self.i_am(client):

#         """

#         self.fail()

#     def test_learn_santiago_locations(self):
#         """New Santiago locations are learned."""

#         self.fail()

#     def test_learn_service_locations(self):
#         """New service locations are learned."""

#         self.fail()

#     def test_dequeue_service_request(self):
#         """Don't accept further service requests after the request is handled.

#         Of course, this has its limits.  Multiple requests to the same host
#         would create multiple outstanding requests. Should they?  Think on that.

#         """
#         self.fail()

class OutgoingRequest(SantiagoTest):
    """Are outgoing requests properly formed?

    Here, we'll use a faux Santiago Sender that merely records and decodes the
    request when it goes out.

    """
    class TestRequestSender(object):
        """A barebones sender that records details about the request."""

        def __init__(self):
            self.gpg = gnupg.GPG(use_agent = True)

        def outgoing_request(self, request, destination):
            """Decrypt and record the pertinent details about the request."""

            self.destination = destination
            self.crypt = request
            self.request = str(self.gpg.decrypt(str(request)))

    def setUp(self):
        """Create an encryptable request."""

        self.keyid = utilities.load_config().get("pgpprocessor", "keyid")

        self.santiago = santiago.Santiago(
            me = self.keyid,
            consuming = { self.keyid: { santiago.Santiago.SERVICE_NAME: ( "https://1", )}})

        self.request_sender = OutgoingRequest.TestRequestSender()
        self.santiago.senders = { "https": self.request_sender }

        self.host = self.keyid
        self.client = self.keyid
        self.service = santiago.Santiago.SERVICE_NAME
        self.reply_to = [ "https://1" ]
        self.locations = [1]
        self.request_version = 1
        self.reply_versions = [1]

        self.request = {
            "host": self.host, "client": self.client,
            "service": self.service,
            "reply_to": self.reply_to, "locations": self.locations,
            "request_version": self.request_version,
            "reply_versions": self.reply_versions }

    def outgoing_call(self):
        """A short-hand for calling outgoing_request with all 8 arguments."""

        self.santiago.outgoing_request(
            None, None, self.host, self.client,
            self.service, self.locations, self.reply_to)

    def test_valid_message(self):
        """Are valid messages properly encrypted and delivered?"""

        self.outgoing_call()

        self.assertEqual(self.request_sender.request,
                         json.dumps(self.request))
        self.assertEqual(self.request_sender.destination, self.reply_to[0])

    def test_queue_service_request(self):
        """Add the host's service to the request queue."""

        self.outgoing_call()

        self.assertIn(self.service, self.santiago.requests[self.host])

    def test_transparent_unwrapping(self):
        """Is the unwrapping process transparent?"""

        import urlparse, urllib

        self.outgoing_call()

        request = {"request": str(self.request_sender.crypt) }

        self.assertEqual(request["request"],
                         urlparse.parse_qs(urllib.urlencode(request))
                         ["request"][0])

class CreateHosting(SantiagoTest):
    """Are clients, services, and locations learned correctly?

    Each should be available in ``self.hosting`` after it's learned.

    """
    def setUp(self):
        self.keyid = utilities.load_config().get("pgpprocessor", "keyid")

        self.santiago = santiago.Santiago(me = self.keyid)

        self.client = 1
        self.service = 2
        self.location = 3

    def test_add_hosting_client(self):
        self.santiago.create_hosting_client(self.client)
        self.assertIn(self.client, self.santiago.hosting)

    def test_add_hosting_service(self):
        self.santiago.create_hosting_service(self.client, self.service)
        self.assertIn(self.service, self.santiago.hosting[self.client])

    def test_add_hosting_location(self):
        self.santiago.create_hosting_location(self.client, self.service,
                                              [self.location])
        self.assertIn(self.location,
                        self.santiago.hosting[self.client][self.service])

class CreateConsuming(SantiagoTest):
    """Are hosts, services, and locations learned correctly?

    Each should be available in ``self.consuming`` after it's learned.

    """
    def setUp(self):
        self.keyid = utilities.load_config().get("pgpprocessor", "keyid")

        self.santiago = santiago.Santiago(me = self.keyid)

        self.host = 1
        self.service = 2
        self.location = 3

    def test_add_consuming_host(self):
        self.santiago.create_consuming_host(self.host)

        self.assertIn(self.host, self.santiago.consuming)

    def test_add_consuming_service(self):
        self.santiago.create_consuming_service(self.host, self.service)

        self.assertIn(self.service, self.santiago.consuming[self.host])

    def test_add_consuming_location(self):
        self.santiago.create_consuming_location(self.host,self.service,
                                                [self.location])

        self.assertIn(self.location,
                       self.santiago.consuming[self.host][self.service])

if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
