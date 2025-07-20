#!/usr/bin/python3

import os
import json
import datetime
import base64
import random
import logging
import time

# https://pypi.org/project/psycopg2/
import psycopg2

# https://python-jsonschema.readthedocs.io https://pypi.org/project/jsonschema/
# See also https://json-schema.org/
import jsonschema

TLD = "example"
MAX_DOMAINS = 5000
MAX_CONTACTS = 5000
LOGFILENAME = "rpp.log"

class AlreadyExists(Exception):
    pass
class DoesNotExist(Exception):
    pass
class Immutable(Exception):
    pass
class TooManyDomains(Exception):
    pass
class TooManyContacts(Exception):
    pass
class Conflict(Exception):
    pass
class NoValidationForThisMethod(Exception):
    def __init__(self, method):
        self.method = method
    
def serialize_others(obj): 
    if isinstance(obj, datetime.datetime): 
        return obj.isoformat() 
    raise TypeError("Type not serializable")

def send(start_response, status, output):
    """output must be a dictionary, status also, with members 'code'
    and 'message'"""
    output["status_code"] = status["code"]
    output["status_message"] = status["message"]
    joutput = json.dumps(output, default=serialize_others) + "\r\n"
    response_headers = [("Content-Type", "application/rpp+json"),
                        ("Content-Length", str(len(joutput)))]
    svtrid = "(None)"
    if "svtrid" in status:
        response_headers.append(("RPP-Svtrid", str(status["svtrid"])))
        svtrid = status["svtrid"]
    # TODO log the client name
    logger.info("Completing transaction %s" % (svtrid))
    if "cltrid" in status:
        response_headers.append(("RPP-Cltrid", status["cltrid"]))
    sstatus = "%s %s" % (status["code"], status["message"])
    start_response(sstatus, response_headers)
    return [joutput.encode()]
    # We should return errors in JSON as in RFC 9457

def head_domain(domain):
    cursor.execute("SELECT name FROM domains WHERE name= (%(domain)s)",
                   {"domain": domain})
    data = cursor.fetchone()
    if data is None:
        return None
    else:
        return {"name": data[0]}

def head_contact(contact):
    # TODO allow search by name
    cursor.execute("SELECT name FROM Contacts WHERE handle = (%(contact)s)",
                   {"contact": contact})
    data = cursor.fetchone()
    if data is None:
        return None
    else:
        return {"name": data[0]}

def info_domain(domain):
    cursor.execute("SELECT name,holder,tech,admin,registrar,created FROM domains WHERE name= (%(domain)s)",
                   {"domain": domain})
    data = cursor.fetchone()
    if data is None:
        return None
    else:
        return {"name": data[0], "holder": data[1], "tech": data[2], "admin": data[3], "registrar": int(data[4]),
                "created": data[5]} 

def info_contact(contact):
    cursor.execute("SELECT name,created FROM Contacts WHERE handle = (%(contact)s)",
                   {"contact": contact})
    data = cursor.fetchone()
    if data is None:
        return None
    else:
        return {"name": data[0], "created": data[1]} 

def list_domains():
    cursor.execute("SELECT name FROM domains")
    result = []
    for data in cursor.fetchall():
        result.append(data[0])
    return {"list": result}

def patch_domain(domain, data):
    output = info_domain(domain)
    if output is None:
       return ({"code": 404,  "message": "Not found"},
               {"result": "Domain %s NOT found" % domain})
    data = data["change"]
    if "tech" in data:
        cursor.execute("UPDATE Domains SET tech = %(tech)s WHERE name = %(domain)s",
                       {"domain": domain, "tech": data["tech"]})
        if cursor.rowcount != 1:
            connection.rollback()
            return {"code": 500, "message": "Internal error"}, {"result": "Update of tech contact failed"}                
    if "admin" in data:
        cursor.execute("UPDATE Domains SET admin = %(admin)s WHERE name = %(domain)s",
                       {"domain": domain, "admin": data["admin"]})
        if cursor.rowcount != 1:
            connection.rollback()
            return {"code": 500, "message": "Internal error"}, {"result": "Update of admin contact failed"}                
    connection.commit()
    return {"code": 204, "message": "Updated"}, {"result": "Update done"}                
    
