#!/usr/bin/env python

"""
This module provide anything needed to create and subclass Box instancs, which
are used to store raw documents (without their metadata.
"""
class Box(dict):
    """
    This is an interface to be subclassed by specific Box. It provides standard 
    method that must be present on any of its subclasses and works as a dict.

    It can be used to specialise box. Either using local filesystem, ftp, 
    distributed ones or databases one.

    Subclass of Box must implements _put, _get, _list and _del methods
    """
    def __init__(self, *args, **kwargs):
        """
        Do whatever is needed to have the box Working, like connecting to 
        databases, getting needed parameters, etc
        """
        self.update(*args, **kwargs)

    def __repr__(self, *args, **kwargs):
        """
        Let's display our Box content
        """
        result ='{'
        for (k, v) in self.items(*args, **kwargs):
            result += repr(k) + ": " + repr(v) + ","

        result = result[:-1] + '}'
        return result

    def __len__(self, *args, **kwargs):
        """
        Return the length of the box, ie the number of keys
        """
        return len(self._list(*args, **kwargs))

    def __getitem__(self, key, *args, **kwargs):
        """
        Return the File like object associated to a key
        """
        # And if it exist
        if not self.has_key(key, *args, **kwargs):
            raise IndexError

        return self._get(key, *args, **kwargs)

    def __setitem__(self, key, document, *args, **kwargs):
        """
        Let's assign the document to a specific place in the Box
        """
        self._put(key, document, *args, **kwargs)

    def __delitem__(self, key, *args, **kwargs):
        """
        Delete an item from the box
        """
        self._del(key, *args, **kwargs)

    def __iter__(self, *args, **kwargs):
        """
        Let's iterate over keys
        """
        for key in self.keys(*args, **kwargs):
            yield key

    def __contains__(self, key, *args, **kwargs):
        """
        Do we have a key in our Box
        """
        if key in self._list(*args, **kwargs):
            return True
        return False

    def iterkeys(self, *args, **kwargs):
        """
        Let's iterate over keys
        """
        self.__iter__(*args, **kwargs)

    def itervalues(self, *args, **kwargs):
        """
        Let's iterate over values
        """
        for key in self.iterkeys():
            yield self._get(key, *args, **kwargs)

    def keys(self, *args, **kwargs):
        """
        Returns the ordered file list contained in the box, which are the keys.
        """
        return self._list(*args, **kwargs)

    def values(self, *args, **kwargs):
        """
        Returns the ordered file content in the box, values are File like object.
        """
        return [ self._get(doc, *args, **kwargs) for doc in self.keys(*args, **kwargs) ]

    def items(self, *args, **kwargs):
        """
        Return the tuples (key, value) of the document in the Box
        """
        return [ (key, self._get(key, *args, **kwargs),) for key in self.keys(*args, **kwargs) ]

    def has_key(self, name, *args, **kwargs):
        """
        Check if a document with name exist in the box. Name must be a UUID.
        """
        if not name in self._list(*args, **kwargs):
            return False
        return True

    # Below are the method that needs to be subclassed by specific box systems
    def _list(self):
        """
        Returns the list of all items in the box.
        """
        raise NotImplementedError

    def _get(self, name):
        """
        Get a document from the box, should return a File like object
        """
        raise NotImplementedError

    def _put(self, name, document):
        """
        Put a document in a box. document are, generally, File like objects.

        If a document with this name exist, it will be overwritten.
        """
        raise NotImplementedError

    def _del(self, name):
        """
        Remove a document from the box.
        """
        raise NotImplementedError
