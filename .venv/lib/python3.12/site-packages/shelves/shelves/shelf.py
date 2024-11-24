#!/usr/bin/env python
"""
This module provides everything needed for shelves to work and expose all
the needed method as well as some agnostic storage Shelves (such as shelf
of shelves)

A shelve is made of at least a searchable index, and a readable store (indexed
by the index).
"""

class Shelf(dict):
    """
    This is an interface to be implemented by specific Shelf by subclassing it.
    it provides standard method that musst be present on any of the Shelves.

    boxes is a list of Box which can hold Documents.
    readonly is used to check if you can write/upload/remove/alter content
    index is an index used to find documents related to a search
    """
    boxes = []
    readonly = False
    index = None

    def __init__(self, *args, **kwargs):
        """
        Do all the necessary initialisation here.
        Mandatory are a Box system and an Index one.
        """
        pass

    def add(self, document, metadata):
        """
        Add a document and it's metadata into a Shelf
        """
        if self.readonly:
            raise IOError("Shelf is readonly")
        raise NotImplementedError

    def delete(self, name):
        """
        Delete a document and it's metadata from a Shelf.
        we use a name to find it, it must be more a serial number
        than a real name.
        """
        if self.readonly:
            raise IOError("Shelf is readonly")
        raise NotImplementedError

    def modify(self, name, metadata):
        """
        Modify a document by its name. Metadata are merged with the previous one.
        The doc isn't changed.
        """
        if self.readonly:
            raise IOError("Shelf is readonly")
        raise NotImplementedError

    def search(self, query):
        """
        Search through the metadata index of a Shelf and return
        metadata including document id
        """
        raise NotImplementedError

    def get(self, name):
        """
        Get the document named name from one of the boxes
        """
        raise NotImplementedError

    def schema(self):
        """
        Get the schema used to sort the items
        """

class ShelfOfShelves(Shelf):
    """
    This Shelf is made of shelves. We will thread and assemble all queries. The shelf of shelves
    is readonly.

    library is the list of shelves.
    """
    readonly = True
    library = []

    def __init__(self, shelves_list=[]):
        """
        Let's initialize our library.

        shelves_list is a list of already created shelves that we wanna add
        """
        for shelf in shelves_list:
            self.__add_shelf(self, shelf)

    def __add_shelf(self, shelf):
        """
        Let's add a new shelf to our library.

        shelf must be a Shelf object
        """
        # We will check that the shelf does not exist already in our library
        if shelf not in self.shelves:
            # We must be sure that our shelf is indeed a Shelf
            if not isinstance(shelf, Shelf):
                raise TypeError("%s not a subclass of Shelf" % (type(shelf),))
            library.append(shelf)

            # We will add all the boxes in the same shelf, for ease of access
            for box in shelf.boxes:
                self.boxes.append(box)

    def get(self, name):
        """
        Let's search for a specific document and returns it

        name is the name of the document we're looking for
        """
        for box in self.boxes:
            if name in box.keys():
                return box[name]
        return None

    def search(self, query):
        """
        Let's search through all the shelves and extend the results to include all of them before
        returning it.

        query is a dict of keys/values to search for.
        """
        # SO, let's create our results
        results = None
        for shelf in self.library:
            # First shelf we're running the search on
            if results is None:
                results = shelf.search(query)
            # We use upgrade_and_extend, because multiple hits can happen.
            else:
                results.upgrade_and_extend(shelf.search(query))

        return results

    def schema(self):
        """
        Let's get the schema of all the shelves we have
        """
        schemas = {}
        for shelf in library:
            schemas.update(shelf.schema())

        return schemas