def store_domain(domain, holder, tech, admin, registrar):
    cursor.execute("SELECT count(name) FROM domains")
    num = int(cursor.fetchone()[0])
    if num >= MAX_DOMAINS:
        raise TooManyDomains
    try:
        cursor.execute("INSERT INTO domains (name, holder, tech, admin, registrar) VALUES (%(domain)s, %(holder)s, %(tech)s, %(admin)s, %(registrar)s)",
                       {"domain": domain, "holder": holder, "tech": tech, "admin": admin,
                        "registrar": registrar})
        connection.commit()
    except psycopg2.errors.UniqueViolation:
        connection.rollback()
        raise AlreadyExists
    except psycopg2.errors.SerializationFailure:
        connection.rollback()
        raise Conflict
    
def store_contact(name):
    cursor.execute("SELECT count(name) FROM contacts")
    num = int(cursor.fetchone()[0])
    if num >= MAX_CONTACTS:
        raise TooManyContacts
    try:
        cursor.execute("INSERT INTO contacts (name) VALUES (%(name)s)",
                   {"name": name})
        connection.commit()
    except psycopg2.errors.SerializationFailure:
        connection.rollback()
        raise Conflict
    
def delete_domain(domain):
    if domain == "nic.%s" % TLD:
        raise Immutable
    cursor.execute("DELETE FROM domains WHERE name=(%(domain)s)",
                   {"domain": domain})
    if cursor.rowcount == 0:
        connection.rollback()
        raise DoesNotExist
    connection.commit()

def delete_contact(contact):
    if contact == 1:
        raise Immutable
    cursor.execute("DELETE FROM Contacts WHERE handle=(%(contact)s)",
                   {"contact": contact})
    if cursor.rowcount == 0:
        connection.rollback()
        raise DoesNotExist
    connection.commit()

def auth_registrar(user, password):
     cursor.execute("SELECT password FROM Registrars WHERE handle = (%(handle)s)",
                   {"handle": user})
     data = cursor.fetchone()
     if data is not None and data[0] == password:
         return True
     return False

# Business rules
def registerable(domain):
    """ Call this method ONLY on domains that are not aready registered! """
    (flabel, rest) = domain.split(".", maxsplit=1)
    if len(flabel) < 2:
        return (False, "Domains must be at least two characters")
    elif flabel[0] == "0":
        return (False, "Domains must not start with a zero")
    else:
        return (True, )

def validate_json(input, klass="domain", method="put"):
    data = {}
    ojson = json.loads(input)
    if klass == "domain":
        if method == "put":
            jsonschema.validate(instance=ojson, schema=domain_schema)
        elif method == "patch":
            jsonschema.validate(instance=ojson, schema=patch_domain_schema)
        else:
            raise NoValidationForThisMethod(method)
    elif klass == "contact":
        if method == "put":
            jsonschema.validate(instance=ojson, schema=entity_schema)
        else:
            raise NoValidationForThisMethod(method)
    else:                
        raise NoValidationForThisClass(klass)
    return ojson

def availability_domain(domain, method, extra, client, password):
    data = head_domain(domain)
    if method == "HEAD":
        if data is None:
            return ({"code": 404,  "message": "Not found"},
                    {"result": "Domain %s NOT found" % domain})
        else:
            return ({"code": 200,  "message": "Found"},
               {"result": "Domain %s already exists" % domain})
    elif method == "GET":
        if data is None:
            regable = registerable(domain)
            if regable[0]:
                info = "It can be registered"
            else:
                info = "It cannot be registered because %s" % regable[1]
            return ({"code": 404,  "message": "Not found"},
                        {"result": "Domain %s NOT found. %s" % (domain, info)})
        else:
            return ({"code": 200,  "message": "Found"},
               {"result": "Domain %s already exists" % domain})
    else:
        return {"code": 405, "message": "Method %s not supported" % method}, {}

