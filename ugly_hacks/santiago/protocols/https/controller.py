"""The HTTPS Santiago listener and sender.

FIXME: add real authentication.
FIXME: all the Blammos.  They're terrible, unacceptable failures.
FIXME correct direct key access everywhere.

"""

import santiago

from Cheetah.Template import Template
import cherrypy
import httplib, urllib, urlparse
import sys
import logging


def allow_ips(ips = None):
    """Refuse connections from non-whitelisted IPs.

    Defaults to the localhost.

    Hook documentation is available in:

    http://docs.cherrypy.org/dev/progguide/extending/customtools.html

    """
    if ips == None:
        ips = [ "127.0.0.1" ]

    if cherrypy.request.remote.ip not in ips:
        santiago.debug_log("Request from non-local IP.  Forbidden.")
        raise cherrypy.HTTPError(403)

cherrypy.tools.ip_filter = cherrypy.Tool('before_handler', allow_ips)

def start(*args, **kwargs):
    """Module-level start function, called after listener and sender started.

    """
    cherrypy.engine.start()

def stop(*args, **kwargs):
    """Module-level stop function, called after listener and sender stopped.

    """
    cherrypy.engine.stop()
    cherrypy.engine.exit()


class Listener(santiago.SantiagoListener):

    def __init__(self, my_santiago, socket_port=0,
                 ssl_certificate="", ssl_private_key="", **kwargs):

        santiago.debug_log("Creating Listener.")

        super(santiago.SantiagoListener, self).__init__(my_santiago, **kwargs)

        cherrypy.server.socket_port = int(socket_port)
        cherrypy.server.ssl_certificate = ssl_certificate
        cherrypy.server.ssl_private_key = ssl_private_key

        d = cherrypy.dispatch.RoutesDispatcher()
        d.connect("index", "/", self.index)

        cherrypy.tree.mount(cherrypy.Application(self), "",
                            {"/": {"request.dispatch": d}})

        santiago.debug_log("Listener Created.")

    @cherrypy.tools.ip_filter()
    def index(self, **kwargs):
        """Receive an incoming Santiago request from another Santiago client."""

        santiago.debug_log("Received request {0}".format(str(kwargs)))

        # FIXME Blammo!
        # make sure there's some verification of the incoming connection here.

        try:
            self.incoming_request(kwargs["request"])
        except Exception as e:
            logging.exception(e)

            raise cherrypy.HTTPRedirect("/freedombuddy")

class Sender(santiago.SantiagoSender):

    def __init__(self, my_santiago, proxy_host, proxy_port, **kwargs):

        super(santiago.SantiagoSender, self).__init__(my_santiago, **kwargs)
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port

    @cherrypy.tools.ip_filter()
    def outgoing_request(self, request, destination):
        """Send an HTTPS request to each Santiago client.

        Don't queue, just immediately send the reply to each location we know.

        It's both simple and as reliable as possible.

        ``request`` is literally the request's text.  It needs to be wrapped for
        transport across the protocol.

        """
        santiago.debug_log("request {0}".format(str(request)))
        to_send = { "request": request }

        params = urllib.urlencode(to_send)
        santiago.debug_log("params {0}".format(str(params)))

        # TODO: Does HTTPSConnection require the cert and key?
        # Is the fact that the server has it sufficient?  I think so.
        # FIXME Blammo!
        connection = httplib.HTTPSConnection(destination.split("//")[1])

        # proxying required and available only in Python 2.7 or later.
        # TODO: fail if Python version < 2.7.
        # FIXME Blammo!
        if sys.version_info >= (2, 7):
            connection.set_tunnel(self.proxy_host, self.proxy_port)

        # FIXME Blammo!  This must be a post.  Use httplib right.
        connection.request("GET", "/?%s" % params)
        connection.close()

