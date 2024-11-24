#!/usr/bin/env python

from whoosh.fields import SchemaClass, ID, TEXT, KEYWORD

"""
This module will provides different Schema to be used for Shelves
"""

class BasicSchema(SchemaClass):
    """
    A really basic schema, with only file ID, an associated TEXT and keywords
    """
    hash = ID(unique=True, stored=True) # Name must be unique in a shelves
    description = TEXT(spelling=True, stored=True) # A description of the document being stored
    keywords = KEYWORD(lowercase=True, scorable=True, stored=True) # And associated keywords
