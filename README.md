A very limited and very experimental RPP server

# Code testing

Started at the IETF Hackathon (IETF 123 in Madrid)

## Creating the database

Requires a running PostgreSQL

```
psql -f ./create.sql registry
```

## Running the server

TODO: require some Python modules

``` 
./test-server.py
```

### Testing it:

``` 
curl --header @headers.txt http://localhost:8080/domains/nic.example
curl --header @headers.txt --request PUT --user 2:qwerty --data '{"holder": 2}'  http://localhost:8080/domains/durand.example

curl --header @headers.txt http://localhost:8080/entities/2
curl --header @headers.txt --request PUT --data '{"@type": "Card", "name": {"components": [{"kind": "given","value": "Jean"},{"kind": "surname","value": "Bon"}]}}'  http://localhost:8080/entities/

curl --header @headers.txt --head http://localhost:8080/domains/toto.example
``` 

Availability:
``` 
curl --header @headers.txt http://localhost:8080/domains/something.example
``` 

Patch :
``` 
curl -i --header @headers.txt --request PATCH --user 2:qwerty --data '{"change": {"admin": 1}}'  http://localhost:8080/domains/durand.example
``` 

Transfer:
``` 
curl --header @headers.txt  --request POST --user 3:bazinga http://localhost:8080/domains/durand.example/transfer
curl --header @headers.txt  --request POST --user 2:qwerty http://localhost:8080/domains/durand.example/transfer/approval
``` 