def transfer_domain(domain, method, extra, client, password):
    authenticated = auth_registrar(client, password)
    if not authenticated:
        status = {"code": 401,  "message": "Wrong password"}
        output = {"result": "You must authenticate properly"}
        return status,output
    output = info_domain(domain)
    if output is None:
       return ({"code": 404,  "message": "Not found"},
               {"result": "Domain %s NOT found" % domain})
    if method == "GET":
        cursor.execute("SELECT id, created, winner FROM Transfers WHERE NOT completed and domain= (%(domain)s)",
                   {"domain": domain})
        data = cursor.fetchone()
        if data is None:
            return {"code": 200, "message": "OK"}, {"result": "No pending transfer for %s" % (domain)}
        else:
            return {"code": 200, "message": "OK"}, {"result": "Domain %s has a transfer to registrar %s pending (since %s)" % (domain, data[2], data[1])}
    elif method == "POST":
        if extra is None:
            data = info_domain(domain)
            if data["registrar"] == client:
                return ({"code": 200, "message": "OK"},
                        {"result": "%s is already the registrar of %s" % (client, domain)})   
            cursor.execute("SELECT id, created, winner FROM Transfers WHERE NOT completed and domain= (%(domain)s)",
                   {"domain": domain})
            data = cursor.fetchone()
            if data is not None:
                return {"code": 200, "message": "OK"}, {"result": "Domain %s already has a transfer to registrar %s pending (since %s)" % (domain, data[2], data[1])}
            cursor.execute("INSERT INTO Transfers (domain, winner, completed) VALUES ((%(domain)s), (%(to)s), false)", {"domain": domain, "to": client})
            connection.commit()
            return ({"code": 200, "message": "OK"},
                    {"result": "Domain %s transfer to registrar %s started" % (domain, client)})
        else:
            cursor.execute("SELECT winner FROM Transfers WHERE NOT completed and domain = (%(domain)s)",
                   {"domain": domain})
            data = cursor.fetchone()
            if data is None:
                return {"code": 404, "message": "No transfer"}, {"result": "No pending transfer of %s to act on" % (domain)}
            else:
                winner = data[0]
            if extra == "cancelation":
                if winner != client:
                    return {"code": 403, "message": "Not yours"}, {"result": "This is not your transfer"}                    
                cursor.execute("DELETE FROM Transfers WHERE NOT completed and domain= (%(domain)s)",
                   {"domain": domain})
                connection.commit()
                return {"code": 200, "message": "OK"}, {"result": "Transfer of %s cancelled" % (domain)}
            elif extra == "approval":
                data = info_domain(domain)
                if data["registrar"] != client:
                    return {"code": 403, "message": "Not yours"}, {"result": "This is not your domain currently"}
                cursor.execute("UPDATE Transfers SET completed=true WHERE NOT completed AND domain = (%(domain)s)",
                   {"domain": domain})
                if cursor.rowcount != 1:
                    return {"code": 500, "message": "Internal error"}, {"result": "Update of transfer failed"}                
                cursor.execute("UPDATE Domains SET registrar=%(winner)s WHERE name = (%(domain)s)",
                   {"winner": winner, "domain": domain})
                if cursor.rowcount != 1:
                    return {"code": 500, "message": "Internal error"}, {"result": "Update of %s faled" % (domain)}
                connection.commit()
                return {"code": 200, "message": "OK"}, {"result": "Transfer of %s approved" % (domain)}                
            elif extra == "rejection":
                data = info_domain(domain)
                if data["registrar"] != client:
                    return {"code": 403, "message": "Not yours"}, {"result": "This is not your domain currently"}
                cursor.execute("DELETE FROM Transfers WHERE NOT completed and domain= (%(domain)s)",
                   {"domain": domain})
                connection.commit()
                return {"code": 200, "message": "OK"}, {"result": "Transfer of %s rejected" % (domain)}
            else:
                return {"code": 400, "message": "Unknown transfer extra command"}, {"result": "Unnown transfer extra command %s" % extra}
    else:
        return {"code": 405, "message": "Method %s not supported" % method}, output
    
