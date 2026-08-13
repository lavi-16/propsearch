"""
Gold-layer schema definitions -- deliberately empty. The schema lives in
sql/schema/gold/*.sql, not here.

This file's original note said it would be filled in once the schema had
been grounded against real WFS field names rather than guesses. That
precondition has been met: bronze landed all five spec layers, silver and
gold are both built from confirmed field names, and `make gold` is the
build.

It stays empty because the project models the schema as DDL rather than as
ORM classes. That is not an omission -- the constraints are the deliverable
(PK, FK, CHECK, and the biconditionals that keep "measured absence"
distinct from NULL), and none of them survive a translation into
SQLAlchemy models. A second definition here would be a copy that drifts.

Read sql/schema/gold/00_schema.sql for the layer's contract.
"""