class Monitor(santiago.SantiagoMonitor):

    def __init__(self, aSantiago, **kwargs):
        santiago.debug_log("Creating Monitor.")

        super(Monitor, self).__init__(aSantiago, **kwargs)

        try:
            d = cherrypy.tree.apps[""].config["/"]["request.dispatch"]
        except KeyError:
            d = cherrypy.dispatch.RoutesDispatcher()

        root = Root(self.santiago)

        routing_pairs = (
            ('/hosting/:client/:service', HostedService(self.santiago)),
            ('/hosting/:client', HostedClient(self.santiago)),
            ('/hosting', Hosting(self.santiago)),
            ('/consuming/:host/:service', ConsumedService(self.santiago)),
            ('/consuming/:host', ConsumedHost(self.santiago)),
            ('/consuming', Consuming(self.santiago)),
            ('/learn/:host/:service', Learn(self.santiago)),
            ("/stop", Stop(self.santiago)),
            ("/freedombuddy", root),
            )

        for location, handler in routing_pairs:
            Monitor.rest_connect(d, location, handler)

        cherrypy.tree.mount(root, "", {"/": {"request.dispatch": d}})

        santiago.debug_log("Monitor Created.")

    @classmethod
    def rest_connect(cls, dispatcher, location, controller, trailing_slash=True):
        """Simple REST connector for object/location mapping."""

        if trailing_slash:
            location = location.rstrip("/")
            location = [location, location + "/"]
        else:
            location = [location]

        for place in location:
            for a_method in ("PUT", "GET", "POST", "DELETE"):
                dispatcher.connect(controller.__class__.__name__ + a_method,
                                   place, controller=controller, action=a_method,
                                   conditions={ "method": [a_method] })

        return dispatcher

class RestMonitor(santiago.RestController):

    # FIXME filter input and escape output properly.
    # FIXME This input shows evidence of vulnerability: <SCRIPT SRC=http://ha.ckers.org/xss.js></SCRIPT>
    # FIXME build tests for this.
    # FIXME change page headers based on encoding.

    # http://ha.ckers.org/xss.html

    def __init__(self, aSantiago):
        super(RestMonitor, self).__init__()
        self.santiago = aSantiago
        self.relative_path = "protocols/https/templates"

    def _parse_query(self, query_input):
        """Split a URL into its query string.

        Might raise any of: ValueError, TypeError, NameError

        """
        query = ""

        if query_input:
            query_input = query_input[query_input.find("?")+1:]
            query = dict([item.split("=") for item in query_input.split("&")])

        return query

    def respond(self, template, values, encoding="html"):
        try:
            query = self._parse_query(cherrypy.request.query_string)
        except (ValueError, TypeError, NameError):
            return

        if query:
            try:
                encoding = query["encoding"]
            except KeyError:
                pass

        return [str(Template(
                    file="/".join((self.relative_path, encoding,
                                   self.santiago.locale, template)),
                    searchList = [dict(values)]))]

class Root(RestMonitor):
    @cherrypy.tools.ip_filter()
    def GET(self, **kwargs):
        return self.respond("root.tmpl", {})

class Stop(RestMonitor):
    @cherrypy.tools.ip_filter()
    def POST(self, **kwargs):
        self.santiago.live = 0
        raise cherrypy.HTTPRedirect("/")

    @cherrypy.tools.ip_filter()
    def GET(self, **kwargs):
        self.POST() # FIXME cause it's late and I'm tired.

class Learn(RestMonitor, santiago.SantiagoListener):
    @cherrypy.tools.ip_filter()
    def POST(self, host, service):
        super(Learn, self).learn(host, service)

        raise cherrypy.HTTPRedirect("/consuming/%s/%s" % (host, service))

class Hosting(RestMonitor):
    @cherrypy.tools.ip_filter()
    def GET(self, **kwargs):
        return self.respond("hosting.tmpl",
                            {"clients": [x for x in self.santiago.hosting]})

    @cherrypy.tools.ip_filter()
    def POST(self, put="", delete="", **kwargs):
        if put:
            self.PUT(put)
        elif delete:
            self.DELETE(delete)

        raise cherrypy.HTTPRedirect("/hosting")

    @cherrypy.tools.ip_filter()
    def PUT(self, client):
        self.santiago.create_hosting_client(client)

    @cherrypy.tools.ip_filter()
    def DELETE(self, client):
        if client in self.santiago.hosting:
            del self.santiago.hosting[client]

class HostedClient(RestMonitor):

    # FIXME correct direct key access
    @cherrypy.tools.ip_filter()
    def GET(self, client, **kwargs):
        return self.respond("hostedClient.tmpl",
                            { "client": client,
                              "services": self.santiago.hosting[client] if
                              client in self.santiago.hosting else [] })

    @cherrypy.tools.ip_filter()
    def POST(self, client="", put="", delete="", **kwargs):
        if put:
            self.PUT(client, put)
        elif delete:
            self.DELETE(client, delete)

        raise cherrypy.HTTPRedirect("/hosting/" + client)

    @cherrypy.tools.ip_filter()
    def PUT(self, client, service):
        self.santiago.create_hosting_service(client, service)

    @cherrypy.tools.ip_filter()
    def DELETE(self, client, service):
        if service in self.santiago.hosting[client]:
            del self.santiago.hosting[client][service]