def handle_domain(domain, method, operation=None, extra=None, length=0, body=None,
                  user=None, password=None):
    domain = domain.lower()
    status = {"code": 200, "message": "OK"}
    output = {}
    if not domain.endswith(".%s" % TLD):
        status = {"code": 400, "message": "Domain name must be under .%s" % TLD}
        return status, output
    # The specific operations:
    if operation == "transfer":
        result = transfer_domain(domain, method, extra, user, password)
        return result[0], result[1]
    elif operation == "availability":
        result = availability_domain(domain, method, extra, user, password)
        return result[0], result[1]
    elif operation is not None:
        return {"code": 400, "message": "Unknown operation"}, {"result": "Unknown operation %s for domain %s" % (operation, domain)}
    # The general case (nothing was after the domain name):
    if method == "HEAD":
        output = head_domain(domain)
        # Output will be typically ignored by the client when using
        # HEAD (curl --head will not display it). RFC 9110, section
        # 6.4.1.
        if output is None:
            status = {"code": 404,  "message": "Not found"}
            output = {}
        else:
            output = {}
    elif method == "GET":
        output = info_domain(domain)
        if output is None:
            status = {"code": 404,  "message": "Not found"}
            output = {"result": "Domain %s NOT found" % domain}
        else:
            output = {"result": "Domain %s exists" % domain,
                      "holder": output["holder"],
                      "tech_contact": output["tech"],
                      "admin_contact": output["admin"],
                      "registrar": output["registrar"],
                      "created": output["created"]} 
    elif method == "PUT":    
        if user is None:
            status = {"code": 401,  "message": "Unauthenticated"}
            output = {"result": "You must authenticate to create a domain"}
            return status,output
        authenticated = auth_registrar(user, password)
        if not authenticated:
            status = {"code": 401,  "message": "Wrong password"}
            output = {"result": "You must authenticate properly"}
            return status,output
        # Add nameservers?
        if body is None:
             status = {"code": 400,  "message": "Empty"}
             output = {"result": "No JSON body to create %s" % domain}
             return status, output
        jinput = body.read(length)
        try:
            data = validate_json(jinput)
            try:
                store_domain(domain, data["holder"], data["tech"], data["admin"], user)
                status = {"code": 201,  "message": "Created"}
                output = {"result": "%s created" % domain} 
            except AlreadyExists:
                status = {"code": 412,  "message": "Exists"}
                output = {"result": "%s already exists" % domain}
            except TooManyDomains:
                status = {"code": 400,  "message": "Too many"}
                output = {"result": "Too many domains already"}
            except Conflict:
                status = {"code": 500,  "message": "Conflict"}
                output = {"result": "Internal conflict"}
        except jsonschema.exceptions.ValidationError as e:
            status = {"code": 400,  "message": "Invalid JSON"}
            output = {"result": "Invalid JSON body (%s) for %s" % (e, domain)}
        except json.decoder.JSONDecodeError:
            status = {"code": 400,  "message": "Invalid"}
            output = {"result": "Invalid JSON body for %s" % domain}
    elif method == "PATCH":
        if user is None:
            status = {"code": 401,  "message": "Unauthenticated"}
            output = {"result": "You must authenticate as the registrar of %s" % domain}
            return status,output
        authenticated = auth_registrar(user, password)
        if not authenticated:
            status = {"code": 401,  "message": "Wrong password"}
            output = {"result": "You must authenticate properly"}
            return status,output
        # TODO check this is the proper registrar
        if body is None:
             status = {"code": 400,  "message": "Empty"}
             output = {"result": "No JSON body to patch %s" % domain}
             return status, output
        jinput = body.read(length)
        try:
            data = validate_json(jinput, "domain", "patch")
            try:
                (status, output) = patch_domain(domain, data)
            except Conflict:
                status = {"code": 500,  "message": "Conflict"}
                output = {"result": "Internal conflict"}
        except jsonschema.exceptions.ValidationError as e:
            status = {"code": 400,  "message": "Invalid JSON"}
            output = {"result": "Invalid JSON body (%s) for %s" % (e, domain)}
        except json.decoder.JSONDecodeError:
            status = {"code": 400,  "message": "Invalid"}
            output = {"result": "Invalid JSON body for %s" % domain}
        return status,output
    elif method == "DELETE":
        if user is None:
            status = {"code": 401,  "message": "Unauthenticated"}
            output = {"result": "You must authenticate as the registrar of %s" % domain}
            return status,output
        info = info_domain(domain)
        if info is None:
            status = {"code": 404,  "message": "Not found"}
            output = {"result": "%s does not exist" % domain} 
            return status, output
        if user != info["registrar"]:
            status = {"code": 403,  "message": "Forbidden"}
            output = {"result": "You (%i) are not the registrar of %s (%i)" % (user, domain, info["registrar"])} 
            return status, output
        authenticated = auth_registrar(user, password)
        if not authenticated:
            status = {"code": 401,  "message": "Wrong password"}
            output = {"result": "You must authenticate as the registrar of %s" % domain}
            return status,output
        try:
            delete_domain(domain)
            status = {"code": 202,  "message": "Accepted"}
            output = {"result": "%s deleted" % domain} 
        except DoesNotExist:
            status = {"code": 404,  "message": "Not found"}
            output = {"result": "%s does not exist" % domain} 
        except Immutable:
            status = {"code": 423,  "message": "Immutable"}
            output = {"result": "%s cannot be deleted" % domain} 
    else: 
        return {"code": 405, "message": "Method %s not supported" % method}, output
    return status, output

