#!/usr/bin/env python3

import wsgiref.simple_server as server
import sys

import registry

port = 8080
VERSION = "0.0"

httpd = server.make_server("", port, registry.dispatch)
server.ServerHandler.server_software = "RPP-Afnic/%s CPython/%s" % (VERSION, sys.version.split()[0])
print("Serving HTTP on port %i..." % port)
# Respond to requests until process is killed
httpd.serve_forever()

