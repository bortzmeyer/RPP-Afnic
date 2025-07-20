DROP TABLE Transfers;
DROP TABLE Domains;
DROP TABLE Contacts;
DROP TABLE Registrars;

CREATE TABLE Contacts (handle SERIAL UNIQUE NOT NULL, name TEXT NOT NULL,
                       created TIMESTAMP NOT NULL DEFAULT current_timestamp);

CREATE TABLE Registrars (name TEXT UNIQUE NOT NULL, handle SERIAL UNIQUE NOT NULL,
                      password TEXT NOT NULL, -- TODO do not store in clear
                      created TIMESTAMP NOT NULL DEFAULT current_timestamp);

CREATE TABLE Domains (name TEXT UNIQUE NOT NULL,
                      holder INTEGER NOT NULL REFERENCES Contacts(handle),
		      tech INTEGER NOT NULL REFERENCES Contacts(handle),
		      admin INTEGER NOT NULL REFERENCES Contacts(handle),
		      registrar INTEGER NOT NULL REFERENCES Registrars(handle),
                      created TIMESTAMP NOT NULL DEFAULT current_timestamp);

CREATE TABLE Transfers(id SERIAL UNIQUE NOT NULL,
                       domain TEXT NOT NULL REFERENCES Domains(name),
		       winner INTEGER NOT NULL REFERENCES Registrars(handle),
		       completed BOOLEAN DEFAULT false,
                       created TIMESTAMP NOT NULL DEFAULT current_timestamp);
		       
INSERT INTO Contacts (name) VALUES ('NIC');
INSERT INTO Contacts (name) VALUES ('Jean Durand');

INSERT INTO Registrars (name, password) VALUES ('NIC', '1234');
INSERT INTO Registrars (name, password) VALUES ('Foo Bar', 'qwerty');
INSERT INTO Registrars (name, password) VALUES ('Bazinga', 'bazinga');

INSERT INTO Domains (name, holder, tech, admin, registrar)
    VALUES ('nic.example', (SELECT handle FROM Contacts WHERE name = 'NIC'),
    (SELECT handle FROM Contacts WHERE name = 'NIC'),
    (SELECT handle FROM Contacts WHERE name = 'NIC'),
    (SELECT handle FROM Registrars WHERE name = 'NIC'));
INSERT INTO Domains (name, holder, tech, admin, registrar)
    VALUES ('foobar.example', (SELECT handle FROM Contacts WHERE name = 'Jean Durand'),
    (SELECT handle FROM Contacts WHERE name = 'Jean Durand'),
    (SELECT handle FROM Contacts WHERE name = 'Jean Durand'),
    (SELECT handle FROM Registrars WHERE name = 'Foo Bar'));