def handle_contact(contact, method, length=None, body=None):
    status = {"code": 200, "message": "OK", }
    output = {}
    if method == "HEAD":
        output = head_contact(contact)
        if output is None:
            status = {"code": 404,  "message": "Not found"}
            output = {"result": "Contact %s NOT found" % contact}
        else:
            output = {"result": "Contact %s exists" % contact}
    elif method == "GET":
        output = info_contact(contact)
        if output is None:
            status = {"code": 404,  "message": "Not found"}
            output = {"result": "Contact %s NOT found" % contact}
        else:
            output = {"result": "Contact %s exists" % contact,
                      "name": output["name"], "created": output["created"]}
    elif method == "PUT":    
        if body is None:
             status = {"code": 400,  "message": "Empty"}
             output = {"result": "No JSON body to create contact"}
             return status, output
        jinput = body.read(length)
        try:
            data = validate_json(jinput, "contact")
            try:
                root = data["name"]["components"]
                given = ""
                surname = None
                for component in root:
                    if component["kind"] == "given":
                        given = component["value"]
                    if component["kind"] == "surname":
                        surname = component["value"]
                if not surname:
                    raise Exception("No surname???")
                fullname = given + " " + surname
                handle = store_contact(fullname)
                status = {"code": 201,  "message": "Created"}
                output = {"result": "%s (%s) created" % (handle, data["name"])} 
            except TooManyContacts:
                status = {"code": 400,  "message": "Too many"}
                output = {"result": "Too many contacts already"}
            except Conflict:
                status = {"code": 500,  "message": "Conflict"}
                output = {"result": "Internal conflict"}
        except json.decoder.JSONDecodeError:
            status = {"code": 400,  "message": "Invalid"}
            output = {"result": "Invalid JSON body"}
    elif method == "DELETE":    
        try:
            delete_contact(contact)
            status = {"code": 202,  "message": "Accepted"}
            output = {"result": "%s deleted" % contact} 
        except DoesNotExist:
            status = {"code": 404,  "message": "Not found"}
            output = {"result": "%s does not exist" % contact} 
        except Immutable:
            status = {"code": 423,  "message": "Immutable"}
            output = {"result": "%s cannot be deleted" % contact} 
    else: 
        return {"code": 405, "message": "Method %s not supported" % method}, output
    return status, output