class HostedService(RestMonitor):
    @cherrypy.tools.ip_filter()
    def GET(self, client, service, **kwargs):
        return self.respond("hostedService.tmpl", {
                "service": service,
                "client": client,
                "locations": self.santiago.get_host_locations(client, service)})

    @cherrypy.tools.ip_filter()
    def POST(self, client="", service="", put="", delete="", **kwargs):
        if put:
            self.PUT(client, service, put)
        elif delete:
            self.DELETE(client, service, delete)

        raise cherrypy.HTTPRedirect("/hosting/{0}/{1}/".format(client, service))

    @cherrypy.tools.ip_filter()
    def PUT(self, client, service, location):
        self.santiago.create_hosting_location(client, service, [location])

    # Have to remove instead of delete for locations as $service is a list
    @cherrypy.tools.ip_filter()
    # FIXME correct direct key access
    def DELETE(self, client, service, location):
        if location in self.santiago.hosting[client][service]:
            self.santiago.hosting[client][service].remove(location)

class Consuming(RestMonitor):
    @cherrypy.tools.ip_filter()
    def GET(self, **kwargs):
        return self.respond("consuming.tmpl",
                            { "hosts": [x for x in self.santiago.consuming]})

    @cherrypy.tools.ip_filter()
    def POST(self, put="", delete="", **kwargs):
        if put:
            self.PUT(put)
        elif delete:
            self.DELETE(delete)

        raise cherrypy.HTTPRedirect("/consuming")

    @cherrypy.tools.ip_filter()
    def PUT(self, host):
        self.santiago.create_consuming_host(host)

    @cherrypy.tools.ip_filter()
    def DELETE(self, host):
        if host in self.santiago.consuming:
            del self.santiago.consuming[host]

class ConsumedHost(RestMonitor):
    @cherrypy.tools.ip_filter()
    def GET(self, host, **kwargs):
        return self.respond(
            "consumedHost.tmpl",
            { "services": self.santiago.consuming[host] if host in
                  self.santiago.consuming else [],
              "host": host })

    @cherrypy.tools.ip_filter()
    def POST(self, host="", put="", delete="", **kwargs):
        if put:
            self.PUT(host, put)
        elif delete:
            self.DELETE(host, delete)

        raise cherrypy.HTTPRedirect("/consuming/" + host)

    @cherrypy.tools.ip_filter()
    def PUT(self, host, service):
        self.santiago.create_consuming_service(host, service)

    @cherrypy.tools.ip_filter()
    def DELETE(self, host, service):
        if service in self.santiago.consuming[host]:
            del self.santiago.consuming[host][service]

class ConsumedService(RestMonitor):
    @cherrypy.tools.ip_filter()
    def GET(self, host, service, **kwargs):
        return self.respond("consumedService.tmpl",
                            { "service": service,
                              "host": host,
                              "locations":
                                  self.santiago.get_client_locations(host,
                                                                     service)})

    @cherrypy.tools.ip_filter()
    def POST(self, host="", service="", put="", delete="", **kwargs):
        if put:
            self.PUT(host, service, put)
        elif delete:
            self.DELETE(host, service, delete)

        raise cherrypy.HTTPRedirect("/consuming/{0}/{1}/".format(host, service))

    @cherrypy.tools.ip_filter()
    def PUT(self, host, service, location):
        self.santiago.create_consuming_location(host, service, [location])

    # Have to remove instead of delete for locations as $service is a list
    @cherrypy.tools.ip_filter()
    def DELETE(self, host, service, location):
        if location in self.santiago.consuming[host][service]:
            self.santiago.consuming[host][service].remove(location)

def query(conn, type="", id="", service="",
          action="GET", url="", params=None, body=None):
    """A helper method to request tests for the HTTPS controller.

    :conn: a httplib.HTTPSConnection.

    :type: the type of request (consuming, learning, hosting, stop, /).

    :id: the gpg key we're querying about

    :service: the service to request data for

    :action: GET, POST, PUT, DELETE (required when posting)

    :url: the url to query (required for weird controllers).  Defaults to
    ``/%(type)s/%(id)s/%(service)s?%(params)s``

    :params: the request parameters.  defaults to {}

    :body: the request's body.  ignored unless posting.

    """
    if params is None:
        params = {}
    params = urllib.urlencode(params)

    if action not in ("GET", "POST", "PUT", "DELETE"):
        return

    if action == "POST":
        if not body:
            body = urllib.urlencode({"host": id, "service": service})
        else:
            body = urllib.urlencode(body)

    if url:
        location = url % locals()
    else:
        location = "/{0}/{1}/{2}?{3}".format(type, id, service, params)

    conn.request(action, location, body)

    response = conn.getresponse()
    data = response.read()

    return data
