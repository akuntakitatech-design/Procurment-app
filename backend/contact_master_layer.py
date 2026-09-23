"""Register reusable internal employee/contact master data.

The generic master routes from master_auto remain the single CRUD implementation;
this layer only adds the contacts collection and automatic KON-xxxxx numbering.
"""

import master_auto


def install(server):
    master_auto.MASTER_PREFIX["contacts"] = "KON"
    server.MASTER_COLLECTIONS["contacts"] = server.db.contacts