def dispatch(environ, start_response):
    method = environ["REQUEST_METHOD"]
    path = environ["PATH_INFO"]
    client_transaction_id = None
    if "HTTP_RPP_CLTRID" in environ:
        client_transaction_id = environ["HTTP_RPP_CLTRID"]
    server_transaction_id = random.randint(0, 999999)
    # TODO check that the client accepts JSON
    # TODO create status with the control id for all commands
    do_list_domains = False
    # TODO Test the type of the body is application/rpp+json?
    # TODO return RPP-code
    if not path.startswith("/domains/") and  not path.startswith("/entities/") and not path.startswith("/list-domains"):
        status = {"code": 400, "message": "Path must start with /domains, /entities or be /list-domains"}
        return send(start_response, status, {})
    try:
        body_size = int(environ.get("CONTENT_LENGTH", 0))
    except ValueError:
        body_size = 0
    user = None
    password = None
    if "HTTP_AUTHORIZATION" in environ:
        header = environ.get("HTTP_AUTHORIZATION")
        if header and header.startswith('Basic'):
            allauth = base64.b64decode(header[6:].encode()).decode()
            auth = allauth.split(':')
            if len(auth) == 2:
                user, password = auth
                user = int(user)
    if path == "/list-domains":
        do_list_domains = True
    elif path.startswith("/domains/"):
        domain = path.removeprefix("/domains/")
        if domain == "":
            raise Exception("Empty domain") # TODO return better error
        operation = None
        extra = None
        if "/" in domain:
            array = domain.split("/")
            if len(array) > 3:
                return send(start_response,
                            status = {"code": 400,
                                      "message": "Invalid path syntax"},
                            output = {"result": "Invalid path syntax for %s" % \
                                      (domain)});
            if len(array) > 2:
                extra = array[2]
            if len(array) > 1:
                operation = array[1]
            domain = array[0]
        result = handle_domain(domain, method, operation, extra,
                               body_size, environ["wsgi.input"],
                               user, password)
        status = result[0]
        if client_transaction_id is not None:
            status["cltrid"] = client_transaction_id
        status["svtrid"] = server_transaction_id
        return send(start_response, status, result[1]);
    elif path.startswith("/entities/"):
        contact = path.removeprefix("/entities/")
        result = handle_contact(contact, method, body_size, environ["wsgi.input"])
        status = result[0]
        if client_transaction_id is not None:
            status["cltrid"] = client_transaction_id
        status["svtrid"] = server_transaction_id
        return send(start_response, status, result[1]);
    else:
        status = {"code": 500,  "message": "Internal error, should not happen"}
        return send(start_response, status, {})
    if do_list_domains:
        if method == "GET":
            output = list_domains()
            return send(start_response,
                        {"code": 200, "message": "OK"}, output)
        else:
            return send(start_response,
                        {"code": 405, "message": "Method %s not supported for /list-domains" % method}, {})

# Logging
logger = logging.getLogger("RPP")
logger.setLevel(logging.DEBUG)
loggingstr = "/home/stephane/tmp/" + LOGFILENAME
fh = logging.FileHandler(loggingstr)
ft = logging.Formatter(fmt = 'RPP - %(levelname)s - %(asctime)s - %(message)s',
                       datefmt = '%Y-%m-%d %H:%M:%SZ')
ft.converter = time.gmtime
fh.setFormatter(ft)
logger.addHandler(fh)

# Database
connection = psycopg2.connect("dbname=registry")
connection.set_session(autocommit=False,
                       isolation_level=psycopg2.extensions.ISOLATION_LEVEL_READ_COMMITTED)
cursor = connection.cursor()
logger.info("Server starts")

# JSONschema
INPUT = open("domain-schema.json")
domain_schema = json.load(INPUT)
INPUT = open("patch-domain-schema.json")
patch_domain_schema = json.load(INPUT)
INPUT = open("entity-schema.json")
entity_schema = json.load(INPUT)




